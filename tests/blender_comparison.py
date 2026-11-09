"""Native comparison checks with real GLBs and no network or saved preferences."""

import json
import struct
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sculptary_blender as addon


class Directory:
    def __init__(self, base, head):
        self.files = {"base": base, "head": head}
        self.calls = []
        self.failure = None

    def my_repositories(self):
        return [{"full_name": "fixture/shell", "visibility": "private"}]

    def repository(self, name):
        return {"full_name": name, "default_branch": "main", "is_empty": False}

    def branches(self, name):
        return [{"name": "main", "commit": "a" * 40}, {"name": "fit/v2", "commit": "b" * 40}]

    def assets(self, name, ref=None):
        return [{"path": "models/shell.glb", "status": "ready", "metadata": {}}]

    def pull_requests(self, name, state="open"):
        return {"counts": {"open": 0, "closed": 0, "merged": 0}, "items": []}

    def asset_at(self, name, path, ref):
        side = "base" if ref in ("main", "a" * 40) else "head"
        self.calls.append(("asset", name, path, ref))
        return {"id": side, "commit": ("a" if side == "base" else "b") * 40,
            "path": path, "status": "ready", "standard_preview_url": "/preview?encoding=standard"}

    def download_preview(self, name, asset_id, destination):
        self.calls.append(("download", name, asset_id, destination))
        if self.failure and asset_id == "head":
            if self.failure == "invalid":
                Path(destination).write_bytes(b"invalid GLB")
                return
            raise addon.SculptaryError(409, "Standard preview is being prepared. Retry shortly.")
        Path(destination).write_bytes(self.files[asset_id].read_bytes())


def expect_failure(operator):
    try:
        assert operator() == {"CANCELLED"}
    except RuntimeError:
        pass  # Blender raises for an operator's ERROR report.


def root(scene, side):
    return next(obj for obj in scene.objects if obj.get("sculptary_review_root") == side)


def local_points(scene, side):
    parent = root(scene, side)
    return {tuple(round(value, 4) for value in (parent.matrix_world.inverted() @ obj.matrix_world @ vertex.co))
        for obj in scene.objects if obj.type == "MESH" and obj.get("sculptary_review_side") == side
        for vertex in obj.data.vertices}


def add_animation(path):
    data = path.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + length])
    binary = bytearray(data[28 + length:])
    offset = len(binary)
    binary.extend(struct.pack("<2f6f", 0, 1, 20, 1, -2, 25, 1, -2))
    view, accessor = len(doc["bufferViews"]), len(doc["accessors"])
    doc["bufferViews"].extend([{"buffer": 0, "byteOffset": offset, "byteLength": 8},
        {"buffer": 0, "byteOffset": offset + 8, "byteLength": 24}])
    doc["accessors"].extend([{"bufferView": view, "componentType": 5126, "count": 2,
        "type": "SCALAR", "min": [0], "max": [1]},
        {"bufferView": view + 1, "componentType": 5126, "count": 2, "type": "VEC3"}])
    node = next(i for i, item in enumerate(doc["nodes"]) if item.get("name") == "Cube")
    doc["animations"] = [{"name": "Move", "samplers": [{"input": accessor, "output": accessor + 1}],
        "channels": [{"sampler": 0, "target": {"node": node, "path": "translation"}}]}]
    doc["buffers"][0]["byteLength"] = len(binary)
    encoded = json.dumps(doc).encode()
    encoded += b" " * (-len(encoded) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<II", len(encoded), 0x4e4f534a) + encoded
        + struct.pack("<II", len(binary), 0x004e4942) + binary)


addon.register()
try:
    preferences = bpy.context.preferences.addons.new()
    preferences.module = addon.ADDON
    preferences.preferences.host = "https://sculptary.fixture"
    working = bpy.context.scene
    cube = working.objects["Cube"]
    bpy.ops.object.select_all(action="DESELECT")
    cube.select_set(True)
    bpy.context.view_layer.objects.active = cube
    parent = bpy.data.objects.new("Assembly", None)
    working.collection.objects.link(parent)
    parent.location.x = 2
    parent.select_set(True)
    cube.parent = parent
    with tempfile.TemporaryDirectory(prefix="sculptary-comparison-fixture-") as folder:
        base, head = Path(folder) / "base.glb", Path(folder) / "head.glb"
        cube.location = (3, 2, 1)
        bpy.ops.export_scene.gltf(filepath=str(base), export_format="GLB", use_selection=True)
        add_animation(base)
        cube.location.x += 0.25
        cube.scale.x = 2
        bpy.ops.export_scene.gltf(filepath=str(head), export_format="GLB", use_selection=True)
        before = {obj: obj.matrix_world.copy() for obj in working.objects}
        tracks = len(working.gltf2_animation_tracks) if hasattr(working, "gltf2_animation_tracks") else None
        directory = Directory(base, head)
        addon.client = lambda: directory
        assert bpy.ops.sculptary.refresh() == {"FINISHED"}
        state = addon.state(bpy.context)
        state.compare_base, state.compare_head = "main", "fit/v2"
        state.compare_path = "models/shell.glb"
        assert bpy.ops.sculptary.compare_models() == {"FINISHED"}
        review = bpy.context.scene
        assert review != working and len(review.collection.children) == 2
        info = json.loads(review["sculptary_review"])
        assert info["base"]["commit"] == "a" * 40 and info["head"]["commit"] == "b" * 40
        assert info["working_scene"] == working.name
        assert root(review, "base").location.x < 0 < root(review, "head").location.x
        assert all(obj.hide_select for obj in review.objects)
        assert all(tuple(root(review, side).scale) == (1, 1, 1) for side in ("base", "head"))
        expected_base = {(x, y, z) for x in (4., 6.) for y in (1., 3.) for z in (0., 2.)}
        expected_head = {(x, y, z) for x in (3.25, 7.25) for y in (1., 3.) for z in (0., 2.)}
        assert local_points(review, "base") == expected_base
        assert local_points(review, "head") == expected_head, "Comparison hid the authored placement or scale change"
        assert all(any(obj.type == "MESH" and obj.parent != root(review, side)
            and obj.get("sculptary_review_side") == side for obj in review.objects) for side in ("base", "head"))
        assert (len(working.gltf2_animation_tracks) if hasattr(working, "gltf2_animation_tracks") else None) == tracks, "Import changed the working scene's clip list"
        assert bpy.ops.sculptary.comparison_layout(mode="overlay") == {"FINISHED"}
        assert all(root(review, side).location.length == 0 for side in ("base", "head"))
        assert local_points(review, "head") == expected_head
        assert bpy.ops.sculptary.publish() == {"CANCELLED"}
        assert bpy.ops.sculptary.import_model() == {"CANCELLED"}
        assert {obj: obj.matrix_world for obj in working.objects} == before
        assert not any(Path(call[3]).exists() for call in directory.calls if call[0] == "download")
        # A scene pointer must survive renaming the working scene.
        other = bpy.data.scenes.new("Another project")
        working.name = "Renamed project"
        assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
        assert bpy.context.scene == working
        bpy.data.scenes.remove(other)
        assert bpy.context.scene == working and len(bpy.data.scenes) == 1
        assert {obj: obj.matrix_world for obj in working.objects} == before
        assert len(bpy.data.objects) == len(before)
        for failure in ("pending", "invalid"):
            directory.failure = failure
            expect_failure(bpy.ops.sculptary.compare_models)
            assert bpy.context.scene == working and len(bpy.data.scenes) == 1
            assert len(bpy.data.objects) == len(before), "Failed comparison leaked generated objects"
        directory.failure = None
        assert bpy.ops.sculptary.compare_models() == {"FINISHED"}
        # Preserve an object the user added to a generated scene when closing it.
        foreign = bpy.data.objects.new("User annotation", None)
        bpy.context.scene.collection.objects.link(foreign)
        assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
        assert foreign.name in working.objects
        assert not any(Path(call[3]).exists() for call in directory.calls if call[0] == "download")
        print("BLENDER COMPARISON CHECKS PASSED")
finally:
    addon.unregister()
