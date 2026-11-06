"""Build dist/shapesdb-<version>.zip for installation as a Blender extension."""

import pathlib
import tomllib
import zipfile

root = pathlib.Path(__file__).parent
pkg = root / "shapesdb_blender"
version = tomllib.loads((pkg / "blender_manifest.toml").read_text())["version"]
out = root / "dist" / f"shapesdb-{version}.zip"
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts:
            z.write(f, f.relative_to(pkg))
    z.write(root / "LICENSE", "LICENSE")
print(out)
