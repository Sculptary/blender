"""Sculptary API client using only the Python standard library (Blender ships no extras).

Kept free of `bpy` so it can be tested outside Blender.
"""

from __future__ import annotations

import json
import mimetypes
import uuid
from typing import Any
from urllib import error, parse, request

USER_AGENT = "sculptary-blender/0.2.1"


class SculptaryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _origin(url: str) -> tuple:
    parts = parse.urlsplit(url)
    return parts.scheme.lower(), parts.hostname, parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())


class CredentialRedirectHandler(request.HTTPRedirectHandler):
    """Signed object URLs authenticate themselves; never forward the API token."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and _origin(req.full_url) != _origin(newurl):
            for header in ("Authorization", "Cookie", "Proxy-authorization"):
                redirected.remove_header(header)
        return redirected


def _http_error(exc: error.HTTPError) -> SculptaryError:
    message = str(exc.reason)
    try:
        payload = json.loads(exc.read(65536) or b"{}")
        detail = payload.get("error") if isinstance(payload, dict) else None
        value = detail.get("message") if isinstance(detail, dict) else None
        if isinstance(value, str) and value.strip():
            message = value[:1000]
    except (ValueError, OSError):
        pass
    return SculptaryError(exc.code, message)


class Client:
    def __init__(self, host: str, token: str = "", timeout: float = 60.0, opener=None):
        self.host = host.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._open = opener or request.build_opener(CredentialRedirectHandler()).open

    def _req(self, method: str, path: str, *, query: dict | None = None, body: bytes | None = None,
             content_type: str | None = None) -> request.Request:
        url = f"{self.host}/api/v1{path}"
        q = {k: v for k, v in (query or {}).items() if v not in (None, "")}
        if q:
            url += "?" + parse.urlencode(q)
        req = request.Request(url, data=body, method=method)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Accept", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if content_type:
            req.add_header("Content-Type", content_type)
        return req

    def _send(self, req: request.Request) -> Any:
        try:
            with self._open(req, timeout=self.timeout) as resp:
                data = resp.read()
        except error.HTTPError as exc:
            raise _http_error(exc) from None
        except error.URLError as exc:
            raise SculptaryError(0, f"Could not reach {self.host}: {exc.reason}") from None
        try:
            return json.loads(data) if data else None
        except ValueError:
            raise SculptaryError(502, "The server did not return valid JSON. Check the host and try again.") from None

    def get(self, api_path: str, **query) -> Any:
        return self._send(self._req("GET", api_path, query=query))

    def post_json(self, path: str, payload: dict) -> Any:
        return self._send(self._req("POST", path, body=json.dumps(payload).encode(), content_type="application/json"))

    def download(self, api_path: str, dest: str, **query) -> int:
        req = self._req("GET", api_path, query=query)
        try:
            with self._open(req, timeout=max(self.timeout, 600)) as resp, open(dest, "wb") as f:
                n = 0
                while chunk := resp.read(1024 * 1024):
                    f.write(chunk)
                    n += len(chunk)
                return n
        except error.HTTPError as exc:
            raise _http_error(exc) from None
        except error.URLError as exc:
            raise SculptaryError(0, f"Could not reach {self.host}: {exc.reason}") from None

    # --- Operations used by the add-on ------------------------------------

    def me(self) -> dict:
        return self.get("/user")

    def my_repositories(self) -> list[dict]:
        return self.get("/user/repos")

    def repository(self, full_name: str) -> dict:
        return self.get(f"/repos/{full_name}")

    def create_repository(self, name: str, private: bool, description: str = "") -> dict:
        return self.post_json("/repos", {"name": name, "visibility": "private" if private else "public", "description": description})

    def branches(self, full_name: str) -> list[dict]:
        return self.get(f"/repos/{full_name}/branches")

    def create_branch(self, full_name: str, name: str, from_ref: str) -> dict:
        return self.post_json(f"/repos/{full_name}/branches", {"name": name, "from_ref": from_ref})

    def pull_requests(self, full_name: str, state: str = "open") -> dict:
        return self.get(f"/repos/{full_name}/pulls", state=state)

    def pull_request(self, full_name: str, number: int) -> dict:
        return self.get(f"/repos/{full_name}/pulls/{number}")

    def pull_changes(self, full_name: str, number: int) -> dict:
        return self.get(f"/repos/{full_name}/pulls/{number}/changes")

    def create_pull_request(self, full_name: str, title: str, source_branch: str, *,
                            target_branch: str | None = None, body: str = "", draft: bool = False,
                            source_repository: str | None = None) -> dict:
        payload = {"title": title, "source_branch": source_branch, "body": body, "draft": draft}
        if target_branch is not None:
            payload["target_branch"] = target_branch
        if source_repository is not None:
            payload["source_repository"] = source_repository
        return self.post_json(f"/repos/{full_name}/pulls", payload)

    def comment_pull_request(self, full_name: str, number: int, body: str, *, path: str | None = None,
                             commit_sha: str | None = None, spatial_anchor: dict | None = None,
                             parent_id: str | None = None) -> dict:
        payload = {"body": body}
        payload.update({key: value for key, value in {"path": path, "commit_sha": commit_sha,
            "spatial_anchor": spatial_anchor, "parent_id": parent_id}.items() if value is not None})
        return self.post_json(f"/repos/{full_name}/pulls/{number}/comments", payload)

    def resolve_comment(self, full_name: str, comment_id: str, *, resolved: bool = True) -> dict:
        action = "resolve" if resolved else "unresolve"
        return self.post_json(f"/repos/{full_name}/comments/{parse.quote(comment_id, safe='')}/{action}", {})

    def assets(self, full_name: str, ref: str | None = None) -> list[dict]:
        return self.get(f"/repos/{full_name}/assets", ref=ref)["assets"]

    def asset_at(self, full_name: str, path: str, ref: str) -> dict:
        return self.get(f"/repos/{full_name}/asset", path=path, ref=ref)

    def download_preview(self, full_name: str, asset_id: str, dest: str) -> int:
        return self.download(f"/repos/{full_name}/assets/{parse.quote(asset_id, safe='')}/preview", dest, encoding="standard")

    def history(self, full_name: str, path: str, ref: str | None = None) -> list[dict]:
        return self.get(f"/repos/{full_name}/commits", ref=ref, path=path, per_page=20)["commits"]

    def download_file(self, full_name: str, path: str, dest: str, ref: str | None = None) -> int:
        return self.download(f"/repos/{full_name}/raw", dest, path=path, ref=ref, download="true")

    def upload(self, full_name: str, files: dict[str, str], message: str, branch: str | None = None) -> dict:
        """Commit local files (repository path -> local file path) in one commit."""
        repo = self.repository(full_name)
        branch = branch or repo["default_branch"]
        head = ""
        if not repo.get("is_empty"):
            selected = next((item for item in self.branches(full_name) if item["name"] == branch), None)
            if selected is None:
                raise SculptaryError(409, "The selected branch no longer exists. Refresh branches before publishing.")
            head = selected["commit"]
        fields = {"branch": branch, "message": message, "expected_head": head}
        body, ctype = encode_multipart(fields, files)
        return self._send(self._req("POST", f"/repos/{full_name}/contents", body=body, content_type=ctype))


def encode_multipart(fields: dict[str, str], files: dict[str, str]) -> tuple[bytes, str]:
    boundary = f"----sculptary{uuid.uuid4().hex}"
    out = bytearray()

    def part(headers: str, payload: bytes) -> None:
        out.extend(f"--{boundary}\r\n{headers}\r\n\r\n".encode())
        out.extend(payload)
        out.extend(b"\r\n")

    for k, v in fields.items():
        part(f'Content-Disposition: form-data; name="{k}"', str(v).encode())
    for repo_path in files:
        part('Content-Disposition: form-data; name="paths"', repo_path.encode())
    for repo_path, local in files.items():
        name = repo_path.rsplit("/", 1)[-1].replace('"', "")
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(local, "rb") as f:
            data = f.read()
        part(f'Content-Disposition: form-data; name="files"; filename="{name}"\r\nContent-Type: {ctype}', data)
    out.extend(f"--{boundary}--\r\n".encode())
    return bytes(out), f"multipart/form-data; boundary={boundary}"
