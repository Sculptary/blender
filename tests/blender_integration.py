"""Run inside Blender against a live Sculptary server:

    blender -b --factory-startup --python tests/blender_integration.py -- <host> <token> <addon-dir>

Exercises sign-in, repository listing, model import, history and publishing.
"""

import sys
import time

import addon_utils
import bpy

host, token, addon_dir = sys.argv[sys.argv.index("--") + 1:][:3]
sys.path.insert(0, addon_dir)
bpy.utils.refresh_script_paths()
import sculptary_blender  # noqa: E402

sculptary_blender.register()
bpy.context.preferences.addons.new().module = "sculptary_blender"
p = bpy.context.preferences.addons["sculptary_blender"].preferences
p.host, p.token = host, token

assert bpy.ops.sculptary.sign_in() == {"FINISHED"}, "sign in failed"
print("signed in as", p.username)
s = bpy.context.window_manager.sculptary
names = [r.full_name for r in s.repos]
print("repos:", names)
s.repo_index = names.index("northwind/medieval-castle")
assert any(a.path == "models/castle.glb" for a in s.assets), [a.path for a in s.assets]
s.asset_index = [a.path for a in s.assets].index("models/castle.glb")

before = len(bpy.data.objects)
assert bpy.ops.sculptary.import_model() == {"FINISHED"}
print("imported objects:", len(bpy.data.objects) - before)
assert len(bpy.data.objects) - before >= 40

assert bpy.ops.sculptary.history() == {"FINISHED"}
print("history:", [(c.sha, c.message) for c in s.history])
assert s.history and s.history[0].message == "Raise towers and add the central keep"

# Publish: new repository, scene with a cube.
s.new_repo_name = f"blender-check-{int(time.time())}"
s.new_repo_private = True
assert bpy.ops.sculptary.create_repo() == {"FINISHED"}
assert s.repos[s.repo_index].full_name.endswith(s.new_repo_name or "")  # name cleared after creation
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
bpy.ops.mesh.primitive_cube_add(size=2)
s.publish_path = "models/cube.glb"
s.publish_message = "Publish cube from Blender"
assert bpy.ops.sculptary.publish() == {"FINISHED"}
repo = s.repos[s.repo_index].full_name
c = sculptary_blender.client()
for _ in range(60):
    a = next((x for x in c.assets(repo) if x["path"] == "models/cube.glb"), None)
    if a and a["status"] in ("ready", "failed"):
        break
    time.sleep(1)
print("published asset:", a["status"], a["metadata"].get("triangle_count"))
assert a["status"] == "ready" and a["metadata"]["triangle_count"] == 12
c._send(c._req("DELETE", f"/repos/{repo}"))
print("BLENDER INTEGRATION OK")
