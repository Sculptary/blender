"""Native PR comparison and cursor pins, including forks and renamed models."""

import json
import sys
import tempfile
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sculptary_blender as addon


class Directory:
    def __init__(self, source):
        self.source, self.calls, self.comments = source, [], []
        self.head, self.denied = "b" * 40, False

    def my_repositories(self):
        return [{"full_name": "fixture/shell", "visibility": "private"}]

    def repository(self, name):
        return {"full_name": name, "default_branch": "main", "is_empty": False}

    def branches(self, name):
        return [{"name": "main", "commit": "a" * 40}]

    def assets(self, name, ref=None):
        return []

    def pull_requests(self, name, state="open"):
        return {"counts": {"open": 1, "closed": 0, "merged": 0}, "items": [self.pull_request(name, 7)]}

    def pull_request(self, name, number):
        return {"number": number, "title": "Review shell", "state": "open", "draft": False,
            "source": {"repository": "forker/shell", "branch": "fit/v2", "sha": self.head},
            "target": {"repository": name, "branch": "main", "sha": "d" * 40}, "comments": self.comments}

    def pull_changes(self, name, number):
        return {"base": "a" * 40, "head": self.head, "changes": [
            {"path": "models/new.glb", "old_path": "models/old.glb", "status": "R", "model_format": "glb"},
            {"path": "models/added.glb", "status": "A", "model_format": "glb"},
            {"path": "models/removed.glb", "status": "D", "model_format": "glb"},
            {"path": "README.md", "status": "M", "model_format": None}]}

    def asset_at(self, name, path, ref):
        self.calls.append(("asset", name, path, ref))
        return {"id": ref[0], "commit": ref, "path": path, "status": "ready", "standard_preview_url": "/preview?encoding=standard"}

    def download_preview(self, name, asset_id, destination):
        Path(destination).write_bytes(self.source.read_bytes())

    def comment_pull_request(self, name, number, body, **payload):
        if self.denied:
            raise addon.SculptaryError(403, "Fixture cannot comment")
        self.calls.append(("comment", name, number, body, payload))
        comment = {"id": "fixture-comment", "body": body, "author": {"username": "reviewer"},
            "resolved_at": None, "replies": [], **payload}
        self.comments.append(comment)
        return comment


def expect_failure(operator):
    try:
        assert operator() == {"CANCELLED"}
    except RuntimeError:
        pass


def root(side):
    return addon.comparison.roots(bpy.context.scene)[side]


addon.register()
try:
    prefs = bpy.context.preferences.addons.new()
    prefs.module = addon.ADDON
    prefs.preferences.host = "https://sculptary.fixture"
    with tempfile.TemporaryDirectory(prefix="sculptary-review-fixture-") as folder:
        source = Path(folder) / "source.glb"
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.scene.objects["Cube"].select_set(True)
        bpy.ops.export_scene.gltf(filepath=str(source), export_format="GLB", use_selection=True)
        directory = Directory(source)
        addon.client = lambda: directory
        assert bpy.ops.sculptary.refresh() == {"FINISHED"}
        s = addon.state(bpy.context)
        assert bpy.ops.sculptary.load_pull_models() == {"FINISHED"}
        assert [item.path for item in s.review_models] == ["models/new.glb", "models/added.glb", "models/removed.glb"]
        assert bpy.ops.sculptary.compare_pull_model() == {"FINISHED"}
        info = addon.comparison.review_info(bpy.context.scene)
        assert info["pull_number"] == 7
        assert info["base"]["path"] == "models/old.glb" and info["head"]["path"] == "models/new.glb"
        assert ("asset", "fixture/shell", "models/old.glb", "a" * 40) in directory.calls
        assert ("asset", "forker/shell", "models/new.glb", "b" * 40) in directory.calls
        scene = bpy.context.scene
        scene.sculptary_pin_body = "Check the opening"
        scene.sculptary_pin_side = "head"
        scene.cursor.location = root("head").matrix_world @ Vector((1, 2, 3))
        assert bpy.ops.sculptary.pin_cursor() == {"FINISHED"}
        posted = next(call for call in directory.calls if call[0] == "comment")
        assert posted[:4] == ("comment", "fixture/shell", 7, "Check the opening")
        assert posted[4] == {"path": "models/new.glb", "commit_sha": "b" * 40,
            "spatial_anchor": {"point": [1., 3., -2.], "normal": None, "object": "models/new.glb", "camera": None, "animation": {"rest": True}}}
        assert scene.sculptary_pin_body == ""
        assert len(json.loads(s.review_json)["comments"]) == 1
        scene.sculptary_pin_body = "Check the base"
        scene.sculptary_pin_side = "base"
        scene.cursor.location = root("base").matrix_world @ Vector((1, 2, 3))
        assert bpy.ops.sculptary.pin_cursor() == {"FINISHED"}
        assert directory.calls[-1][4]["path"] == "models/old.glb"
        assert directory.calls[-1][4]["commit_sha"] == "a" * 40
        scene.sculptary_pin_body = "Keep my draft"
        directory.head = "c" * 40
        expect_failure(bpy.ops.sculptary.pin_cursor)
        assert scene.sculptary_pin_body == "Keep my draft"
        assert len([call for call in directory.calls if call[0] == "comment"]) == 2
        directory.head = "b" * 40
        directory.denied = True
        expect_failure(bpy.ops.sculptary.pin_cursor)
        assert scene.sculptary_pin_body == "Keep my draft" and not s.review_json
        directory.denied = False
        assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
        assert bpy.ops.sculptary.load_pull(number=7) == {"FINISHED"}
        assert bpy.ops.sculptary.load_pull_models() == {"FINISHED"}
        for index, absent in ((1, "base"), (2, "head")):
            s.review_model_index = index
            assert bpy.ops.sculptary.compare_pull_model() == {"FINISHED"}
            assert addon.comparison.review_info(bpy.context.scene)[absent] is None
            bpy.context.scene.sculptary_pin_side = absent
            bpy.context.scene.sculptary_pin_body = "Cannot pin absent geometry"
            expect_failure(bpy.ops.sculptary.pin_cursor)
            assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
        print("BLENDER REVIEW CHECKS PASSED")
finally:
    addon.unregister()
