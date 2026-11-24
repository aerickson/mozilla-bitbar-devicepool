import datetime
import json
import stat
import sys

import pytest

from mozilla_bitbar_devicepool.lambdatest import api, pool_status, status


def test_build_pool_report_identifies_actionable_device_states():
    config = {
        "projects": {"a55-perf": {"TC_WORKER_TYPE": "gecko-t-lambda-perf-a55"}},
        "device_groups": {"a55-perf": ["busy", "missing", "quarantined", "idle", "maintenance"]},
    }
    report = pool_status.build_pool_report(
        config,
        {"A55": {"busy": "busy", "quarantined": "active", "idle": "active", "maintenance": "maintenance"}},
        [
            {"workerId": "busy", "state": "running", "quarantined": False},
            {"workerId": "quarantined", "state": "running", "quarantined": True},
            {"workerId": "former-device", "state": "running", "quarantined": False},
        ],
        [],
        "a55-perf",
    )

    by_udid = {device["udid"]: device for device in report["devices"]}
    assert by_udid["busy"]["finding"] == "busy_without_running_job"
    assert by_udid["missing"]["finding"] == "missing_from_lambdatest"
    assert by_udid["quarantined"]["finding"] == "taskcluster_quarantined"
    assert by_udid["idle"]["finding"] == "no_active_taskcluster_worker"
    assert by_udid["idle"]["severity"] == "warning"
    assert by_udid["maintenance"]["severity"] == "info"
    assert report["unconfigured_taskcluster_workers"] == ["former-device"]


def test_build_pool_report_suppresses_busy_finding_after_recent_tc_task():
    config = {
        "projects": {"a55-perf": {"TC_WORKER_TYPE": "gecko-t-lambda-perf-a55"}},
        "device_groups": {"a55-perf": ["device-1"]},
    }
    now = datetime.datetime(2026, 8, 24, 22, 0, tzinfo=datetime.timezone.utc)

    report = pool_status.build_pool_report(
        config,
        {"A55": {"device-1": "busy"}},
        [{"workerId": "device-1"}],
        [],
        "a55-perf",
        tc_task_activity_by_udid={"device-1": "2026-08-24T21:55:00Z"},
        recent_activity_minutes=10,
        now=now,
    )

    device = report["devices"][0]
    assert device["finding"] is None
    assert device["severity"] is None
    assert device["recent_tc_task"]
    assert device["tc_latest_task_activity"] == "2026-08-24T21:55:00Z"


@pytest.mark.parametrize(
    ("state", "job_times", "expected_seconds", "expected_basis", "expected_display"),
    [
        (
            "busy",
            [{"start_time": "2026-08-24T21:53:00Z", "created_at": "2026-08-24T21:50:00Z"}],
            420,
            "start_time",
            "7m",
        ),
        ("busy", [{"start_time": 1787608800}], 0, "start_time", "0s"),
        ("busy", [{"start_time": "invalid", "created_at": "2026-08-24T21:50:00Z"}], 600, "created_at", "10m (age)"),
        ("busy", [{"start_time": "2026-08-24T22:01:00Z"}], None, None, "unknown"),
        ("busy", [{}], None, None, "unknown"),
        ("busy", [], None, None, "unknown"),
        ("busy", [{"start_time": "2026-08-24T21:50:00Z"}] * 2, None, None, "unknown"),
        ("active", [{"start_time": "2026-08-24T21:50:00Z"}], None, None, "-"),
    ],
)
def test_pool_report_shows_elapsed_time_for_busy_device_with_one_matching_job(
    state, job_times, expected_seconds, expected_basis, expected_display, capsys
):
    config = {
        "projects": {"a55-perf": {"TC_WORKER_TYPE": "worker-type"}},
        "device_groups": {"a55-perf": ["device-1"]},
    }
    now = datetime.datetime(2026, 8, 24, 22, 0, tzinfo=datetime.timezone.utc)
    report = pool_status.build_pool_report(
        config,
        {"A55": {"device-1": state}},
        [{"workerId": "device-1"}],
        [{"job_label": '["device-1"]', **timestamps} for timestamps in job_times],
        "a55-perf",
        now=now,
        running_jobs_incomplete_reason="HyperExecute pagination cursor did not advance",
    )
    report["pending_task_count"] = 0

    device = report["devices"][0]
    assert device["lt_job_elapsed_seconds"] == expected_seconds
    assert device["lt_job_elapsed_basis"] == expected_basis
    pool_status.print_pool_report(report)
    _, _, headings, row, _ = capsys.readouterr().out.splitlines()
    assert row[headings.index("LT job elapsed") : headings.index("finding")].strip() == expected_display


def test_stuck_observation_tracks_continuous_state_and_resets(tmp_path):
    observation_path = tmp_path / "lt-pool-status" / "observations.json"
    initial_time = datetime.datetime(2026, 9, 3, 18, 0, tzinfo=datetime.timezone.utc)
    report = {
        "pool": "a55-perf",
        "devices": [{"udid": "device-1", "lt_state": "busy", "finding": "busy_without_running_job"}],
    }

    pool_status.update_state_observations(report, "user", observation_path, now=initial_time)
    assert report["devices"][0]["stuck_observed_for_seconds"] == 0
    assert stat.S_IMODE(observation_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(observation_path.parent.stat().st_mode) == 0o700

    later_report = {
        "pool": "a55-perf",
        "devices": [{"udid": "device-1", "lt_state": "busy", "finding": "busy_without_running_job"}],
    }
    pool_status.update_state_observations(
        later_report, "user", observation_path, now=initial_time + datetime.timedelta(minutes=7)
    )
    assert later_report["devices"][0]["stuck_observed_for_seconds"] == 420

    other_pool_report = {
        "pool": "p9-perf",
        "devices": [{"udid": "device-2", "lt_state": "busy", "finding": "busy_without_running_job"}],
    }
    pool_status.update_state_observations(
        other_pool_report, "user", observation_path, now=initial_time + datetime.timedelta(minutes=8)
    )
    observations = pool_status.load_observations(observation_path)
    assert set(observations) == {"user:a55-perf:device-1", "user:p9-perf:device-2"}

    healthy_report = {"pool": "a55-perf", "devices": [{"udid": "device-1", "lt_state": "busy", "finding": None}]}
    pool_status.update_state_observations(
        healthy_report, "user", observation_path, now=initial_time + datetime.timedelta(minutes=8)
    )

    reset_report = {
        "pool": "a55-perf",
        "devices": [{"udid": "device-1", "lt_state": "busy", "finding": "busy_without_running_job"}],
    }
    pool_status.update_state_observations(
        reset_report, "user", observation_path, now=initial_time + datetime.timedelta(minutes=9)
    )
    assert reset_report["devices"][0]["stuck_observed_for_seconds"] == 0
    assert reset_report["devices"][0]["state_observed_for_seconds"] == 540


@pytest.mark.parametrize("state", ["active", "busy", "maintenance", "cleanup", "missing"])
def test_state_observation_tracks_duration_and_resets_on_transition(tmp_path, state):
    observation_path = tmp_path / "observations.json"
    now = datetime.datetime(2026, 9, 3, 18, 0, tzinfo=datetime.timezone.utc)
    report = {"pool": "a55-perf", "devices": [{"udid": "device-1", "lt_state": state, "finding": None}]}

    pool_status.update_state_observations(report, "user", observation_path, now=now)
    assert report["devices"][0]["state_observed_for_seconds"] == 0
    pool_status.update_state_observations(report, "user", observation_path, now=now + datetime.timedelta(minutes=7))
    assert report["devices"][0]["state_observed_for_seconds"] == 420
    assert report["devices"][0]["stuck_observed_for_seconds"] is None

    report["devices"][0]["lt_state"] = "cleanup" if state != "cleanup" else "active"
    pool_status.update_state_observations(report, "user", observation_path, now=now + datetime.timedelta(minutes=8))
    assert report["devices"][0]["state_observed_for_seconds"] == 0
    report["devices"][0]["lt_state"] = state
    pool_status.update_state_observations(report, "user", observation_path, now=now + datetime.timedelta(minutes=9))
    assert report["devices"][0]["state_observed_for_seconds"] == 0


def test_state_observation_preserves_legacy_stuck_cache(tmp_path):
    observation_path = tmp_path / "observations.json"
    now = datetime.datetime(2026, 9, 3, 18, 0, tzinfo=datetime.timezone.utc)
    pool_status.write_observations(observation_path, {"user:a55-perf:device-1": {"observed_since": now.isoformat()}})
    report = {
        "pool": "a55-perf",
        "devices": [{"udid": "device-1", "lt_state": "busy", "finding": "busy_without_running_job"}],
    }
    pool_status.update_state_observations(report, "user", observation_path, now=now + datetime.timedelta(minutes=7))
    assert report["devices"][0]["state_observed_for_seconds"] == 420
    assert report["devices"][0]["stuck_observed_for_seconds"] == 420


def test_write_observations_preserves_existing_parent_permissions(tmp_path):
    parent = tmp_path / "shared"
    parent.mkdir()
    parent.chmod(0o755)
    path = parent / "state.json"

    pool_status.write_observations(path, {})

    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("output_format", ["--json", "--ids-only", "--color=never"])
@pytest.mark.parametrize("only_problems", [False, True])
def test_main_output_formats(monkeypatch, capsys, tmp_path, output_format, only_problems):
    class FakeConfiguration:
        def __init__(self, **kwargs):
            self.config = {
                "projects": {"a55-perf": {"TC_WORKER_TYPE": "worker-type"}},
                "device_groups": {"a55-perf": ["device-1"]},
            }

        def configure(self):
            pass

        def get_config(self):
            return self.config

    class FakeStatus:
        lt_username = "user"
        lt_api_key = "key"

        def __init__(self, username, api_key):
            assert (username, api_key) == ("user", "key")

        def get_device_list(self, *, require_inventory):
            assert require_inventory
            return {"A55": {"device-1": "active"}}

        def get_running_job_scan(self, jobs):
            assert jobs == 100
            return {"data": [], "incomplete_reason": None}

    class FakeTaskclusterClient:
        def __init__(self, verbose=False):
            pass

        def get_workers(self, provisioner_id, worker_type):
            assert (provisioner_id, worker_type) == ("proj-autophone", "worker-type")
            return [{"workerId": "device-1", "state": "running"}]

        def get_quarantined_workers(self, provisioner_id, worker_type, workers):
            return []

        def get_pending_tasks(self, provisioner_id, worker_type):
            assert (provisioner_id, worker_type) == ("proj-autophone", "worker-type")
            return 0

    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    monkeypatch.setattr(pool_status, "ConfigurationLt", FakeConfiguration)
    monkeypatch.setattr(pool_status, "Status", FakeStatus)
    monkeypatch.setattr(pool_status, "TaskclusterClient", FakeTaskclusterClient)
    args = ["lt_pool_status", "--pool", "a55-perf", "--state-file", str(tmp_path / "observations.json"), output_format]
    if only_problems:
        args.append("--only-problems")
    monkeypatch.setattr(sys, "argv", args)

    pool_status.main()

    output = capsys.readouterr().out
    if output_format == "--ids-only":
        assert output == ("" if only_problems else "device-1\n")
    elif output_format == "--color=never":
        assert ("device-1" in output) is not only_problems
        assert ("No matching devices." in output) is only_problems
    else:
        report = json.loads(output)
        assert report["pool"] == "a55-perf"
        assert report["configured_device_count"] == 1
        assert report["pending_task_count"] == 0
        if only_problems:
            assert report["devices"] == []
        else:
            assert report["devices"][0]["finding"] is None
            assert report["devices"][0]["state_observed_for_seconds"] == 0
            assert report["devices"][0]["state_observed_since"]


@pytest.mark.parametrize("output_format", [[], ["--json"], ["--only-problems"], ["--only-problems", "--ids-only"]])
def test_main_keeps_running_jobs_after_page_404(monkeypatch, mocker, capsys, tmp_path, output_format):
    config = mocker.patch.object(pool_status, "ConfigurationLt").return_value
    config.get_config.return_value = {
        "projects": {"a55-perf": {"TC_WORKER_TYPE": "worker-type"}},
        "device_groups": {"a55-perf": ["running-device", "unknown-device"]},
    }
    mocker.patch.object(
        status,
        "get_devices",
        return_value={
            "data": {
                "private_cloud_devices": [
                    {"name": "A55", "udid": device, "status": "busy"} for device in ("running-device", "unknown-device")
                ]
            }
        },
    )
    taskcluster = mocker.patch.object(pool_status, "TaskclusterClient").return_value
    taskcluster.get_workers.return_value = [{"workerId": device} for device in ("running-device", "unknown-device")]
    taskcluster.get_quarantined_workers.return_value = []
    taskcluster.get_pending_tasks.return_value = 5
    first_page = mocker.Mock(status_code=200)
    first_page.json.return_value = {"data": [{"job_number": 42, "job_label": '["running-device"]'}]}
    fetch = mocker.patch.object(api.bounded_jobs_session, "get", side_effect=[first_page, mocker.Mock(status_code=404)])
    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    monkeypatch.setattr(
        sys,
        "argv",
        ["lt_pool_status", "--pool", "a55-perf", "--state-file", str(tmp_path / "observations.json"), *output_format],
    )

    pool_status.main()

    assert fetch.call_count == 2
    taskcluster.get_worker_latest_task_activity.assert_not_called()
    output = capsys.readouterr()
    assert "job scan incomplete (HyperExecute returned HTTP 404)" in output.err
    assert "busy_without_running_job" not in output.out
    if "--json" in output_format:
        report = json.loads(output.out)
        running, unknown = report["devices"]
        assert running["running_lt_job"] is True
        assert unknown["running_lt_job"] is None
        assert unknown["finding"] is None
        assert report["running_jobs_incomplete_reason"] == "HyperExecute returned HTTP 404"
        assert report["pending_task_count"] == 5
    elif "--ids-only" in output_format:
        assert output.out == ""
    elif "--only-problems" in output_format:
        assert "No matching devices." in output.out
    else:
        assert "unknown-device  busy      ok         unknown" in output.out
        assert "pending Taskcluster tasks: 5" in output.out


def test_main_fails_without_writing_observations_when_inventory_is_unavailable(monkeypatch, mocker, capsys, tmp_path):
    config = mocker.patch.object(pool_status, "ConfigurationLt").return_value
    config.get_config.return_value = {
        "projects": {"a55-perf": {"TC_WORKER_TYPE": "worker-type"}},
        "device_groups": {"a55-perf": ["device-1"]},
    }
    mocker.patch.object(api.cached_session, "get", return_value=mocker.Mock(status_code=503))
    fetch_jobs = mocker.patch.object(status, "get_jobs")
    taskcluster = mocker.patch.object(pool_status, "TaskclusterClient")
    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    path = tmp_path / "observations.json"
    monkeypatch.setattr(sys, "argv", ["lt_pool_status", "--pool", "a55-perf", "--state-file", str(path), "--json"])

    with pytest.raises(SystemExit, match="LambdaTest device inventory unavailable"):
        pool_status.main()

    assert capsys.readouterr().out == ""
    assert not path.exists()
    fetch_jobs.assert_not_called()
    taskcluster.assert_not_called()


def test_device_order_groups_findings_then_udid_regardless_of_state():
    devices = [
        {"udid": udid, "severity": severity, "finding": finding, "lt_state": state}
        for udid, severity, finding, state in [
            ("healthy", None, None, "active"),
            ("info", "info", "no_active_taskcluster_worker", "maintenance"),
            ("quarantine", "warning", "taskcluster_quarantined", "active"),
            ("stuck-b", "warning", "busy_without_running_job", "busy"),
            ("stuck-a", "warning", "busy_without_running_job", "busy"),
            ("aaa-healthy-busy", None, None, "busy"),
        ]
    ]
    report = {"devices": devices}
    expected = ["stuck-a", "stuck-b", "quarantine", "info", "aaa-healthy-busy", "healthy"]
    assert [device["udid"] for device in pool_status.select_devices(report)] == expected
    assert [device["udid"] for device in pool_status.select_devices(report, True)] == expected[:4]
    assert report["devices"][0]["udid"] == "healthy"


def test_only_problems_includes_informational_findings(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 2,
            "taskcluster_worker_count": 0,
            "pending_task_count": 0,
            "unconfigured_taskcluster_workers": [],
            "devices": [
                {
                    "udid": "ok-device",
                    "lt_state": "active",
                    "tc_worker_state": "running",
                    "running_lt_job": False,
                    "finding": None,
                    "severity": None,
                },
                {
                    "udid": "no-worker",
                    "lt_state": "maintenance",
                    "tc_worker_state": "missing",
                    "running_lt_job": False,
                    "finding": "no_active_taskcluster_worker",
                    "severity": "info",
                },
            ],
        },
        only_problems=True,
    )

    output = capsys.readouterr().out
    assert "no-worker" in output
    assert "ok-device" not in output
    assert "LT state     TC worker" in output
    assert "pending Taskcluster tasks: 0" in output


def test_pool_report_colors_findings(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 1,
            "taskcluster_worker_count": 0,
            "pending_task_count": 3,
            "unconfigured_taskcluster_workers": [],
            "devices": [
                {
                    "udid": "bad-device",
                    "lt_state": "missing",
                    "tc_worker_state": "missing",
                    "running_lt_job": False,
                    "finding": "missing_from_lambdatest",
                    "severity": "warning",
                }
            ],
        },
        color=True,
    )

    output = capsys.readouterr().out
    assert "\033[31mmissing_from_lambdatest\033[0m" in output
    assert "\033[31mmissing" in output
    assert "pending Taskcluster tasks: 3" in output


def test_pool_report_uses_simple_taskcluster_worker_status(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 1,
            "taskcluster_worker_count": 1,
            "pending_task_count": 0,
            "unconfigured_taskcluster_workers": [],
            "devices": [
                {
                    "udid": "worker-device",
                    "lt_state": "busy",
                    "tc_worker_state": "standalone",
                    "running_lt_job": True,
                    "state_observed_for_seconds": 420,
                    "finding": None,
                    "severity": None,
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "worker-device  busy      ok" in output
    assert "standalone" not in output
    assert "7m" in output
