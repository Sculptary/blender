import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sculptary_blender"))
import review_gltf


def glb(document, binary=b"mesh"):
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<II", len(encoded), 0x4e4f534a) + encoded
        + struct.pack("<II", len(binary), 0x004e4942) + binary)


def test_static_review_retains_authored_transforms_and_binary_data(tmp_path):
    document = {"asset": {"version": "2.0"}, "nodes": [{"name": "Shell", "translation": [5, 1, -2]}],
        "animations": [{"name": "Lift", "channels": []}],
        "extensionsUsed": ["KHR_animation_pointer", "KHR_materials_unlit"],
        "extensionsRequired": ["KHR_animation_pointer"], "buffers": [{"byteLength": 4}]}
    source, output = tmp_path / "source.glb", tmp_path / "review.glb"
    source.write_bytes(glb(document))
    result, clips = review_gltf.static_preview(source, output)
    assert result == output and clips == 1
    data = output.read_bytes()
    length = struct.unpack_from("<I", data, 12)[0]
    actual = json.loads(data[20:20 + length])
    assert "animations" not in actual
    assert actual["nodes"] == document["nodes"]
    assert actual["extensionsUsed"] == ["KHR_materials_unlit"]
    assert "extensionsRequired" not in actual
    assert data[20 + length:] == struct.pack("<II", 4, 0x004e4942) + b"mesh"
    assert source.read_bytes() == glb(document)


def test_static_source_is_used_without_a_second_copy(tmp_path):
    source, output = tmp_path / "source.glb", tmp_path / "review.glb"
    source.write_bytes(glb({"asset": {"version": "2.0"}}))
    assert review_gltf.static_preview(source, output) == (source, 0)
    assert not output.exists()


@pytest.mark.parametrize("uri", ["../private.bin", "file:///private.bin", "https://x.test/mesh", "//x.test/a"])
@pytest.mark.parametrize("kind", ["buffers", "images"])
def test_review_never_reads_external_or_local_resources(tmp_path, uri, kind):
    source = tmp_path / "source.glb"
    source.write_bytes(glb({"asset": {"version": "2.0"}, kind: [{"uri": uri}]}))
    with pytest.raises(review_gltf.PreviewError, match="self-contained"):
        review_gltf.static_preview(source, tmp_path / "review.glb")


@pytest.mark.parametrize("data", [b"invalid", b"glTF" + b"\0" * 40, glb([]), glb({"buffers": 7}),
    glb({"asset": {"version": "2.0"}, "animations": [{}], "extensionsRequired": None})])
def test_malformed_previews_have_a_clear_error(tmp_path, data):
    source = tmp_path / "source.glb"
    source.write_bytes(data)
    with pytest.raises(review_gltf.PreviewError):
        review_gltf.static_preview(source, tmp_path / "review.glb")
