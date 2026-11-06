# ShapesDB for Blender

Sign in to [ShapesDB](https://shapesdb.com), browse your repositories, import models into the scene,
check a file's version history, and publish the current scene as a GLB commit, all from the 3D Viewport
sidebar (N panel, ShapesDB tab).

Every publish is a real Git commit in your repository, stored with Git LFS, and processed by ShapesDB
for previews and geometry metadata.

## Install

Blender 4.2 or newer. Download the zip from
[Releases](https://github.com/ShapesDB/blender/releases) and use *Edit > Preferences > Get Extensions >
Install from Disk*. Then add an access token (scopes `repo:write` and `user`) in the add-on preferences
and press *Sign in*.

## Status

Foundations: sign-in, repository list and creation, model list with processing status, import (GLB,
glTF, OBJ, STL, PLY), per-file history, publish scene or selection as GLB. Planned: branch selection,
pull requests and side-by-side comparison inside Blender.

## Development

The API client (`shapesdb_blender/api.py`) uses only the standard library and is unit-tested outside
Blender:

```bash
python -m pytest tests/test_api.py
```

End-to-end check against a running server, inside Blender:

```bash
blender -b --factory-startup --python tests/blender_integration.py -- <host> <token> <repo-dir>
```

Build the extension zip with `python build.py`.

## License

GPL-3.0-or-later (required for Blender add-ons).
