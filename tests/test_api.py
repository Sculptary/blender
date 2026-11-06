import io
import json
import sys
from pathlib import Path
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shapesdb_blender"))
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


def test_http_errors_become_shapesdb_errors():
    def fail(req):
        raise error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b'{"error":{"message":"Repository not found."}}'))

    _open, _ = opener(fail)
    try:
        api.Client("https://x.test", opener=_open).repository("a/b")
    except api.ShapesDBError as e:
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
