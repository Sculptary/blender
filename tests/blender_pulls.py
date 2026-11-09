"""Native review controls with an in-memory API fixture and no browser launch."""

import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sculptary_blender as addon  # noqa: E402


class Directory:
    def __init__(self):
        self.calls = []
        self.created = None
        self.denied = False

    def my_repositories(self):
        return [{"full_name": name, "visibility": "private"} for name in ("fixture/shell", "fixture/other")]

    def repository(self, name):
        return {"full_name": name, "default_branch": "main", "is_empty": False}

    def branches(self, name):
        return [{"name": "main", "commit": "a" * 40, "default": True}, {"name": "fit/v2", "commit": "b" * 40, "default": False}]

    def assets(self, name, ref=None):
        return []

    def pull_request(self, name, number):
        return {"number": number, "title": f"Review {number}", "state": "closed" if number == 9 else "open",
            "draft": number == 10, "body": "Review fixture", "comments": [],
            "source": {"repository": "forker/shell", "branch": "fit/v2", "sha": "b" * 40},
            "target": {"repository": name, "branch": "main", "sha": "a" * 40}}

    def pull_requests(self, name, state="open"):
        self.calls.append(("list", name, state))
        if self.denied:
            raise addon.SculptaryError(403, "Fixture access denied")
        numbers = [] if name.endswith("other") else [9] if state == "closed" else [7, 8]
        if self.created and state != "closed" and name.endswith("shell"):
            numbers.insert(0, 10)
        return {"counts": {"open": 101 if numbers else 0, "closed": 1 if numbers else 0, "merged": 0},
            "items": [self.pull_request(name, number) for number in numbers]}

    def create_pull_request(self, name, title, source_branch, **values):
        self.calls.append(("create", name, title, source_branch, values))
        self.created = self.pull_request(name, 10)
        return self.created


directory = Directory()
addon.register()
try:
    preferences = bpy.context.preferences.addons.new()
    preferences.module = addon.ADDON
    preferences.preferences.host = "https://sculptary.fixture/"
    addon.client = lambda: directory
    assert bpy.ops.sculptary.refresh() == {"FINISHED"}
    state = bpy.context.window_manager.sculptary
    assert [pull.number for pull in state.pulls] == [7, 8]
    assert state.pull_total == 101
    assert addon.pulls.current_review(bpy.context)["number"] == 7
    assert json.loads(state.review_json)["source"]["repository"] == "forker/shell"
    opened = []
    addon.pulls.open_url = opened.append
    assert bpy.ops.sculptary.open_pull() == {"FINISHED"}
    assert opened == ["https://sculptary.fixture/fixture/shell/pulls/7"]
    state.pull_filter = "closed"
    assert [pull.number for pull in state.pulls] == [9]
    assert addon.pulls.current_review(bpy.context)["number"] == 9
    assert bpy.ops.sculptary.load_pull(number=99) == {"FINISHED"}
    assert addon.pulls.current_review(bpy.context)["number"] == 99 and state.pull_index == -1
    state.branch_index = 1
    state.pull_title, state.pull_description, state.pull_target, state.pull_draft = "Revise opening", "Check fit", "main", True
    assert bpy.ops.sculptary.create_pull() == {"FINISHED"}
    created = next(call for call in directory.calls if call[0] == "create")
    assert created == ("create", "fixture/shell", "Revise opening", "fit/v2", {"target_branch": "main", "body": "Check fit", "draft": True})
    assert addon.pulls.current_review(bpy.context)["number"] == 10 and state.pull_filter == "open"
    assert state.pull_title == "" and state.pull_description == ""
    assert bpy.ops.sculptary.refresh() == {"FINISHED"}
    assert addon.pulls.current_review(bpy.context)["number"] == 10
    state.repo_index = 1
    assert not state.pulls and addon.pulls.current_review(bpy.context) is None
    state.repo_index = 0
    directory.denied = True
    try:
        bpy.ops.sculptary.load_pulls()
    except RuntimeError:
        pass  # Blender reports an ERROR operator result as an exception in scripts.
    assert not state.pulls and addon.pulls.current_review(bpy.context) is None
    assert state.pull_error == "Fixture access denied"
    directory.denied = False
    assert bpy.ops.sculptary.load_pulls() == {"FINISHED"}
    assert addon.pulls.current_review(bpy.context) is not None
    preferences.preferences.token = "fixture-session-change"
    assert not state.repos and not state.pulls and addon.current_branch(bpy.context) is None
    assert addon.pulls.current_review(bpy.context) is None
    print("BLENDER PULL REQUEST CHECKS PASSED")
finally:
    addon.unregister()
