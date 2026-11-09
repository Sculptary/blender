import io
import json
import sys
from pathlib import Path
from urllib import error, parse

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
