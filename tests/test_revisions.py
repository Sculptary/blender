"""Branch selectors and free-form revision inputs have distinct identities."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sculptary_blender"))
from revisions import branch_ref, comparison_ref  # noqa: E402


@pytest.mark.parametrize("name", ["main", "fit/v2", "refs/tags/v1", "a" * 40])
def test_branch_selection_always_identifies_a_branch(name):
    assert branch_ref(name) == f"refs/heads/{name}"


def test_comparison_branch_names_are_explicit_even_when_a_tag_can_share_them():
    assert comparison_ref("fit/v2", ["main", "fit/v2"]) == "refs/heads/fit/v2"


@pytest.mark.parametrize("revision", ["refs/tags/fit/v2", "refs/heads/fit/v2", "a" * 40, "b" * 64])
def test_explicit_comparison_revisions_are_not_reinterpreted_as_branch_names(revision):
    assert comparison_ref(revision, [revision, "main"]) == revision


def test_git_expressions_pass_through_without_a_branch_lookup():
    assert comparison_ref("HEAD~2", ["main", "fit/v2"]) == "HEAD~2"
