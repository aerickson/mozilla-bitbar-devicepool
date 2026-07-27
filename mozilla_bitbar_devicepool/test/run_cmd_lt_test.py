# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import shlex
import subprocess
import sys

import pytest

from mozilla_bitbar_devicepool import run_cmd_lt
from mozilla_bitbar_devicepool.lambdatest import run_cmd


def test_generate_config_includes_opt_in_artifact_paths():
    config = run_cmd.generate_config("SERIAL", "echo hello", artifact_paths=["fleetbench-artifacts/**"])

    assert "- output.txt" in config
    assert '- "fleetbench-artifacts/**"' in config


@pytest.mark.parametrize("path", ["", "/tmp/output", "../output", "output/../secret", "output//nested"])
def test_validate_artifact_path_rejects_unsafe_paths(path):
    with pytest.raises(ValueError):
        run_cmd.validate_artifact_path(path)


def test_run_on_device_preserves_artifacts_and_validates_required_globs(tmp_path, monkeypatch):
    user_script_dir = tmp_path / "user_script"
    user_script_dir.mkdir()
    (user_script_dir / "run_cmd_on_device.sh").write_text("#!/bin/bash\n")
    artifacts_root = tmp_path / "persistent-artifacts"

    def fake_run(cmd, **_kwargs):
        artifacts_dir = shlex.split(cmd)[shlex.split(cmd).index("--download-artifacts-path") + 1]
        output_dir = os.path.join(artifacts_dir, "run-cmd-output", "1")
        fleetbench_dir = os.path.join(artifacts_dir, "extra-artifact-1", "1", "fleetbench-artifacts")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.join(fleetbench_dir, "nested"), exist_ok=True)
        with open(os.path.join(output_dir, "output.txt"), "w") as artifact_file:
            artifact_file.write("command output")
        with open(os.path.join(fleetbench_dir, "nested", "result.json"), "w") as artifact_file:
            artifact_file.write("{}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(run_cmd.subprocess, "run", fake_run)

    result = run_cmd.run_on_device(
        "SERIAL",
        "echo hello",
        str(tmp_path),
        str(user_script_dir),
        artifacts_root=str(artifacts_root),
        artifact_paths=["fleetbench-artifacts/**"],
        required_artifact_globs=["fleetbench-artifacts/**/*.json"],
    )

    assert result == ("SERIAL", "command output", "ok")
    assert (
        artifacts_root / "SERIAL" / "extra-artifact-1" / "1" / "fleetbench-artifacts" / "nested" / "result.json"
    ).is_file()


def test_run_on_device_fails_when_required_artifact_is_missing(tmp_path, monkeypatch):
    user_script_dir = tmp_path / "user_script"
    user_script_dir.mkdir()
    (user_script_dir / "run_cmd_on_device.sh").write_text("#!/bin/bash\n")
    artifacts_root = tmp_path / "persistent-artifacts"

    def fake_run(cmd, **_kwargs):
        artifacts_dir = shlex.split(cmd)[shlex.split(cmd).index("--download-artifacts-path") + 1]
        os.makedirs(artifacts_dir, exist_ok=True)
        with open(os.path.join(artifacts_dir, "output.txt"), "w") as artifact_file:
            artifact_file.write("command output")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(run_cmd.subprocess, "run", fake_run)

    result = run_cmd.run_on_device(
        "SERIAL",
        "echo hello",
        str(tmp_path),
        str(user_script_dir),
        artifacts_root=str(artifacts_root),
        required_artifact_globs=["fleetbench-artifacts/**/*.json"],
    )

    assert result == ("SERIAL", "command output", "failed")


def test_run_batch_progress_identifies_the_latest_completed_device(monkeypatch):
    postfixes = []

    class FakeProgressBar:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def set_postfix_str(self, value):
            postfixes.append(value)

        def update(self, _count):
            pass

    monkeypatch.setattr(run_cmd, "tqdm", lambda **_kwargs: FakeProgressBar())
    monkeypatch.setattr(
        run_cmd,
        "run_on_device",
        lambda udid, *_args: (udid, "", "ok"),
    )

    run_cmd._run_batch(
        ["SERIAL"],
        "echo hello",
        ".",
        ".",
        max_parallel=1,
        timeout=1,
        queue_timeout=1,
        script_path=None,
        labels=[],
        artifacts_root=None,
        artifact_paths=[],
        required_artifact_globs=[],
    )

    assert postfixes == ["1/1 completed (latest: SERIAL [OK])"]


def test_main_rejects_duplicate_devices_before_launch(monkeypatch, capsys):
    class FakeConfiguration:
        def __init__(self, lightweight):
            self.config = {"device_groups": {}}

        def configure(self):
            pass

    monkeypatch.setattr(run_cmd_lt.configuration_lt, "ConfigurationLt", FakeConfiguration)
    monkeypatch.setattr(sys, "argv", ["lt_run_cmd", "echo hello", "--device", "SERIAL", "--device", "SERIAL"])

    with pytest.raises(SystemExit, match="1"):
        run_cmd_lt.main()

    assert "duplicate device serial(s): SERIAL" in capsys.readouterr().err
