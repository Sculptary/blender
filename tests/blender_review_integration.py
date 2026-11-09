"""Opt-in live review test. Pass a temporary JSON config path, never a token argument.

Config: host, token, repository, pull, path, base_commit, head_commit, optional render.
The caller owns creation and cleanup of its disposable repository and account.
"""

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sculptary_blender as addon

config = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text())
addon.register()
try:
    prefs = bpy.context.preferences.addons.new()
    prefs.module = addon.ADDON
    prefs.preferences.host, prefs.preferences.token = config["host"], config["token"]
    assert bpy.ops.sculptary.sign_in() == {"FINISHED"}
    s = addon.state(bpy.context)
    s.repo_index = next(i for i, repo in enumerate(s.repos) if repo.full_name == config["repository"])
    assert bpy.ops.sculptary.load_pull(number=config["pull"]) == {"FINISHED"}
    assert bpy.ops.sculptary.load_pull_models() == {"FINISHED"}
    s.review_model_index = next(i for i, item in enumerate(s.review_models) if item.path == config["path"])
    working = bpy.context.scene
    before = set(working.objects)
    assert bpy.ops.sculptary.compare_pull_model() == {"FINISHED"}
    scene = bpy.context.scene
    info = addon.comparison.review_info(scene)
    assert info["base"]["commit"] == config["base_commit"]
    assert info["head"]["commit"] == config["head_commit"]
    assert len(scene.collection.children) == 2
    root = addon.comparison.roots(scene)["head"]
    scene.cursor.location = root.matrix_world @ Vector((0, 0, 1.4))
    scene.sculptary_pin_body = "Native cursor integration fixture."
    assert bpy.ops.sculptary.pin_cursor() == {"FINISHED"}
    posted = next(comment for comment in addon.client().pull_request(config["repository"], config["pull"])["comments"]
        if comment["id"] == scene["sculptary_last_pin"])
    assert posted["path"] == config["path"] and posted["commit_sha"] == config["head_commit"]
    assert all(math.isclose(actual, expected, abs_tol=1e-5) for actual, expected in zip(posted["spatial_anchor"]["point"], [0, 1.4, 0]))
    assert posted["spatial_anchor"]["animation"] == {"rest": True}
    assert scene.sculptary_pin_body == ""
    if config.get("render"):
        snapshot = addon.comparison._snapshot()
        world = bpy.data.worlds.new("Review QA world")
        world.use_nodes = True
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.08, 0.09, 0.11, 1)
        world.node_tree.nodes["Background"].inputs[1].default_value = 0.7
        scene.world = world
        camera = bpy.data.cameras.new("Review QA camera")
        camera_object = bpy.data.objects.new("Review QA camera", camera)
        scene.collection.objects.link(camera_object)
        target = Vector((0, 0, 0.15))
        direction = Vector(scene["sculptary_review_direction"])
        camera_object.location = target + Vector((direction.y * 10, -direction.x * 10, 7))
        camera_object.rotation_euler = (target - camera_object.location).to_track_quat("-Z", "Y").to_euler()
        camera.type, camera.ortho_scale = "ORTHO", 1
        scene.camera = camera_object
        for name, location, power, size in (("Key", (-3, -4, 7), 700, 5), ("Fill", (4, 1, 5), 450, 4)):
            light = bpy.data.lights.new(name, "AREA")
            light.energy, light.shape, light.size = power, "DISK", size
            obj = bpy.data.objects.new(name, light)
            scene.collection.objects.link(obj)
            obj.location = location
            obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()
        addon.comparison._tag_new(snapshot, scene[addon.comparison.OWNER])
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 960, 640, 100
        bpy.context.view_layer.update()
        inverse = camera_object.matrix_world.inverted()
        points = [inverse @ obj.matrix_world @ Vector(corner) for obj in scene.objects if obj.type == "MESH" for corner in obj.bound_box]
        frame = camera.view_frame(scene=scene)
        camera.ortho_scale = max((max(p.x for p in points) - min(p.x for p in points)) / (max(p.x for p in frame) - min(p.x for p in frame)),
            (max(p.y for p in points) - min(p.y for p in points)) / (max(p.y for p in frame) - min(p.y for p in frame))) * 1.2
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 16
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 960, 640, 100
        scene.render.filepath = config["render"]
        bpy.ops.render.render(write_still=True)
    assert bpy.ops.sculptary.close_comparison() == {"FINISHED"}
    assert bpy.context.scene == working and set(working.objects) == before
    print("LIVE BLENDER REVIEW CHECKS PASSED")
finally:
    addon.unregister()
