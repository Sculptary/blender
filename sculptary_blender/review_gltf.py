"""Prepare a self-contained, static GLB without changing geometry or transforms."""

import json
import shutil
import struct
from pathlib import Path

MAX_JSON_BYTES = 32 * 1024 * 1024


class PreviewError(ValueError):
    pass


def static_preview(source: Path, destination: Path) -> tuple[Path, int]:
    with source.open("rb") as stream:
        header = stream.read(20)
        if len(header) != 20:
            raise PreviewError("The desktop preview is not a valid GLB.")
        magic, version, total, length, kind = struct.unpack("<4sIIII", header)
        if magic != b"glTF" or version != 2 or total != source.stat().st_size or kind != 0x4e4f534a or length > total - 20:
            raise PreviewError("The desktop preview is not a valid GLB.")
        if length > MAX_JSON_BYTES:
            raise PreviewError("The preview metadata exceeds the 32 MiB desktop review limit.")
        try:
            document = json.loads(stream.read(length))
            if not isinstance(document, dict) or document.get("asset", {}).get("version") != "2.0":
                raise ValueError()
            for group in ("buffers", "images"):
                entries = document.get(group, [])
                if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                    raise ValueError()
                for entry in entries:
                    uri = entry.get("uri")
                    if uri is not None and (not isinstance(uri, str) or not uri.startswith("data:")):
                        raise PreviewError("The desktop review preview must be self-contained.")
            clips = document.get("animations", [])
            if not isinstance(clips, list):
                raise ValueError()
            for key in ("extensionsUsed", "extensionsRequired"):
                values = document.get(key, [])
                if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                    raise ValueError()
        except PreviewError:
            raise
        except (ValueError, TypeError, AttributeError):
            raise PreviewError("The desktop preview contains invalid GLB metadata.") from None
        if not clips:
            return source, 0
        document.pop("animations", None)
        for key in ("extensionsUsed", "extensionsRequired"):
            if key in document:
                document[key] = [value for value in document[key] if value != "KHR_animation_pointer"]
                if not document[key]:
                    document.pop(key)
        encoded = json.dumps(document, separators=(",", ":")).encode()
        encoded += b" " * (-len(encoded) % 4)
        with destination.open("wb") as output:
            output.write(struct.pack("<4sIIII", magic, version, total - length + len(encoded), len(encoded), kind))
            output.write(encoded)
            shutil.copyfileobj(stream, output)
        return destination, len(clips)
