# Branch and tag identity

Version 0.2.1 fixes reads from a selected branch when a tag shares its name.
Model listing, import, history and new-branch creation now identify the branch
with `refs/heads/`. Branch names stay readable in the interface, pull requests
and publish destinations. Publishing continues to use the selected branch's
recorded head as its concurrency check.

Comparisons qualify known branch names, retain explicit tags and object IDs,
and identify the selected branch explicitly when the head field is blank.
The initial base uses an explicit default-branch ref. This also handles branch
names that themselves look like refs or full hashes. History refuses stale
branch context instead of falling back to the repository default.

Before implementation, native regressions opened the same-named tag's model
list and used the wrong comparison base. The final checkpoint passes all 45
Python tests, all four native Blender 4.2.23 suites and extension packaging.
Coverage includes slash names, ref-like names, hash-like names, explicit tags,
immutable commits, blank comparison heads, stale selections, unchanged publish
destinations and temporary-file cleanup. Existing PR, scene, rest-pose and pin
checks also pass. This checkpoint does not claim a live-server or hosted CI pass.
