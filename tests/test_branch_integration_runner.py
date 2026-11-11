"""Failure logs must remain useful without leaking the fixture credential."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_branch_identity_integration as runner  # noqa: E402


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_native_logs_are_redacted_including_partial_timeout_output(tmp_path, monkeypatch, outcome):
    token = "fixture-token-must-not-appear"
    config, log = tmp_path / "private.json", tmp_path / "output/native.log"
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 180, output=f"Partial {token}".encode(), stderr=b"Still waiting")
        return subprocess.CompletedProcess(command, 0 if outcome == "success" else 1, stdout=f"Result {token}", stderr="Native diagnostic")

    monkeypatch.setattr(runner.subprocess, "run", run)
    if outcome == "success":
        runner.run_native("fixture-blender", config, log, token)
    else:
        with pytest.raises(RuntimeError, match="timed out" if outcome == "timeout" else "failed"):
            runner.run_native("fixture-blender", config, log, token)
    output = log.read_text(encoding="utf-8")
    assert token not in output and "[redacted]" in output
    diagnostic = "Still waiting" if outcome == "timeout" else "Native diagnostic"
    assert diagnostic in output
    assert token not in str(commands)
    assert commands[0][-2:] == ["--", str(config)]


@pytest.mark.parametrize("host", ["https://example.invalid", "https://localhost.example.invalid"])
def test_external_hosts_are_refused_before_creating_a_fixture(monkeypatch, host):
    calls = []
    monkeypatch.setattr(runner.sys, "argv", ["runner", "--blender", "fixture-blender", "--host", host])
    monkeypatch.setattr(runner, "server", lambda *args: calls.append(args))
    with pytest.raises(SystemExit) as caught:
        runner.main()
    assert caught.value.code == 2 and calls == []
