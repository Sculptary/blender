"""Sculptary for Blender: sign in, browse your repositories, publish the current
scene as GLB, import models and inspect a file's version history."""

bl_info = {
    "name": "Sculptary",
    "author": "Sculptary",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Sculptary",
    "description": "Version control and collaboration for 3D",
    "doc_url": "https://github.com/Sculptary/blender",
    "category": "Import-Export",
}

import os
import tempfile

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences, Operator, Panel, PropertyGroup, UIList

from .api import Client, SculptaryError

ADDON = __package__ or __name__


def prefs():
    return bpy.context.preferences.addons[ADDON].preferences


def client() -> Client:
    p = prefs()
    return Client(p.host, p.token)


class SculptaryPreferences(AddonPreferences):
    bl_idname = ADDON

    host: StringProperty(name="Host", default="https://sculptary.com")
    token: StringProperty(name="Access token", subtype="PASSWORD", description="Create one at Settings > Tokens with repo:write and user scopes")
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
    triangles: IntProperty()


class SculptaryCommit(PropertyGroup):
    sha: StringProperty()
    message: StringProperty()
    author: StringProperty()
    date: StringProperty()


def _on_repo_change(self, context):
    bpy.ops.sculptary.load_assets()


class SculptaryState(PropertyGroup):
    repos: CollectionProperty(type=SculptaryRepo)
    repo_index: IntProperty(update=_on_repo_change)
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
        try:
            repos = client().my_repositories()
        except SculptaryError as exc:
            return report_error(self, exc)
        s.repos.clear()
        for r in repos:
            item = s.repos.add()
            item.full_name, item.visibility = r["full_name"], r["visibility"]
        bpy.ops.sculptary.load_assets()
        return {"FINISHED"}


class SCULPTARY_OT_load_assets(Operator):
    bl_idname = "sculptary.load_assets"
    bl_label = "Load models"

    def execute(self, context):
        s = state(context)
        s.assets.clear()
        s.history.clear()
        repo = current_repo(context)
        if not repo:
            return {"FINISHED"}
        try:
            assets = client().assets(repo)
        except SculptaryError as exc:
            if exc.status == 0:
                return report_error(self, exc)
            assets = []
        for a in assets:
            item = s.assets.add()
            item.path, item.status = a["path"], a["status"]
            item.triangles = int((a.get("metadata") or {}).get("triangle_count") or 0)
        return {"FINISHED"}


class SCULPTARY_OT_import(Operator):
    bl_idname = "sculptary.import_model"
    bl_label = "Import"
    bl_description = "Download the selected model and import it into the scene"

    def execute(self, context):
        s = state(context)
        repo = current_repo(context)
        if not repo or not (0 <= s.asset_index < len(s.assets)):
            self.report({"WARNING"}, "Select a model first")
            return {"CANCELLED"}
        path = s.assets[s.asset_index].path
        ext = os.path.splitext(path)[1].lower()
        tmp = os.path.join(tempfile.mkdtemp(prefix="sculptary-"), os.path.basename(path))
        try:
            client().download_file(repo, path, tmp)
        except SculptaryError as exc:
            return report_error(self, exc)
        importers = {
            ".glb": lambda: bpy.ops.import_scene.gltf(filepath=tmp),
            ".gltf": lambda: bpy.ops.import_scene.gltf(filepath=tmp),
            ".obj": lambda: bpy.ops.wm.obj_import(filepath=tmp),
            ".stl": lambda: bpy.ops.wm.stl_import(filepath=tmp),
            ".ply": lambda: bpy.ops.wm.ply_import(filepath=tmp),
        }
        if ext not in importers:
            self.report({"WARNING"}, f"{ext} files cannot be imported yet")
            return {"CANCELLED"}
        importers[ext]()
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
            commits = client().history(repo, s.assets[s.asset_index].path)
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
        s = state(context)
        repo = current_repo(context)
        if not repo:
            self.report({"WARNING"}, "Select or create a repository first")
            return {"CANCELLED"}
        target = s.publish_path.strip().lstrip("/") or "models/scene.glb"
        if not target.lower().endswith(".glb"):
            target += ".glb"
        local = os.path.join(tempfile.mkdtemp(prefix="sculptary-"), os.path.basename(target))
        export_glb(local, s.selected_only)
        try:
            result = client().upload(repo, {target: local}, s.publish_message or "Update model from Blender")
        except SculptaryError as exc:
            return report_error(self, exc)
        self.report({"INFO"}, f"Committed {target} as {result['commit'][:7]}")
        bpy.ops.sculptary.load_assets()
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
        row.label(text=f"{item.triangles:,} tris" if item.status == "ready" else item.status)


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
        col.prop(s, "publish_path")
        col.prop(s, "publish_message")
        col.prop(s, "selected_only")
        col.operator("sculptary.publish", icon="EXPORT")


CLASSES = (
    SculptaryPreferences, SculptaryRepo, SculptaryAsset, SculptaryCommit, SculptaryState,
    SCULPTARY_OT_sign_in, SCULPTARY_OT_refresh, SCULPTARY_OT_load_assets, SCULPTARY_OT_import, SCULPTARY_OT_history,
    SCULPTARY_OT_publish, SCULPTARY_OT_create_repo, SCULPTARY_OT_open_in_browser,
    SCULPTARY_UL_repos, SCULPTARY_UL_assets, SCULPTARY_PT_main, SCULPTARY_PT_models, SCULPTARY_PT_publish,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.sculptary = bpy.props.PointerProperty(type=SculptaryState)


def unregister():
    del bpy.types.WindowManager.sculptary
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

