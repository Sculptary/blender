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
requests list their changed models and accept pinned comments at the 3D cursor.

The selected branch applies to browsing, import, history and publishing. Refresh
preserves your current branch; switching repositories selects that repository's
default branch. Publishing the first model creates an empty repository's default
branch. Temporary downloads and exports are removed after each operation.
Branch selections retain their explicit Git identity, so a tag with the same
name cannot redirect browsing, import, history or branch creation.

The pull request list shows the server's returned count and total, so its 100-row
limit is visible. Load an older review directly by number. Changing repositories,
host or access token clears the previous review context. Failed authorization
clears review data and shows the error.

## Compare revisions

Select a model, then enter a base ref and a head ref in **Compare revisions**.
A ref can be a branch name, an immutable commit or `refs/tags/name` for a tag.
A blank head uses the selected branch. Use `refs/heads/name` to explicitly name
a branch that resembles a commit ID or another Git ref. Enter **Previous path**
when the file was renamed. Each ref resolves to
an immutable asset before downloading its standard GLB preview.

The comparison opens in a separate scene. Both versions retain their authored
coordinates, hierarchy and scale; side-by-side layout adds only a display
translation along the initial viewport's horizontal axis. Overlay shows the base as wireframe. Reviews use the authored rest
pose, so animations do not change pin coordinates or autoplay. Source files stay
unchanged. Previews must be self-contained, with at most 32 MiB of JSON metadata.

**Close comparison** returns to the working scene, restores its view and removes generated data.
User-added objects and externally linked data are preserved. Publishing and model
import are blocked inside a comparison scene. Switch to object mode before
opening or closing a comparison. The server must support standard desktop
previews; if one is still being prepared, retry shortly.

For a pull request, use **Changed models > Load changed models**, select a file,
then **Compare selected model**. Forks use the source repository's immutable head;
renames use the previous path on the base side. Added or deleted files show an
explicit absent side.

Place the 3D cursor, choose **Head** or **Base**, enter a comment and press
**Post pin at cursor**. The pin uses that revision's canonical coordinates,
excluding the side-by-side offset. Pins carry explicit authored-pose context for
the web viewer. The add-on checks the latest PR revisions before posting and
keeps the draft if the request fails. Close and reopen a comparison when the
pull request has changed. An absent model cannot receive a pin.

## Development

The API client (`sculptary_blender/api.py`) uses only the standard library and is unit-tested outside
Blender. It includes branch creation, pull request discovery and creation, change
lists, spatial comments, threaded replies and resolution. Native controls support
pull request comparisons and posting cursor pins. Open the request on Sculptary
to read and manage its discussion threads.

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
blender --background --factory-startup --python-exit-code 1 --python tests/blender_review.py
```

An opt-in end-to-end review check accepts a temporary JSON config outside the
checkout. See the script's docstring for its fields. Use a disposable repository
with a processed model PR; the caller is responsible for fixture cleanup. Keep
the config private and remove it after the run. The token is read from the file
so it does not appear in process arguments:

```bash
blender -b --factory-startup --python-exit-code 1 --python tests/blender_review_integration.py -- /private/temp/fixture.json
```

Build the extension zip with `python build.py`.

## License

GPL-3.0-or-later (required for Blender add-ons).
