"""Sculptary for Blender: sign in, browse your repositories, publish the current
scene as GLB, import models and inspect a file's version history."""

bl_info = {
    "name": "Sculptary",
    "author": "Sculptary",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Sculptary",
    "description": "Version control and collaboration for 3D",
    "doc_url": "https://github.com/Sculptary/blender",
    "category": "Import-Export",
}

import os
import tempfile

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList

from .api import Client, SculptaryError
from . import comparison, pulls

ADDON = __package__ or __name__


def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


def client() -> Client:
    p = prefs()
    return Client(p.host, p.token)


def _credentials_changed(self, context):
    self.username = ""
    manager = getattr(context, "window_manager", None)
    s = getattr(manager, "sculptary", None)
    if s is None:
        return
    previous = s.updating
    s.updating = True
    try:
        s.repos.clear()
        s.branches.clear()
        s.assets.clear()
        s.history.clear()
        s.loaded_repo, s.default_branch, s.new_branch_name = "", "", ""
        s.is_empty = False
        s.compare_base, s.compare_head, s.compare_path, s.compare_base_path = "", "", "", ""
        pulls.clear_review(s, drafts=True)
    finally:
        s.updating = previous


class SculptaryPreferences(AddonPreferences):
    bl_idname = ADDON

    host: StringProperty(name="Host", default="https://sculptary.com", update=_credentials_changed)
    token: StringProperty(name="Access token", subtype="PASSWORD", description="Create one at Settings > Tokens with repo:write and user scopes", update=_credentials_changed)
    username: StringProperty(name="Signed in as", default="")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "host")
        col.prop(self, "token")
        row = col.row()
        row.operator("sculptary.sign_in", icon="LINKED")
        if self.username:
            row.label(text=f"Signed in as {self.username}")


class SculptaryRepo(PropertyGroup):
    full_name: StringProperty()
    visibility: StringProperty()


class SculptaryAsset(PropertyGroup):
    path: StringProperty()
    status: StringProperty()
    triangles: IntProperty(default=-1)


class SculptaryBranch(PropertyGroup):
    name: StringProperty()
    commit: StringProperty()
    protected: BoolProperty()
    default: BoolProperty()


class SculptaryCommit(PropertyGroup):
    sha: StringProperty()
    message: StringProperty()
    author: StringProperty()
    date: StringProperty()


def _on_repo_change(self, context):
    if not self.updating:
        bpy.ops.sculptary.load_repository()


def _on_branch_change(self, context):
    if not self.updating:
        bpy.ops.sculptary.load_assets()


class SculptaryState(PropertyGroup):
    repos: CollectionProperty(type=SculptaryRepo)
    repo_index: IntProperty(update=_on_repo_change)
    branches: CollectionProperty(type=SculptaryBranch)
    branch_index: IntProperty(update=_on_branch_change)
    default_branch: StringProperty()
    is_empty: BoolProperty()
    loaded_repo: StringProperty()
    updating: BoolProperty(options={"HIDDEN"})
    new_branch_name: StringProperty(name="New branch")
    pulls: CollectionProperty(type=pulls.SculptaryPull)
    pull_index: IntProperty(default=-1, update=pulls.on_selection)
    pull_filter: EnumProperty(name="State", items=[("open", "Open", ""), ("closed", "Closed", ""), ("merged", "Merged", ""), ("all", "All", "")], update=pulls.on_filter)
    pull_repo: StringProperty()
    pull_total: IntProperty(default=-1)
    pull_error: StringProperty()
    pull_lookup_number: IntProperty(name="Number", default=1, min=1)
    review_repo: StringProperty()
    review_number: IntProperty()
    review_json: StringProperty(options={"HIDDEN"})
    pull_title: StringProperty(name="Title", maxlen=256)
    pull_description: StringProperty(name="Description", maxlen=65536)
    pull_target: StringProperty(name="Into branch")
    pull_draft: BoolProperty(name="Draft")
    compare_base: StringProperty(name="Base ref")
    compare_head: StringProperty(name="Head ref", description="Leave blank to use the selected branch")
    compare_path: StringProperty(name="Model path", description="Leave blank to use the selected model")
    compare_base_path: StringProperty(name="Previous path", description="Optional path before a rename")
    assets: CollectionProperty(type=SculptaryAsset)
    asset_index: IntProperty()
    history: CollectionProperty(type=SculptaryCommit)
    publish_path: StringProperty(name="Path", default="models/scene.glb")
    publish_message: StringProperty(name="Message", default="Update model from Blender")
    selected_only: BoolProperty(name="Selected objects only", default=False)
    new_repo_name: StringProperty(name="New repository")
    new_repo_private: BoolProperty(name="Private", default=True)


def state(context) -> SculptaryState:
    return context.window_manager.sculptary


def current_repo(context) -> str | None:
    s = state(context)
    if 0 <= s.repo_index < len(s.repos):
        return s.repos[s.repo_index].full_name
    return None


def current_branch(context) -> str | None:
    s = state(context)
    if s.loaded_repo != current_repo(context):
        return None
    if 0 <= s.branch_index < len(s.branches):
        return s.branches[s.branch_index].name
    return s.default_branch if s.is_empty and s.default_branch else None


def report_error(op: Operator, exc: Exception) -> set:
    op.report({"ERROR"}, getattr(exc, "message", str(exc)))
    return {"CANCELLED"}


class SCULPTARY_OT_sign_in(Operator):
    bl_idname = "sculptary.sign_in"
    bl_label = "Sign in"
    bl_description = "Verify the access token and load your repositories"

    def execute(self, context):
        try:
            me = client().me()
        except SculptaryError as exc:
            return report_error(self, exc)
        prefs().username = me["username"]
        bpy.ops.sculptary.refresh()
        self.report({"INFO"}, f"Signed in as {me['username']}")
        return {"FINISHED"}


class SCULPTARY_OT_refresh(Operator):
    bl_idname = "sculptary.refresh"
    bl_label = "Refresh"
    bl_description = "Reload repositories and models"

    def execute(self, context):
        s = state(context)
        previous = current_repo(context)
        try:
            repos = client().my_repositories()
        except SculptaryError as exc:
            return report_error(self, exc)
        s.updating = True
        try:
            s.repos.clear()
            for r in repos:
                item = s.repos.add()
                item.full_name, item.visibility = r["full_name"], r["visibility"]
            s.repo_index = next((i for i, repo in enumerate(s.repos) if repo.full_name == previous), 0)
        finally:
            s.updating = False
        bpy.ops.sculptary.load_repository()
        return {"FINISHED"}


class SCULPTARY_OT_load_repository(Operator):
    bl_idname = "sculptary.load_repository"
    bl_label = "Load branches"

    select_branch: StringProperty(options={"HIDDEN"})

    def execute(self, context):
        s = state(context)
        repo = current_repo(context)
        previous = self.select_branch or current_branch(context)
        same_repo = s.loaded_repo == repo
        review_number = s.review_number if same_repo else 0
        s.updating = True
        try:
            s.branches.clear()
            s.assets.clear()
            s.history.clear()
            pulls.clear_review(s, drafts=not same_repo)
            s.loaded_repo = ""
            s.default_branch = ""
            s.is_empty = False
            if not repo:
                return {"FINISHED"}
            c = client()
            metadata = c.repository(repo)
            branches = c.branches(repo) if not metadata["is_empty"] else []
            for branch in branches:
                item = s.branches.add()
                item.name, item.commit = branch["name"], branch["commit"]
                item.protected, item.default = branch.get("protected", False), branch.get("default", False)
            s.default_branch, s.is_empty = metadata["default_branch"], metadata["is_empty"]
            if not same_repo or not s.compare_base:
                s.compare_base, s.compare_head, s.compare_path, s.compare_base_path = s.default_branch, "", "", ""
            if not s.pull_target:
                s.pull_target = s.default_branch
            desired = previous if any(branch.name == previous for branch in s.branches) else s.default_branch
            s.branch_index = next((i for i, branch in enumerate(s.branches) if branch.name == desired), 0)
            s.loaded_repo = repo
        except SculptaryError as exc:
            return report_error(self, exc)
        finally:
            s.updating = False
        bpy.ops.sculptary.load_assets()
        bpy.ops.sculptary.load_pulls(select_number=review_number)
        return {"FINISHED"}


class SCULPTARY_OT_create_branch(Operator):
    bl_idname = "sculptary.create_branch"
    bl_label = "Create branch"

    def execute(self, context):
        s = state(context)
        repo, branch, name = current_repo(context), current_branch(context), s.new_branch_name.strip()
        if not repo or not branch or s.is_empty or not name:
            self.report({"WARNING"}, "Select an existing branch and enter a new branch name")
            return {"CANCELLED"}
        try:
            client().create_branch(repo, name, branch)
        except SculptaryError as exc:
            return report_error(self, exc)
        s.new_branch_name = ""
        bpy.ops.sculptary.load_repository(select_branch=name)
        return {"FINISHED"}


class SCULPTARY_OT_load_assets(Operator):
    bl_idname = "sculptary.load_assets"
    bl_label = "Load models"

    def execute(self, context):
        s = state(context)
        s.assets.clear()
        s.history.clear()
        repo = current_repo(context)
        branch = current_branch(context)
        if not repo or not branch or s.is_empty:
            return {"FINISHED"}
        try:
            assets = client().assets(repo, ref=branch)
        except SculptaryError as exc:
            return report_error(self, exc)
        for a in assets:
            item = s.assets.add()
            item.path, item.status = a["path"], a["status"]
            triangles = (a.get("metadata") or {}).get("triangle_count")
            item.triangles = int(triangles) if triangles is not None else -1
        return {"FINISHED"}


class SCULPTARY_OT_import(Operator):
    bl_idname = "sculptary.import_model"
    bl_label = "Import"
    bl_description = "Download the selected model and import it into the scene"

    def execute(self, context):
        if comparison.review_info(context.scene):
            self.report({"WARNING"}, "Close the comparison before importing into your working scene")
            return {"CANCELLED"}
        s = state(context)
        repo = current_repo(context)
        if not repo or not (0 <= s.asset_index < len(s.assets)):
            self.report({"WARNING"}, "Select a model first")
            return {"CANCELLED"}
        path = s.assets[s.asset_index].path
        ext = os.path.splitext(path)[1].lower()
        branch = current_branch(context)
        if not branch:
            self.report({"WARNING"}, "Select a branch first")
            return {"CANCELLED"}
        importers = {
            ".glb": bpy.ops.import_scene.gltf,
            ".gltf": bpy.ops.import_scene.gltf,
            ".obj": bpy.ops.wm.obj_import,
            ".stl": bpy.ops.wm.stl_import,
            ".ply": bpy.ops.wm.ply_import,
        }
        if ext not in importers:
            self.report({"WARNING"}, f"{ext} files cannot be imported yet")
            return {"CANCELLED"}
        try:
            with tempfile.TemporaryDirectory(prefix="sculptary-") as folder:
                tmp = os.path.join(folder, "model" + ext)
                client().download_file(repo, path, tmp, ref=branch)
                importers[ext](filepath=tmp)
        except (SculptaryError, OSError, RuntimeError) as exc:
            return report_error(self, exc)
        self.report({"INFO"}, f"Imported {path}")
        return {"FINISHED"}


class SCULPTARY_OT_history(Operator):
    bl_idname = "sculptary.history"
    bl_label = "History"
    bl_description = "Show recent commits that changed the selected model"

    def execute(self, context):
        s = state(context)
        repo = current_repo(context)
        if not repo or not (0 <= s.asset_index < len(s.assets)):
            return {"CANCELLED"}
        try:
            commits = client().history(repo, s.assets[s.asset_index].path, ref=current_branch(context))
        except SculptaryError as exc:
            return report_error(self, exc)
        s.history.clear()
        for c in commits:
            item = s.history.add()
            item.sha = c["oid"][:7]
            item.message = c["message"].split("\n", 1)[0]
            item.author = c["author"].get("username") or c["author"]["name"]
            item.date = c["committer"]["date"][:10]
        return {"FINISHED"}


def export_glb(path: str, selected_only: bool) -> None:
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=selected_only, export_apply=True)


class SCULPTARY_OT_publish(Operator):
    bl_idname = "sculptary.publish"
    bl_label = "Publish"
    bl_description = "Export the scene as GLB and commit it to the selected repository"

    def execute(self, context):
        if comparison.review_info(context.scene):
            self.report({"WARNING"}, "Close the comparison before publishing your working scene")
            return {"CANCELLED"}
        s = state(context)
        repo = current_repo(context)
        if not repo:
            self.report({"WARNING"}, "Select or create a repository first")
            return {"CANCELLED"}
        branch = current_branch(context)
        if not branch:
            self.report({"WARNING"}, "Select a branch first")
            return {"CANCELLED"}
        target = s.publish_path.strip().lstrip("/") or "models/scene.glb"
        if not target.lower().endswith(".glb"):
            target += ".glb"
        try:
            with tempfile.TemporaryDirectory(prefix="sculptary-") as folder:
                local = os.path.join(folder, "model.glb")
                export_glb(local, s.selected_only)
                result = client().upload(repo, {target: local}, s.publish_message or "Update model from Blender", branch=branch)
        except (SculptaryError, OSError, RuntimeError) as exc:
            return report_error(self, exc)
        self.report({"INFO"}, f"Committed {target} as {result['commit'][:7]}")
        bpy.ops.sculptary.load_repository()
        return {"FINISHED"}


class SCULPTARY_OT_create_repo(Operator):
    bl_idname = "sculptary.create_repo"
    bl_label = "Create repository"

    def execute(self, context):
        s = state(context)
        name = s.new_repo_name.strip()
        if not name:
            self.report({"WARNING"}, "Enter a repository name")
            return {"CANCELLED"}
        try:
            repo = client().create_repository(name, s.new_repo_private)
        except SculptaryError as exc:
            return report_error(self, exc)
        bpy.ops.sculptary.refresh()
        for i, r in enumerate(s.repos):
            if r.full_name == repo["full_name"]:
                s.repo_index = i
        s.new_repo_name = ""
        return {"FINISHED"}


class SCULPTARY_OT_open_in_browser(Operator):
    bl_idname = "sculptary.open_browser"
    bl_label = "Open on Sculptary"

    def execute(self, context):
        repo = current_repo(context)
        if repo:
            bpy.ops.wm.url_open(url=f"{prefs().host}/{repo}")
        return {"FINISHED"}


class SCULPTARY_UL_repos(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.label(text=item.full_name, icon="LOCKED" if item.visibility == "private" else "WORLD")


class SCULPTARY_UL_assets(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        row = layout.row()
        row.label(text=item.path, icon="MESH_DATA")
        row.label(text=(f"{item.triangles:,} triangles" if item.triangles >= 0 else "Triangles unknown") if item.status == "ready" else item.status)


class SCULPTARY_UL_branches(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        layout.label(text=item.name, icon="LOCKED" if item.protected else "OUTLINER_COLLECTION")
        if item.default:
            layout.label(text="Default")


class SCULPTARY_PT_main(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Sculptary"

    def draw(self, context):
        layout = self.layout
        p = prefs()
        s = state(context)
        if not p.token:
            layout.label(text="Add an access token in the add-on preferences.")
            layout.operator("preferences.addon_show", text="Open preferences").module = ADDON
            return
        row = layout.row()
        row.label(text=p.username or "Not verified", icon="USER")
        row.operator("sculptary.refresh", text="", icon="FILE_REFRESH")
        layout.template_list("SCULPTARY_UL_repos", "", s, "repos", s, "repo_index", rows=4)
        row = layout.row(align=True)
        row.prop(s, "new_repo_name", text="")
        row.prop(s, "new_repo_private", text="", icon="LOCKED")
        row.operator("sculptary.create_repo", text="", icon="ADD")
        layout.operator("sculptary.open_browser", icon="URL")
        layout.label(text="Branch")
        if s.branches:
            layout.template_list("SCULPTARY_UL_branches", "", s, "branches", s, "branch_index", rows=3)
            row = layout.row(align=True)
            row.prop(s, "new_branch_name", text="")
            row.operator("sculptary.create_branch", text="", icon="ADD")
        elif s.is_empty:
            layout.label(text="Publish the first model to create " + s.default_branch)
        else:
            layout.label(text="No branch selected")


class SCULPTARY_PT_models(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Models"
    bl_parent_id = "SCULPTARY_PT_main"

    def draw(self, context):
        s = state(context)
        layout = self.layout
        layout.template_list("SCULPTARY_UL_assets", "", s, "assets", s, "asset_index", rows=4)
        row = layout.row(align=True)
        row.operator("sculptary.import_model", icon="IMPORT")
        row.operator("sculptary.history", icon="TIME")
        for c in s.history[:8]:
            layout.label(text=f"{c.sha}  {c.date}  {c.author}: {c.message}")


class SCULPTARY_PT_publish(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Sculptary"
    bl_label = "Publish"
    bl_parent_id = "SCULPTARY_PT_main"

    def draw(self, context):
        s = state(context)
        col = self.layout.column()
        branch = current_branch(context)
        col.label(text="Publish to " + branch if branch else "Select a branch")
        col.prop(s, "publish_path")
        col.prop(s, "publish_message")
        col.prop(s, "selected_only")
        col.operator("sculptary.publish", icon="EXPORT")


CLASSES = (
    SculptaryPreferences, SculptaryRepo, SculptaryAsset, SculptaryBranch, SculptaryCommit, *pulls.DATA_CLASSES, SculptaryState,
    SCULPTARY_OT_sign_in, SCULPTARY_OT_refresh, SCULPTARY_OT_load_repository, SCULPTARY_OT_create_branch, SCULPTARY_OT_load_assets, SCULPTARY_OT_import, SCULPTARY_OT_history,
    SCULPTARY_OT_publish, SCULPTARY_OT_create_repo, SCULPTARY_OT_open_in_browser,
    SCULPTARY_UL_repos, SCULPTARY_UL_assets, SCULPTARY_UL_branches, SCULPTARY_PT_main, SCULPTARY_PT_models, SCULPTARY_PT_publish,
    *pulls.UI_CLASSES, *comparison.UI_CLASSES,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.sculptary = bpy.props.PointerProperty(type=SculptaryState)
    bpy.types.Scene.sculptary_review_working = bpy.props.PointerProperty(type=bpy.types.Scene)


def unregister():
    del bpy.types.Scene.sculptary_review_working
    del bpy.types.WindowManager.sculptary
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

