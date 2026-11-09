# Sculptary for Blender

Sign in to [Sculptary](https://sculptary.com), browse your repositories, import models into the scene,
check a file's version history, and publish the current scene as a GLB commit, all from the 3D Viewport
sidebar (N panel, Sculptary tab).

Every publish is a real Git commit in your repository, stored with Git LFS, and processed by Sculptary
for previews and geometry metadata.

## Install

Blender 4.2 or newer. Download the zip from
[Releases](https://github.com/Sculptary/blender/releases) and use *Edit > Preferences > Get Extensions >
Install from Disk*. Then add an access token (scopes `repo:write` and `user`) in the add-on preferences
and press *Sign in*.

## Status

Sign-in, repository list and creation, branch selection and creation, model list
with processing status, import (GLB, glTF, OBJ, STL, PLY), per-file history and
publishing a scene or selection as GLB are implemented. Pull requests can be
listed, filtered, loaded by number, opened on Sculptary and created from the
selected branch, including drafts. Models can be compared between two refs in
aligned Base and Head collections, with side-by-side and overlay layouts. Pull
request model selection and cursor pins remain in progress.

The selected branch applies to browsing, import, history and publishing. Refresh
preserves your current branch; switching repositories selects that repository's
default branch. Publishing the first model creates an empty repository's default
branch. Temporary downloads and exports are removed after each operation.

The pull request list shows the server's returned count and total, so its 100-row
limit is visible. Load an older review directly by number. Changing repositories,
host or access token clears the previous review context. Failed authorization
clears review data and shows the error.

## Compare revisions

Select a model, then enter a base ref and a head ref in **Compare revisions**.
A ref can be a branch or an immutable commit. A blank head uses the selected
branch. Enter **Previous path** when the file was renamed. Each ref resolves to
an immutable asset before downloading its standard GLB preview.

The comparison opens in a separate scene. Both versions retain their authored
coordinates, hierarchy and scale; side-by-side layout adds only a display
translation. Overlay shows the base as wireframe. Reviews use the authored rest
pose, so animations do not change pin coordinates or autoplay. Source files stay
unchanged. Previews must be self-contained, with at most 32 MiB of JSON metadata.

**Close comparison** returns to the working scene and removes generated data.
User-added objects and externally linked data are preserved. Publishing and model
import are blocked inside a comparison scene. Switch to object mode before
opening or closing a comparison. The server must support standard desktop
previews; if one is still being prepared, retry shortly.

## Development

The API client (`sculptary_blender/api.py`) uses only the standard library and is unit-tested outside
Blender. It includes branch creation, pull request discovery and creation, change
lists, spatial comments, threaded replies and resolution. Pull request comparison
and comment controls are still in progress.

Run the client tests with:

```bash
python -m pytest tests
```

Native branch tests use real Blender import/export operators with an in-memory
API fixture and no account or server:

```bash
blender --background --factory-startup --python-exit-code 1 --python tests/blender_branches.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_pulls.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_comparison.py
```

End-to-end check against a running server, inside Blender:

```bash
blender -b --factory-startup --python tests/blender_integration.py -- <host> <token> <repo-dir>
```

Build the extension zip with `python build.py`.

## License

GPL-3.0-or-later (required for Blender add-ons).
