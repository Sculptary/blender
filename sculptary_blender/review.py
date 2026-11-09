"""Pull request model selection and comments at canonical cursor coordinates."""

import json
import math
import sys

import bpy
from bpy.props import StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from . import comparison
from .api import SculptaryError
from .review_gltf import PreviewError


def _app():
    return sys.modules[__package__]


class SculptaryReviewModel(PropertyGroup):
    path: StringProperty()
    old_path: StringProperty()
    status: StringProperty()


def clear_models(s):
    s.review_models.clear()
    s.review_model_index = 0
    s.review_models_repo, s.review_models_number = "", 0


def _snapshot(client, repo, number):
    changes = client.pull_changes(repo, number)
    pull = client.pull_request(repo, number)
    if pull["source"]["sha"] != changes["head"]:
        raise SculptaryError(409, "The pull request changed while loading. Refresh its models and try again.")
    return changes, pull


def _store_pull(context, repo, pull):
    s = _app().state(context)
    s.review_repo, s.review_number, s.review_json = repo, pull["number"], json.dumps(pull)


def _error(operator, context, exc):
    app = _app()
    if isinstance(exc, SculptaryError) and exc.status in (401, 403, 404):
        app.pulls.clear_review(app.state(context))
        app.state(context).pull_error = exc.message
    return app.report_error(operator, exc)


def _sides(repo, changes, pull, change):
    base = None if change["status"] == "A" or not changes["base"] else {
        "repository": repo, "path": change.get("old_path") or change["path"], "commit": changes["base"]}
    head = None if change["status"] == "D" else {
        "repository": pull["source"]["repository"], "path": change["path"], "commit": changes["head"]}
    return base, head


def _same_side(actual, expected):
    return actual is None if expected is None else actual is not None and all(actual[key] == value for key, value in expected.items())


class SCULPTARY_OT_load_pull_models(Operator):
    bl_idname = "sculptary.load_pull_models"
    bl_label = "Load changed models"

    def execute(self, context):
        app = _app()
        s, pull = app.state(context), app.pulls.current_review(context)
        clear_models(s)
        if not pull:
            self.report({"WARNING"}, "Select a pull request first")
            return {"CANCELLED"}
        repo = app.current_repo(context)
        try:
            changes, pull = _snapshot(app.client(), repo, pull["number"])
        except SculptaryError as exc:
            return _error(self, context, exc)
        _store_pull(context, repo, pull)
        for change in changes["changes"]:
            if change.get("model_format"):
                row = s.review_models.add()
                row.path, row.old_path, row.status = change["path"], change.get("old_path") or "", change["status"]
        s.review_models_repo, s.review_models_number = repo, pull["number"]
        return {"FINISHED"}


class SCULPTARY_OT_compare_pull_model(Operator):
    bl_idname = "sculptary.compare_pull_model"
    bl_label = "Compare selected model"

    def execute(self, context):
        app = _app()
        s, pull, repo = app.state(context), app.pulls.current_review(context), app.current_repo(context)
        if not pull or s.review_models_repo != repo or s.review_models_number != pull["number"] or not 0 <= s.review_model_index < len(s.review_models):
            self.report({"WARNING"}, "Load and select a changed model first")
            return {"CANCELLED"}
        if comparison.review_info(context.scene):
            self.report({"WARNING"}, "Close the current comparison first")
            return {"CANCELLED"}
        selected = s.review_models[s.review_model_index]
        try:
            client = app.client()
            changes, pull = _snapshot(client, repo, pull["number"])
            change = next((item for item in changes["changes"] if item["path"] == selected.path and item.get("model_format")), None)
            if not change or (change.get("old_path") or "") != selected.old_path or change["status"] != selected.status:
                raise SculptaryError(409, "The changed files have moved. Refresh the model list and try again.")
            _store_pull(context, repo, pull)
            sides = [comparison._asset(client, side["repository"], side["path"], side["commit"]) if side else None
                for side in _sides(repo, changes, pull, change)]
            comparison.open_review(context, client, *sides, repository=repo, path=change["path"],
                server=app.prefs().host, pull_number=pull["number"])
        except (SculptaryError, PreviewError, OSError, RuntimeError) as exc:
            return _error(self, context, exc)
        return {"FINISHED"}


class SCULPTARY_OT_pin_cursor(Operator):
    bl_idname = "sculptary.pin_cursor"
    bl_label = "Post pin at cursor"
    bl_description = "Comment on this exact revision at the 3D cursor, excluding the display offset"

    def execute(self, context):
        app = _app()
        scene, info, pull = context.scene, comparison.review_info(context.scene), app.pulls.current_review(context)
        if not info or not pull or info["pull_number"] != pull["number"] or info["repository"] != app.current_repo(context) or info["server"] != comparison.server_identity(app.prefs().host):
            self.report({"WARNING"}, "Load the matching pull request and server before posting a pin")
            return {"CANCELLED"}
        side, body = scene.sculptary_pin_side, scene.sculptary_pin_body.strip()
        asset = info[side]
        if not asset or not body:
            self.report({"WARNING"}, "Choose a side with geometry and enter a comment")
            return {"CANCELLED"}
        try:
            context.view_layer.update()
            point = comparison.roots(scene)[side].matrix_world.inverted() @ scene.cursor.location
            point = [float(point.x), float(point.z), -float(point.y)]
            if not all(math.isfinite(value) for value in point):
                raise SculptaryError(422, "Place the cursor at a finite position before posting a pin.")
            client, repo, number = app.client(), info["repository"], info["pull_number"]
            changes, latest = _snapshot(client, repo, number)
            change = next((item for item in changes["changes"] if item["path"] == info["path"] and item.get("model_format")), None)
            expected = _sides(repo, changes, latest, change) if change else (None, None)
            if not change or not all(_same_side(info[key], value) for key, value in zip(("base", "head"), expected)):
                raise SculptaryError(409, "The pull request has changed. Reopen the comparison before posting a pin.")
            comment = client.comment_pull_request(repo, number, body, path=asset["path"], commit_sha=asset["commit"],
                spatial_anchor={"point": point, "normal": None, "object": asset["path"], "camera": None, "animation": {"rest": True}})
        except (SculptaryError, ValueError, RuntimeError) as exc:
            return _error(self, context, exc)
        scene.sculptary_pin_body = ""
        scene["sculptary_last_pin"] = comment["id"]
        self.report({"INFO"}, f"Pinned comment posted to pull request #{number}")
        try:
            _store_pull(context, repo, client.pull_request(repo, number))
        except SculptaryError:
            self.report({"WARNING"}, "The comment was posted. Refresh the pull request to see it.")
        return {"FINISHED"}


class SCULPTARY_UL_review_models(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        status = {"A": "Added", "D": "Deleted", "R": "Renamed", "C": "Copied"}.get(item.status, "Changed")
        layout.label(text=item.path, icon="MESH_DATA")
        layout.label(text=status)


class SCULPTARY_PT_pull_models(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Changed models"
    bl_parent_id = "SCULPTARY_PT_pulls"

    def draw(self, context):
        s, layout = _app().state(context), self.layout
        layout.operator("sculptary.load_pull_models", icon="FILE_REFRESH")
        if s.review_models_repo:
            layout.label(text=f"{len(s.review_models)} changed models")
            layout.template_list("SCULPTARY_UL_review_models", "", s, "review_models", s, "review_model_index", rows=3)
            if 0 <= s.review_model_index < len(s.review_models) and s.review_models[s.review_model_index].old_path:
                layout.label(text="Previously " + s.review_models[s.review_model_index].old_path)
            row = layout.row()
            row.enabled = not comparison.review_info(context.scene)
            row.operator("sculptary.compare_pull_model", icon="MOD_MIRROR")


class SCULPTARY_PT_cursor_pin(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Pinned comment"
    bl_parent_id = "SCULPTARY_PT_comparison"

    @classmethod
    def poll(cls, context):
        info = comparison.review_info(context.scene)
        return bool(info and info["pull_number"])

    def draw(self, context):
        scene, layout = context.scene, self.layout
        info = comparison.review_info(scene)
        layout.label(text=f"Pull request #{info['pull_number']}")
        layout.prop(scene, "sculptary_pin_side", expand=True)
        layout.prop(scene, "sculptary_pin_body")
        row = layout.row()
        row.enabled = info[scene.sculptary_pin_side] is not None
        row.operator("sculptary.pin_cursor", icon="PINNED")
        if info[scene.sculptary_pin_side] is None:
            layout.label(text="This side has no model to pin")
        if scene.get("sculptary_last_pin"):
            layout.label(text="Comment posted on Sculptary", icon="CHECKMARK")


DATA_CLASSES = (SculptaryReviewModel,)
UI_CLASSES = (SCULPTARY_OT_load_pull_models, SCULPTARY_OT_compare_pull_model, SCULPTARY_OT_pin_cursor,
    SCULPTARY_UL_review_models, SCULPTARY_PT_pull_models, SCULPTARY_PT_cursor_pin)
