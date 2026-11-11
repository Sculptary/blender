"""Run with Blender --background --factory-startup --python-exit-code 1 --python this-file.

Uses an in-memory API fixture and real Blender import/export operators. No server,
credentials, user preferences or existing scenes are changed.
"""

import sys
import tempfile
from pathlib import Path

import addon_utils
import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sculptary_blender as addon  # noqa: E402


class Directory:
    def __init__(self, model):
        self.model = model
        self.calls = []
        self.order = ["fixture/shell", "fixture/empty"]
        self.refs = {"fixture/shell": [{"name": "main", "commit": "a" * 40, "default": True, "protected": False},
            {"name": "fit/v2", "commit": "b" * 40, "default": False, "protected": False}], "fixture/empty": []}

    def my_repositories(self):
        return [{"full_name": name, "visibility": "private"} for name in self.order]

    def repository(self, name):
        return {"full_name": name, "default_branch": "main", "is_empty": not self.refs[name]}

    def branches(self, name):
        return self.refs[name]

    def assets(self, name, ref=None):
        self.calls.append(("assets", name, ref))
        # A same-named tag resolves differently through Git's short-name lookup.
        path = "models/shell.glb" if ref and ref.startswith("refs/heads/") else "models/tag-only.glb"
        return [{"path": path, "status": "ready", "metadata": {"triangle_count": 12}}] if self.refs[name] else []

    def pull_requests(self, name, state="open"):
        return {"counts": {"open": 0, "closed": 0, "merged": 0}, "items": []}

    def history(self, name, path, ref=None):
        self.calls.append(("history", name, ref))
        return [{"oid": "b" * 40, "message": "Adjust shell", "author": {"name": "Fixture"}, "committer": {"date": "2026-11-09"}}]

    def download_file(self, name, path, dest, ref=None):
        self.calls.append(("download", name, ref, dest))
        Path(dest).write_bytes(self.model.read_bytes())

    def upload(self, name, files, message, branch=None):
        assert all(Path(path).read_bytes().startswith(b"glTF") for path in files.values())
        self.calls.append(("upload", name, branch, list(files.values())))
        if not self.refs[name]:
            self.refs[name].append({"name": branch, "commit": "c" * 40, "default": True, "protected": False})
        return {"commit": "c" * 40}

    def create_branch(self, name, branch, from_ref):
        self.calls.append(("create_branch", name, branch, from_ref))
        item = {"name": branch, "commit": "b" * 40, "default": False, "protected": False}
        self.refs[name].append(item)
        return item


addon_utils.enable("io_scene_gltf2", default_set=False)
addon.register()
try:
    with tempfile.TemporaryDirectory(prefix="sculptary-branch-fixture-") as folder:
        model = Path(folder) / "source.glb"
        bpy.ops.export_scene.gltf(filepath=str(model), export_format="GLB")
        directory = Directory(model)
        addon.client = lambda: directory
        assert bpy.ops.sculptary.refresh() == {"FINISHED"}
        state = bpy.context.window_manager.sculptary
        assert [branch.name for branch in state.branches] == ["main", "fit/v2"]
        assert addon.current_branch(bpy.context) == "main"
        assert state.compare_base == "refs/heads/main"
        assert [asset.path for asset in state.assets] == ["models/shell.glb"], "The default branch opened the same-named tag."
        state.branch_index = 1
        assert addon.current_branch(bpy.context) == "fit/v2"
        assert directory.calls[-1] == ("assets", "fixture/shell", "refs/heads/fit/v2")
        assert [asset.path for asset in state.assets] == ["models/shell.glb"]
        assert bpy.ops.sculptary.history() == {"FINISHED"}
        assert directory.calls[-1] == ("history", "fixture/shell", "refs/heads/fit/v2")
        state.loaded_repo = "fixture/other"
        previous_calls = len(directory.calls)
        assert bpy.ops.sculptary.history() == {"CANCELLED"}
        assert len(directory.calls) == previous_calls, "A stale branch selection fell back to default-branch history."
        state.loaded_repo = "fixture/shell"
        objects = len(bpy.data.objects)
        assert bpy.ops.sculptary.import_model() == {"FINISHED"}
        downloaded = directory.calls[-1]
        assert downloaded[:3] == ("download", "fixture/shell", "refs/heads/fit/v2")
        assert not Path(downloaded[3]).exists(), "Import left its temporary download behind."
        assert len(bpy.data.objects) > objects
        assert bpy.ops.sculptary.publish() == {"FINISHED"}
        uploaded = next(call for call in reversed(directory.calls) if call[0] == "upload")
        assert uploaded[:3] == ("upload", "fixture/shell", "fit/v2")
        assert all(not Path(path).exists() for path in uploaded[3]), "Publish left its temporary export behind."
        state.new_branch_name = "review/dimensions"
        assert bpy.ops.sculptary.create_branch() == {"FINISHED"}
        assert ("create_branch", "fixture/shell", "review/dimensions", "refs/heads/fit/v2") in directory.calls
        assert addon.current_branch(bpy.context) == "review/dimensions"
        for name in ("refs/tags/v1", "d" * 40):
            directory.refs["fixture/shell"].append({"name": name, "commit": "b" * 40})
            assert bpy.ops.sculptary.load_repository(select_branch=name) == {"FINISHED"}
            assert addon.current_branch(bpy.context) == name
            assert addon.current_branch_ref(bpy.context) == "refs/heads/" + name
            assert ("assets", "fixture/shell", "refs/heads/" + name) in directory.calls
            assert bpy.ops.sculptary.history() == {"FINISHED"}
            assert directory.calls[-1] == ("history", "fixture/shell", "refs/heads/" + name)
        assert bpy.ops.sculptary.load_repository(select_branch="review/dimensions") == {"FINISHED"}
        directory.order.reverse()
        assert bpy.ops.sculptary.refresh() == {"FINISHED"}
        assert addon.current_repo(bpy.context) == "fixture/shell" and addon.current_branch(bpy.context) == "review/dimensions"
        state.repo_index = 0
        assert addon.current_repo(bpy.context) == "fixture/empty" and not state.branches
        assert addon.current_branch(bpy.context) == "main" and not state.assets and not state.history
        assert bpy.ops.sculptary.publish() == {"FINISHED"}
        assert state.branches and addon.current_branch(bpy.context) == "main"
        state.repo_index = 1
        assert addon.current_branch(bpy.context) == "main", "Switching repositories retained an unrelated branch."
        print("BLENDER BRANCH CHECKS PASSED")
finally:
    addon.unregister()
