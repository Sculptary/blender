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
checks also pass. Hosted CI for `088f088` passes both Python/package and native
Linux Blender jobs in run `42976253953`.

## Live verification

The reproducible local-stack runner passes listing, import, history, comparisons,
branch creation and publication in real Blender. Its private fixture has two
model revisions and colliding `main` and `fit/v2` tags that point to the opposite
branch commits. Model lists differ, and the imported head geometry measures
2.5 units wide. Branch and explicit-tag comparisons use the expected immutable
commits. A new branch starts from the selected branch's commit, then receives
the published GLB while both original branches and tags retain their commits.
All fixture models, including the published GLB, reach ready state before
cleanup. The repository, account and namespace are removed; audit records remain.

All 50 Python tests pass after adding runner regressions for success, failure,
partial timeout logs and external-host refusal. They verify token redaction and
that credentials never enter subprocess arguments. Native logs live in the platform's ignored `.local`
directory. The integration runner uses a private temporary config and refuses
external hosts or unrelated repository names.
