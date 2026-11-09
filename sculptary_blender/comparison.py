"""Isolated, aligned review scenes. Source coordinates are never normalized."""

import json
import math
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import bpy
from bpy.props import EnumProperty
from bpy.types import Operator, Panel
from mathutils import Vector

from .api import SculptaryError
from .review_gltf import PreviewError, static_preview

OWNER = "sculptary_review_owner"
DATA = ("objects", "collections", "meshes", "curves", "armatures", "cameras", "lights",
        "materials", "images", "actions", "node_groups")


def _app():
    return sys.modules[__package__]


def server_identity(host):
    parts = urlsplit(host)
    return [parts.scheme.lower(), parts.hostname, parts.port or {"https": 443, "http": 80}.get(parts.scheme), parts.path.rstrip("/")]


def review_info(scene):
    try:
        info = json.loads(scene.get("sculptary_review", ""))
        return info if isinstance(info, dict) and info.get("uid") == scene.get(OWNER) else None
    except (ValueError, TypeError):
        return None


def roots(scene):
    return {obj.get("sculptary_review_root"): obj for obj in scene.objects
        if obj.get(OWNER) == scene.get(OWNER) and obj.get("sculptary_review_root") in ("base", "head")}


def set_layout(scene, mode):
    direction = Vector(scene.get("sculptary_review_direction", (1, 0, 0)))
    for side, root in roots(scene).items():
        root.location = direction * (0 if mode == "overlay" else scene["sculptary_review_spacing"] * (-0.5 if side == "base" else 0.5))
    for obj in scene.objects:
        if obj.type == "MESH" and obj.get(OWNER) == scene.get(OWNER):
            obj.display_type = "WIRE" if mode == "overlay" and obj.get("sculptary_review_side") == "base" else "TEXTURED"
    scene["sculptary_review_layout"] = mode
    bpy.context.view_layer.update()


def _snapshot():
    return {name: set(getattr(bpy.data, name)) for name in DATA}


def _viewports(context):
    return {"screen": context.screen.name, "areas": {str(area.as_pointer()): {
        "location": list(area.spaces.active.region_3d.view_location),
        "rotation": list(area.spaces.active.region_3d.view_rotation),
        "distance": area.spaces.active.region_3d.view_distance,
        "perspective": area.spaces.active.region_3d.view_perspective,
    } for area in context.screen.areas if area.type == "VIEW_3D"}}


def _restore_viewports(context, views):
    if not views or context.screen.name != views["screen"]:
        return
    for area in context.screen.areas:
        saved = views["areas"].get(str(area.as_pointer()))
        if saved and area.type == "VIEW_3D":
            region = area.spaces.active.region_3d
            region.view_location, region.view_rotation = saved["location"], saved["rotation"]
            region.view_distance, region.view_perspective = saved["distance"], saved["perspective"]


def _frame_review(context, scene):
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    smooth = context.preferences.view.smooth_view
    try:
        context.preferences.view.smooth_view = 0
        for obj in scene.objects:
            obj.select_set(False)
        for obj in meshes:
            obj.hide_select = False
            obj.select_set(True)
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                if area.spaces.active.region_3d.view_perspective == "CAMERA":
                    area.spaces.active.region_3d.view_perspective = "PERSP"
                region = next((item for item in area.regions if item.type == "WINDOW"), None)
                if region:
                    with context.temp_override(area=area, region=region):
                        bpy.ops.view3d.view_selected(use_all_regions=False)
    finally:
        for obj in scene.objects:
            obj.select_set(False)
            obj.hide_select = True
        context.preferences.view.smooth_view = smooth


def _tag_new(before, uid):
    for name, previous in before.items():
        for block in set(getattr(bpy.data, name)) - previous:
            block[OWNER] = uid


def _dispose(scene, working):
    """Remove generated data only; retain user additions and externally linked data."""
    uid = scene[OWNER]
    for obj in list(scene.objects):
        external = any(collection.get(OWNER) != uid or collection.users > 1 for collection in obj.users_collection)
        if obj.get(OWNER) == uid and not external:
            bpy.data.objects.remove(obj, do_unlink=True)
        elif not external:
            working.collection.objects.link(obj)
    bpy.data.scenes.remove(scene)
    # Removing objects releases meshes, materials, images and actions in order.
    for _ in range(2):
        for name in DATA[1:]:
            blocks = getattr(bpy.data, name)
            for block in list(blocks):
                if block.get(OWNER) == uid and block.users == 0:
                    blocks.remove(block)


def _asset(client, repo, path, ref):
    asset = client.asset_at(repo, path, ref)
    if "standard_preview_url" not in asset:
        raise SculptaryError(409, "This server needs an update to provide desktop review previews.")
    if asset["status"] not in ("ready", "pending", "processing"):
        raise SculptaryError(409, "This model has no review preview. Check its processing status on Sculptary.")
    return {"repository": repo, "path": path, "commit": asset["commit"], "asset_id": asset["id"]}


def _import_side(context, scene, side, source, uid):
    collection = bpy.data.collections.new("Base" if side == "base" else "Head")
    collection[OWNER] = uid
    scene.collection.children.link(collection)
    root = bpy.data.objects.new(collection.name + " revision", None)
    root[OWNER], root["sculptary_review_root"], root["sculptary_review_side"] = uid, side, side
    collection.objects.link(root)
    if source is None:
        root["sculptary_review_absent"] = True
        return []
    source, clips = static_preview(source, source.with_name(side + "-static.glb"))
    root["sculptary_review_clips"] = clips
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(source))
    context.view_layer.update()
    imported = set(bpy.data.objects) - before
    points = []
    for obj in imported:
        obj[OWNER], obj["sculptary_review_side"], obj["sculptary_review_root"] = uid, side, ""
        collection.objects.link(obj)
        for other in list(obj.users_collection):
            if other != collection:
                other.objects.unlink(obj)
        if obj.parent not in imported:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_world = world
        if obj.type == "MESH" and obj.data.vertices:
            points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    if not points or any(not math.isfinite(value) for point in points for value in point):
        raise SculptaryError(422, "The preview contains no finite mesh geometry to compare.")
    return points


def open_review(context, client, base, head, *, repository, path, server, pull_number=0):
    working = context.scene
    if context.mode != "OBJECT":
        raise SculptaryError(409, "Switch to object mode before comparing revisions.")
    if review_info(working):
        raise SculptaryError(409, "Close the current comparison before opening another.")
    with tempfile.TemporaryDirectory(prefix="sculptary-review-") as folder:
        sources = {}
        for side, asset in (("base", base), ("head", head)):
            source = Path(folder) / (side + ".glb") if asset else None
            if asset:
                client.download_preview(asset["repository"], asset["asset_id"], str(source))
            sources[side] = source
        before, uid, viewports = _snapshot(), uuid.uuid4().hex, _viewports(context)
        scene = bpy.data.scenes.new("Sculptary comparison")
        scene[OWNER] = scene.collection[OWNER] = uid
        scene["sculptary_review"] = json.dumps({"uid": uid, "working_scene": working.name,
            "repository": repository, "path": path, "server": server_identity(server),
            "base": base, "head": head, "pull_number": pull_number, "viewports": viewports})
        scene.sculptary_review_working = working
        context.window.scene = scene
        try:
            points = []
            for side in ("base", "head"):
                points.extend(_import_side(context, scene, side, sources[side], uid))
            if not points:
                raise SculptaryError(422, "There is no model geometry in this comparison.")
            extents = [max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)]
            area = context.area if context.area and context.area.type == "VIEW_3D" else next((item for item in context.screen.areas if item.type == "VIEW_3D"), None)
            direction = area.spaces.active.region_3d.view_rotation @ Vector((1, 0, 0)) if area else Vector((1, 0, 0))
            projected = [point.dot(direction) for point in points]
            scene["sculptary_review_direction"] = list(direction)
            scene["sculptary_review_spacing"] = max(max(projected) - min(projected), max(extents) * 0.1, 0.00001) * 1.2
            set_layout(scene, "side_by_side")
            _frame_review(context, scene)
        except Exception:
            _tag_new(before, uid)
            context.window.scene = working
            _restore_viewports(context, viewports)
            _dispose(scene, working)
            raise
        _tag_new(before, uid)
    return scene


class SCULPTARY_OT_compare_models(Operator):
    bl_idname = "sculptary.compare_models"
    bl_label = "Compare revisions"

    def execute(self, context):
        app = _app()
        s, repo = app.state(context), app.current_repo(context)
        path = s.compare_path.strip() or (s.assets[s.asset_index].path if 0 <= s.asset_index < len(s.assets) else "")
        base_ref, head_ref = s.compare_base.strip(), s.compare_head.strip() or app.current_branch(context)
        if not repo or not path or not base_ref or not head_ref:
            self.report({"WARNING"}, "Choose a model and enter base and head refs")
            return {"CANCELLED"}
        try:
            client = app.client()
            base = _asset(client, repo, s.compare_base_path.strip() or path, base_ref)
            head = _asset(client, repo, path, head_ref)
            open_review(context, client, base, head, repository=repo, path=path, server=app.prefs().host)
        except (SculptaryError, PreviewError, OSError, RuntimeError) as exc:
            return app.report_error(self, exc)
        return {"FINISHED"}


class SCULPTARY_OT_comparison_layout(Operator):
    bl_idname = "sculptary.comparison_layout"
    bl_label = "Comparison layout"
    mode: EnumProperty(items=[("side_by_side", "Side by side", ""), ("overlay", "Overlay", "")])

    def execute(self, context):
        if not review_info(context.scene):
            return {"CANCELLED"}
        set_layout(context.scene, self.mode)
        return {"FINISHED"}


class SCULPTARY_OT_close_comparison(Operator):
    bl_idname = "sculptary.close_comparison"
    bl_label = "Close comparison"
    bl_description = "Return to the working scene and remove generated comparison data"

    def execute(self, context):
        scene = context.scene
        info = review_info(scene)
        if not info:
            return {"CANCELLED"}
        if context.mode != "OBJECT":
            self.report({"WARNING"}, "Switch to object mode before closing the comparison")
            return {"CANCELLED"}
        working = scene.sculptary_review_working or bpy.data.scenes.get(info["working_scene"])
        if working is None or working == scene:
            working = next((item for item in bpy.data.scenes if not review_info(item)), None) or bpy.data.scenes.new("Scene")
        context.window.scene = working
        _restore_viewports(context, info.get("viewports"))
        _dispose(scene, working)
        return {"FINISHED"}


class SCULPTARY_PT_comparison(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Compare revisions"
    bl_parent_id = "SCULPTARY_PT_main"

    def draw(self, context):
        app = _app()
        s, layout = app.state(context), self.layout
        info = review_info(context.scene)
        if info:
            layout.label(text="Static review in the authored pose")
            layout.label(text=info["path"])
            for side in ("base", "head"):
                asset = info[side]
                layout.label(text=side.capitalize() + ": " + (asset["commit"][:7] if asset else "Absent"))
            row = layout.row(align=True)
            for mode, label in (("side_by_side", "Side by side"), ("overlay", "Overlay")):
                row.operator("sculptary.comparison_layout", text=label,
                    depress=context.scene.get("sculptary_review_layout") == mode).mode = mode
            layout.operator("sculptary.close_comparison", icon="LOOP_BACK")
            return
        layout.prop(s, "compare_path")
        if not s.compare_path and 0 <= s.asset_index < len(s.assets):
            layout.label(text="Selected: " + s.assets[s.asset_index].path)
        layout.prop_search(s, "compare_base", s, "branches")
        layout.prop_search(s, "compare_head", s, "branches")
        layout.prop(s, "compare_base_path")
        layout.operator("sculptary.compare_models", icon="MOD_MIRROR")


UI_CLASSES = (SCULPTARY_OT_compare_models, SCULPTARY_OT_comparison_layout,
    SCULPTARY_OT_close_comparison, SCULPTARY_PT_comparison)
