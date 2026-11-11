"""Opt-in native branch check. The runner owns its private config and fixtures."""

import json
import math
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sculptary_blender as addon

config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
repo = config["repository"]
assert re.fullmatch(r"branchqa-[a-f0-9]{10}/branch-identity", repo), "Use a disposable branch-identity fixture."
assert urlsplit(config["host"]).hostname in ("localhost", "127.0.0.1", "::1"), "Use the local verification stack."
base, head = config["base_commit"], config["head_commit"]
addon.register()
try:
    prefs = bpy.context.preferences.addons.new()
    prefs.module = addon.ADDON
    prefs.preferences.host, prefs.preferences.token = config["host"], config["token"]
    assert bpy.ops.sculptary.sign_in() == {"FINISHED"}
    s = addon.state(bpy.context)
    s.repo_index = next(index for index, item in enumerate(s.repos) if item.full_name == repo)
    assert addon.current_branch(bpy.context) == "main"
    assert sorted(asset.path for asset in s.assets) == ["models/main-only.obj", "models/shared.obj"]
    s.asset_index = next(index for index, asset in enumerate(s.assets) if asset.path == "models/shared.obj")
    assert bpy.ops.sculptary.history() == {"FINISHED"}
    assert s.history[0].sha == base[:7] and s.history[0].message == "Add branch identity fixture"

    s.branch_index = next(index for index, branch in enumerate(s.branches) if branch.name == "fit/v2")
    assert sorted(asset.path for asset in s.assets) == ["models/head-only.obj", "models/main-only.obj", "models/shared.obj"]
    s.asset_index = next(index for index, asset in enumerate(s.assets) if asset.path == "models/shared.obj")
    assert bpy.ops.sculptary.history() == {"FINISHED"}
    assert s.history[0].sha == head[:7] and s.history[0].message == "Revise branch identity fixture"
    before = set(bpy.data.objects)
    assert bpy.ops.sculptary.import_model() == {"FINISHED"}
    imported = [obj for obj in set(bpy.data.objects) - before if obj.type == "MESH"]
    coordinates = [(obj.matrix_world @ Vector(corner)).x for obj in imported for corner in obj.bound_box]
    assert coordinates and math.isclose(max(coordinates) - min(coordinates), 2.5, abs_tol=1e-5), "Imported the tag's geometry."

    working = bpy.context.scene
    for base_ref, head_ref in (("main", ""), ("refs/tags/fit/v2", "refs/tags/main")):
        s.compare_base, s.compare_head, s.compare_path = base_ref, head_ref, "models/shared.obj"
        assert bpy.ops.sculptary.compare_models() == {"FINISHED"}
        info = addon.comparison.review_info(bpy.context.scene)
        assert info["base"]["commit"] == base and info["head"]["commit"] == head
        assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
        assert bpy.context.scene == working

    s.new_branch_name = "from-selected"
    assert bpy.ops.sculptary.create_branch() == {"FINISHED"}
    client = addon.client()
    assert next(branch["commit"] for branch in client.branches(repo) if branch["name"] == "from-selected") == head
    assert addon.current_branch(bpy.context) == "from-selected"
    s.publish_path, s.publish_message = "models/published.glb", "Publish branch identity fixture"
    assert bpy.ops.sculptary.publish() == {"FINISHED"}
    history = client.history(repo, "models/published.glb", ref="refs/heads/from-selected")
    assert history[0]["message"].strip() == "Publish branch identity fixture"
    assert history[0]["oid"] not in (base, head)
    assert client.asset_at(repo, "models/shared.obj", "refs/tags/main")["commit"] == head
    assert client.asset_at(repo, "models/shared.obj", "refs/tags/fit/v2")["commit"] == base
    branches = {branch["name"]: branch["commit"] for branch in client.branches(repo)}
    assert branches["main"] == base and branches["fit/v2"] == head
    print("LIVE BLENDER BRANCH IDENTITY CHECKS PASSED")
finally:
    addon.unregister()
