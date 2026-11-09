import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, parse, request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sculptary_blender"))
import api  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener(handler):
    calls = []

    def _open(req, timeout=None):
        calls.append(req)
        return handler(req)

    return _open, calls


def test_requests_carry_token_and_query():
    _open, calls = opener(lambda req: FakeResponse(json.dumps({"username": "n"}).encode()))
    c = api.Client("https://x.test/", "sdb_pat_t", opener=_open)
    assert c.me()["username"] == "n"
    assert calls[0].full_url == "https://x.test/api/v1/user"
    assert calls[0].get_header("Authorization") == "Bearer sdb_pat_t"
    c.get("/repos/a/b/commits", ref=None, path="m.glb")
    assert calls[1].full_url.endswith("/commits?path=m.glb")


def test_http_errors_become_sculptary_errors():
    def fail(req):
        raise error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":{"message":"Repository not found."}}'))

    _open, _ = opener(fail)
    try:
        api.Client("https://x.test", opener=_open).repository("a/b")
    except api.SculptaryError as e:
        assert e.status == 404 and e.message == "Repository not found."
    else:
        raise AssertionError("expected error")


def test_asset_lookup_and_standard_preview_download_use_immutable_asset_routes(tmp_path):
    def respond(req):
        if "/preview?" in req.full_url:
            return FakeResponse(b"glTF-preview")
        return FakeResponse(b'{"id":"asset-id","commit":"immutable-sha","standard_preview_url":"/preview?encoding=standard"}')

    _open, calls = opener(respond)
    client = api.Client("https://x.test", opener=_open)
    assert client.asset_at("artist/model", "models/a b.glb", "feature/fit")["commit"] == "immutable-sha"
    destination = tmp_path / "preview.glb"
    assert client.download_preview("artist/model", "asset-id", str(destination)) == 12
    assert destination.read_bytes() == b"glTF-preview"
    assert parse.parse_qs(parse.urlsplit(calls[0].full_url).query) == {"path": ["models/a b.glb"], "ref": ["feature/fit"]}
    assert calls[1].full_url.endswith("/assets/asset-id/preview?encoding=standard")


def test_preview_preparation_errors_remain_actionable_and_do_not_write_a_file(tmp_path):
    def fail(req):
        raise error.HTTPError(req.full_url, 409, "Conflict", {}, io.BytesIO(
            b'{"error":{"message":"Standard preview is being prepared. Retry shortly."}}'))

    _open, _ = opener(fail)
    destination = tmp_path / "preview.glb"
    with pytest.raises(api.SculptaryError, match="being prepared") as caught:
        api.Client("https://x.test", opener=_open).download("/preview", str(destination))
    assert caught.value.status == 409 and not destination.exists()


def test_invalid_api_json_becomes_an_actionable_client_error():
    _open, _ = opener(lambda req: FakeResponse(b"<html>Upstream unavailable</html>"))
    with pytest.raises(api.SculptaryError, match="valid JSON") as caught:
        api.Client("https://x.test", opener=_open).me()
    assert caught.value.status == 502


def test_redirects_keep_credentials_only_on_the_same_origin(tmp_path):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            seen.append((self.server.server_port, self.path, self.headers.get("Authorization")))
            if self.path.endswith("/preview?encoding=standard"):
                self.send_response(302)
                self.send_header("Location", "/same-origin")
            elif self.path == "/same-origin":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{storage.server_port}/signed-object")
            else:
                self.send_response(200)
            self.end_headers()
            if self.path == "/signed-object":
                self.wfile.write(b"glTF-preview")

    storage = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (storage, service)]
    for thread in threads:
        thread.start()
    try:
        client = api.Client(f"http://127.0.0.1:{service.server_port}", "test-review-credential")
        client.download("/preview", str(tmp_path / "preview.glb"), encoding="standard")
        assert [entry[2] for entry in seen] == ["Bearer test-review-credential", "Bearer test-review-credential", None]
        assert (tmp_path / "preview.glb").read_bytes() == b"glTF-preview"
    finally:
        for server in (service, storage):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=2)


@pytest.mark.parametrize("destination,authorized", [
    ("https://x.test/next", True), ("https://X.test:443/next", True),
    ("http://x.test/next", False), ("https://storage.test/object", False),
    ("https://x.test:444/object", False),
])
def test_redirect_origin_includes_scheme_host_and_port(destination, authorized):
    original = request.Request("https://x.test/api/v1/user", headers={"Authorization": "Bearer test-review-credential"})
    redirected = api.CredentialRedirectHandler().redirect_request(original, None, 302, "Found", {}, destination)
    assert bool(redirected.get_header("Authorization")) is authorized


def test_multipart_includes_paths_and_files(tmp_path):
    f = tmp_path / "cube.glb"
    f.write_bytes(b"glTF-bytes")
    body, ctype = api.encode_multipart({"branch": "main", "message": "m"}, {"models/cube.glb": str(f)})
    boundary = ctype.split("boundary=")[1]
    assert body.endswith(f"--{boundary}--\r\n".encode())
    assert b'name="paths"\r\n\r\nmodels/cube.glb' in body
    assert b'filename="cube.glb"' in body and b"glTF-bytes" in body


def test_pull_request_discovery_uses_the_server_list_detail_and_changes_contracts():
    def respond(req):
        path = parse.urlsplit(req.full_url).path
        if path.endswith("/changes"):
            result = {"base": "a" * 40, "head": "b" * 40, "changes": [{"path": "models/new.glb", "old_path": "models/old.glb", "status": "renamed"}], "commits": []}
        elif path.endswith("/pulls/7"):
            result = {"number": 7, "title": "Revise shell", "source": {"repository": "artist/model", "branch": "fit/v2", "sha": "b" * 40}, "comments": []}
        else:
            result = {"counts": {"open": 1, "closed": 0, "merged": 0}, "items": [{"number": 7, "title": "Revise shell"}]}
        return FakeResponse(json.dumps(result).encode())
    _open, calls = opener(respond)
    client = api.Client("https://x.test", opener=_open)
    assert client.pull_requests("artist/model", state="all")["counts"]["open"] == 1
    assert client.pull_request("artist/model", 7)["source"]["branch"] == "fit/v2"
    assert client.pull_changes("artist/model", 7)["changes"][0]["old_path"] == "models/old.glb"
    assert calls[0].full_url.endswith("/pulls?state=all")
    assert calls[1].full_url.endswith("/pulls/7") and calls[2].full_url.endswith("/pulls/7/changes")


def test_create_pull_request_preserves_refs_and_optional_source_repository():
    _open, calls = opener(lambda req: FakeResponse(b'{"number":8,"draft":true}'))
    client = api.Client("https://x.test", opener=_open)
    result = client.create_pull_request("team/model", "Revise shell", "fit/v2", target_branch="main",
        body="Check the opening.", draft=True, source_repository="artist/model")
    assert result == {"number": 8, "draft": True}
    assert calls[0].method == "POST" and calls[0].full_url.endswith("/repos/team/model/pulls")
    assert json.loads(calls[0].data) == {"title": "Revise shell", "source_branch": "fit/v2", "target_branch": "main",
        "body": "Check the opening.", "draft": True, "source_repository": "artist/model"}


def test_cursor_comment_is_a_real_spatial_comment_and_replies_use_parent_ids():
    _open, calls = opener(lambda req: FakeResponse(b'{"id":"comment-id"}'))
    client = api.Client("https://x.test", opener=_open)
    anchor = {"point": [1, 3, -2], "normal": None, "object": "Shell", "camera": None}
    client.comment_pull_request("artist/model", 7, "Check this point", path="models/shell.glb", commit_sha="b" * 40, spatial_anchor=anchor)
    assert json.loads(calls[0].data) == {"body": "Check this point", "path": "models/shell.glb", "commit_sha": "b" * 40, "spatial_anchor": anchor}
    client.comment_pull_request("artist/model", 7, "Fixed", parent_id="comment-id")
    assert json.loads(calls[1].data) == {"body": "Fixed", "parent_id": "comment-id"}
    assert all(req.full_url.endswith("/pulls/7/comments") and req.method == "POST" for req in calls)


@pytest.mark.parametrize("resolved,action", [(True, "resolve"), (False, "unresolve")])
def test_comment_resolution_uses_the_comment_resource(resolved, action):
    _open, calls = opener(lambda req: FakeResponse(b'{"id":"comment-id"}'))
    api.Client("https://x.test", opener=_open).resolve_comment("artist/model", "comment-id", resolved=resolved)
    assert calls[0].full_url.endswith("/repos/artist/model/comments/comment-id/" + action)
    assert calls[0].method == "POST" and json.loads(calls[0].data) == {}


def test_branch_creation_and_ref_queries_preserve_slashes_and_unicode():
    _open, calls = opener(lambda req: FakeResponse(b'{"assets":[]}'))
    client = api.Client("https://x.test", opener=_open)
    client.create_branch("artist/model", "fit/épreuve", "main")
    assert json.loads(calls[0].data) == {"name": "fit/épreuve", "from_ref": "main"}
    client.assets("artist/model", "fit/épreuve")
    assert parse.parse_qs(parse.urlsplit(calls[1].full_url).query) == {"ref": ["fit/épreuve"]}


def test_publishing_does_not_recreate_a_selected_branch_that_was_deleted():
    def respond(req):
        result = [{"name": "main", "commit": "a" * 40}] if req.full_url.endswith("/branches") else {"default_branch": "main", "is_empty": False}
        return FakeResponse(json.dumps(result).encode())
    _open, calls = opener(respond)
    with pytest.raises(api.SculptaryError, match="branch no longer exists"):
        api.Client("https://x.test", opener=_open).upload("artist/model", {"models/shell.glb": "not-read.glb"}, "Update shell", branch="deleted/topic")
    assert all(call.method == "GET" for call in calls)


def test_publishing_uses_the_selected_branch_head_for_the_expected_head_check(tmp_path):
    model = tmp_path / "model.glb"
    model.write_bytes(b"glTF-fixture")
    def respond(req):
        if req.method == "POST":
            return FakeResponse(b'{"commit":"new-head"}')
        result = [{"name": "main", "commit": "a" * 40}, {"name": "fit/v2", "commit": "b" * 40}] if req.full_url.endswith("/branches") else {"default_branch": "main", "is_empty": False}
        return FakeResponse(json.dumps(result).encode())
    _open, calls = opener(respond)
    api.Client("https://x.test", opener=_open).upload("artist/model", {"models/shell.glb": str(model)}, "Update shell", branch="fit/v2")
    assert b'name="branch"\r\n\r\nfit/v2\r\n' in calls[-1].data
    assert b'name="expected_head"\r\n\r\n' + b"b" * 40 + b"\r\n" in calls[-1].data
