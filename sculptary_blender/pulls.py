"""Pull request controls. Scene comparison is kept separate from these API views."""

import json
import sys
from urllib.parse import quote

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup, UIList

from .api import SculptaryError


def _app():
    return sys.modules[__package__]


class SculptaryPull(PropertyGroup):
    number: IntProperty()
    title: StringProperty()
    state: StringProperty()
    draft: BoolProperty()


def clear_review(s, *, drafts=False):
    s.pulls.clear()
    s.pull_repo = ""
    s.pull_index = -1
    s.pull_total = -1
    s.review_repo = ""
    s.review_number = 0
    s.review_json = ""
    s.pull_error = ""
    if drafts:
        s.pull_title = ""
        s.pull_description = ""
        s.pull_target = ""
        s.pull_draft = False
        s.pull_filter = "open"


def current_review(context):
    s = _app().state(context)
    if s.review_repo != _app().current_repo(context) or not s.review_number or not s.review_json:
        return None
    try:
        review = json.loads(s.review_json)
        return review if isinstance(review, dict) and review.get("number") == s.review_number else None
    except ValueError:
        return None


def on_selection(s, context):
    if not s.updating and 0 <= s.pull_index < len(s.pulls):
        try:
            bpy.ops.sculptary.load_pull(number=s.pulls[s.pull_index].number)
        except RuntimeError:
            pass  # The operator already reported the failure and cleared stale data.


def on_filter(s, context):
    if not s.updating:
        try:
            bpy.ops.sculptary.load_pulls()
        except RuntimeError:
            pass


def open_url(url):
    bpy.ops.wm.url_open(url=url)


class SCULPTARY_OT_load_pulls(Operator):
    bl_idname = "sculptary.load_pulls"
    bl_label = "Refresh pull requests"

    select_number: IntProperty(options={"HIDDEN"})

    def execute(self, context):
        app = _app()
        s, repo = app.state(context), app.current_repo(context)
        previous = current_review(context)
        previous_number = previous["number"] if previous else 0
        s.updating = True
        try:
            clear_review(s)
            if not repo:
                return {"FINISHED"}
            data = app.client().pull_requests(repo, state=s.pull_filter)
            for item in data["items"]:
                row = s.pulls.add()
                row.number, row.title, row.state = item["number"], item["title"], item["state"]
                row.draft = item.get("draft", False)
            counts = data.get("counts", {})
            values = [counts.get(key) for key in (("open", "closed", "merged") if s.pull_filter == "all" else (s.pull_filter,))]
            s.pull_total = sum(values) if all(type(value) is int and value >= 0 for value in values) else -1
            s.pull_repo = repo
            selected = self.select_number or (previous_number if any(row.number == previous_number for row in s.pulls) else 0)
            if not selected and s.pulls:
                selected = s.pulls[0].number
            s.pull_index = next((i for i, row in enumerate(s.pulls) if row.number == selected), -1)
        except SculptaryError as exc:
            s.pull_error = exc.message
            return app.report_error(self, exc)
        finally:
            s.updating = False
        if selected:
            bpy.ops.sculptary.load_pull(number=selected)
        return {"FINISHED"}


class SCULPTARY_OT_load_pull(Operator):
    bl_idname = "sculptary.load_pull"
    bl_label = "Load pull request"

    number: IntProperty(min=0, options={"HIDDEN"})

    def execute(self, context):
        app = _app()
        s, repo = app.state(context), app.current_repo(context)
        number = self.number or s.pull_lookup_number
        s.review_repo, s.review_number, s.review_json, s.pull_error = "", 0, "", ""
        if not repo or number < 1:
            return {"CANCELLED"}
        try:
            data = app.client().pull_request(repo, number)
        except SculptaryError as exc:
            s.pull_error = exc.message
            return app.report_error(self, exc)
        s.updating = True
        try:
            s.review_repo, s.review_number, s.review_json = repo, data["number"], json.dumps(data)
            s.pull_index = next((i for i, row in enumerate(s.pulls) if row.number == data["number"]), -1)
        finally:
            s.updating = False
        return {"FINISHED"}


class SCULPTARY_OT_open_pull(Operator):
    bl_idname = "sculptary.open_pull"
    bl_label = "Open pull request on Sculptary"

    def execute(self, context):
        review = current_review(context)
        if review is None:
            self.report({"WARNING"}, "Select a pull request first")
            return {"CANCELLED"}
        app = _app()
        path = quote(app.current_repo(context), safe="/")
        open_url(f"{app.prefs().host.rstrip('/')}/{path}/pulls/{review['number']}")
        return {"FINISHED"}


class SCULPTARY_OT_create_pull(Operator):
    bl_idname = "sculptary.create_pull"
    bl_label = "Open pull request"

    def execute(self, context):
        app = _app()
        s, repo, branch = app.state(context), app.current_repo(context), app.current_branch(context)
        title, target = s.pull_title.strip(), s.pull_target.strip()
        if not repo or not branch or s.is_empty or not title or not target or target == branch:
            self.report({"WARNING"}, "Choose different source and target branches and enter a title")
            return {"CANCELLED"}
        try:
            data = app.client().create_pull_request(repo, title, branch, target_branch=target,
                body=s.pull_description, draft=s.pull_draft)
        except SculptaryError as exc:
            s.pull_error = exc.message
            return app.report_error(self, exc)
        s.pull_title, s.pull_description, s.pull_draft = "", "", False
        s.updating = True
        s.pull_filter = "open"
        s.updating = False
        bpy.ops.sculptary.load_pulls(select_number=data["number"])
        self.report({"INFO"}, f"Opened pull request #{data['number']}")
        return {"FINISHED"}


class SCULPTARY_UL_pulls(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.label(text=f"#{item.number} {item.title}")
        layout.label(text="Draft" if item.draft else item.state.capitalize())


class SCULPTARY_PT_pulls(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Pull requests"
    bl_parent_id = "SCULPTARY_PT_main"

    def draw(self, context):
        app = _app()
        s, layout = app.state(context), self.layout
        row = layout.row(align=True)
        row.prop(s, "pull_filter", text="")
        row.operator("sculptary.load_pulls", text="", icon="FILE_REFRESH")
        if s.pull_error:
            layout.label(text=s.pull_error, icon="ERROR")
        if s.pulls:
            layout.template_list("SCULPTARY_UL_pulls", "", s, "pulls", s, "pull_index", rows=4)
            if s.pull_total >= 0:
                layout.label(text=f"Showing {len(s.pulls)} of {s.pull_total} pull requests")
        elif not s.pull_error:
            layout.label(text="No matching pull requests")
        row = layout.row(align=True)
        row.prop(s, "pull_lookup_number")
        row.operator("sculptary.load_pull", text="Load by number").number = s.pull_lookup_number
        review = current_review(context)
        if review:
            layout.label(text=f"#{review['number']} {review['title']}")
            layout.label(text=review["source"]["repository"] + ": " + review["source"]["branch"])
            layout.label(text="Into " + review["target"]["branch"])
            layout.operator("sculptary.open_pull", icon="URL")


class SCULPTARY_PT_create_pull(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Open a pull request"
    bl_parent_id = "SCULPTARY_PT_pulls"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        app = _app()
        s, layout = app.state(context), self.layout
        layout.label(text="From " + (app.current_branch(context) or "no selected branch"))
        layout.prop_search(s, "pull_target", s, "branches", text="Into branch")
        layout.prop(s, "pull_title")
        layout.prop(s, "pull_description")
        layout.prop(s, "pull_draft")
        layout.operator("sculptary.create_pull", icon="ADD")


DATA_CLASSES = (SculptaryPull,)
UI_CLASSES = (SCULPTARY_OT_load_pulls, SCULPTARY_OT_load_pull, SCULPTARY_OT_open_pull,
    SCULPTARY_OT_create_pull, SCULPTARY_UL_pulls, SCULPTARY_PT_pulls, SCULPTARY_PT_create_pull)
