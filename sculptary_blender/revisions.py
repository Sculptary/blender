"""Preserve the identity of branch selections without changing explicit refs."""

import re
from collections.abc import Iterable


def branch_ref(name: str) -> str:
    return f"refs/heads/{name}"


def comparison_ref(ref: str, branches: Iterable[str]) -> str:
    if ref.startswith(("refs/heads/", "refs/tags/")) or re.fullmatch(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})", ref):
        return ref
    return branch_ref(ref) if ref in branches else ref
