"""Create, exercise and remove an isolated fixture in the local Compose stack."""

import argparse
import json
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sculptary_blender"))
from api import Client  # noqa: E402


def server(platform, script, data):
    setup = "import os,json,sys; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); import django; django.setup(); p=json.load(sys.stdin); "
    result = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-c", setup + script],
        cwd=platform, input=json.dumps(data), capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError("Local fixture setup or cleanup failed; no credentials were logged.")
    return json.loads(result.stdout) if result.stdout.strip() else None


def cube(width):
    points = [(-width,-1,-1),(width,-1,-1),(width,1,-1),(-width,1,-1),(-width,-1,1),(width,-1,1),(width,1,1),(-width,1,1)]
    faces = [(5,6,7),(5,7,8),(1,3,2),(1,4,3),(1,5,8),(1,8,4),(2,3,7),(2,7,6),(1,2,6),(1,6,5),(4,8,7),(4,7,3)]
    return "o Branch identity fixture\n" + "".join(f"v {x} {y} {z}\n" for x,y,z in points) + "".join(f"f {a} {b} {c}\n" for a,b,c in faces)


def wait_ready(client, repo, ref):
    deadline = time.monotonic() + 120
    while True:
        assets = client.assets(repo, ref=ref)
        assert assets and all(asset["status"] in ("ready", "pending", "processing") for asset in assets), "Fixture processing failed."
        if all(asset["status"] == "ready" for asset in assets):
            return
        assert time.monotonic() < deadline, "Fixture processing timed out."
        time.sleep(0.5)


def run_native(executable, config, log, token):
    timed_out = False
    try:
        result = subprocess.run([str(executable), "--background", "--factory-startup", "--python-exit-code", "1", "--python",
            str(ROOT / "tests/blender_branch_identity_integration.py"), "--", str(config)], capture_output=True, text=True, timeout=180)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, stderr, code, timed_out = exc.stdout, exc.stderr, None, True
    def text(value):
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
    log.parent.mkdir(exist_ok=True)
    log.write_text((text(stdout) + text(stderr)).replace(token, "[redacted]"), encoding="utf-8")
    if timed_out or code != 0:
        state = "timed out" if timed_out else "failed"
        raise RuntimeError(f"Native integration {state}. See {log}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", type=Path, default=ROOT.parent / "platform")
    parser.add_argument("--blender", default=shutil.which("blender"), required=shutil.which("blender") is None)
    parser.add_argument("--host", default="http://127.0.0.1:18080")
    args = parser.parse_args()
    if urlsplit(args.host).hostname not in ("localhost", "127.0.0.1", "::1"):
        parser.error("Use the local verification stack.")
    name = "branchqa-" + secrets.token_hex(5)
    fixture = server(args.platform, "from accounts.services import register_user; from accounts.models import PersonalAccessToken; import secrets; "
        "u=register_user(p['name'],p['name']+'@example.invalid',secrets.token_urlsafe(32)); "
        "_,token=PersonalAccessToken.issue(u,'Native branch identity check',['repo:write','user']); "
        "print(json.dumps({'id':str(u.pk),'namespace':str(u.namespace_id),'token':token}))", {"name": name})
    client = Client(args.host, fixture["token"])
    repo = name + "/branch-identity"
    try:
        client.create_repository("branch-identity", True, "Disposable native branch/tag identity verification")
        with tempfile.TemporaryDirectory(prefix="sculptary-branch-live-") as folder:
            folder = Path(folder)
            source = folder / "model.obj"
            source.write_text(cube(1))
            base = client.upload(repo, {"models/shared.obj": str(source), "models/main-only.obj": str(source)}, "Add branch identity fixture", "main")["commit"]
            client.create_branch(repo, "fit/v2", base)
            source.write_text(cube(1.25))
            head = client.upload(repo, {"models/shared.obj": str(source), "models/head-only.obj": str(source)}, "Revise branch identity fixture", "fit/v2")["commit"]
            for tag, target in (("main", head), ("fit/v2", base)):
                client.post_json(f"/repos/{repo}/releases", {"tag_name": tag, "target": target, "name": "Branch collision fixture"})
            for ref in ("refs/heads/main", "refs/heads/fit/v2"):
                wait_ready(client, repo, ref)
            config = folder / "fixture.json"
            config.write_text(json.dumps({"host": args.host, "token": fixture["token"], "repository": repo, "base_commit": base, "head_commit": head}))
            config.chmod(0o600)
            run_native(args.blender, config, args.platform / ".local/blender-branch-identity.log", fixture["token"])
            wait_ready(client, repo, "refs/heads/from-selected")
            print("Live branch/tag listing, import, history, comparisons, branch creation and publishing passed.")
    finally:
        server(args.platform, "import re; from accounts.models import User,Namespace; from repositories.models import Repository; from repositories.services import delete_repository; "
            "assert re.fullmatch(r'branchqa-[a-f0-9]{10}',p['name']); u=User.objects.get(pk=p['id']); assert u.username==p['name']; "
            "r=Repository.objects.filter(owner=u.namespace,name='branch-identity').first(); "
            "delete_repository(r,u) if r else None; assert not Repository.objects.filter(owner=u.namespace).exists(); u.delete(); "
            "ns=Namespace.objects.get(pk=p['namespace']); assert ns.slug==p['name']; ns.delete()",
            {"id": fixture["id"], "namespace": fixture["namespace"], "name": name})
        print("Disposable fixture removed; audit records retained.")


if __name__ == "__main__":
    main()
