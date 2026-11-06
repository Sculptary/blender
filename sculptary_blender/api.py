"""Sculptary API client using only the Python standard library (Blender ships no extras).

Kept free of `bpy` so it can be tested outside Blender.
"""

from __future__ import annotations

import json
import mimetypes
import uuid
from typing import Any
from urllib import error, parse, request

USER_AGENT = "sculptary-blender/0.1.0"


class SculptaryError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Client:
    def __init__(self, host: str, token: str = "", timeout: float = 60.0, opener=None):
        self.host = host.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._open = opener or request.urlopen

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
            try:
                msg = json.loads(exc.read() or b"{}").get("error", {}).get("message") or exc.reason
            except ValueError:
                msg = str(exc.reason)
            raise SculptaryError(exc.code, str(msg)) from None
        except error.URLError as exc:
            raise SculptaryError(0, f"Could not reach {self.host}: {exc.reason}") from None
        return json.loads(data) if data else None

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
            raise SculptaryError(exc.code, f"Download failed ({exc.code})") from None

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

    def assets(self, full_name: str, ref: str | None = None) -> list[dict]:
        return self.get(f"/repos/{full_name}/assets", ref=ref)["assets"]

    def history(self, full_name: str, path: str, ref: str | None = None) -> list[dict]:
        return self.get(f"/repos/{full_name}/commits", ref=ref, path=path, per_page=20)["commits"]

    def download_file(self, full_name: str, path: str, dest: str, ref: str | None = None) -> int:
        return self.download(f"/repos/{full_name}/raw", dest, path=path, ref=ref, download="true")

    def upload(self, full_name: str, files: dict[str, str], message: str, branch: str | None = None) -> dict:
        """Commit local files (repository path -> local file path) in one commit."""
        repo = self.repository(full_name)
        branch = branch or repo["default_branch"]
        head = "" if repo.get("is_empty") else next((b["commit"] for b in self.branches(full_name) if b["name"] == branch), "")
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
