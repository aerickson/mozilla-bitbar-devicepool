import datetime
import json
import sys

from mozilla_bitbar_devicepool.lambdatest import pool_status


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


def test_main_outputs_json(monkeypatch, capsys):
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

        def get_device_list(self):
            return {"A55": {"device-1": "active"}}

    class FakeTaskclusterClient:
        def __init__(self, verbose=False):
            pass

        def get_workers(self, provisioner_id, worker_type):
            assert (provisioner_id, worker_type) == ("proj-autophone", "worker-type")
            return [{"workerId": "device-1", "state": "running"}]

        def get_quarantined_workers(self, provisioner_id, worker_type, workers):
            return []

    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    monkeypatch.setattr(pool_status, "ConfigurationLt", FakeConfiguration)
    monkeypatch.setattr(pool_status, "Status", FakeStatus)
    monkeypatch.setattr(pool_status, "TaskclusterClient", FakeTaskclusterClient)
    monkeypatch.setattr(pool_status, "get_jobs", lambda *args, **kwargs: {"data": []})
    monkeypatch.setattr(sys, "argv", ["lt_pool_status", "--pool", "a55-perf", "--json"])

    pool_status.main()

    report = json.loads(capsys.readouterr().out)
    assert report["pool"] == "a55-perf"
    assert report["devices"][0]["finding"] is None


def test_only_problems_includes_informational_findings(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 2,
            "taskcluster_worker_count": 0,
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


def test_pool_report_colors_findings(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 1,
            "taskcluster_worker_count": 0,
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


def test_pool_report_uses_simple_taskcluster_worker_status(capsys):
    pool_status.print_pool_report(
        {
            "pool": "pool",
            "worker_type": "worker-type",
            "configured_device_count": 1,
            "taskcluster_worker_count": 1,
            "unconfigured_taskcluster_workers": [],
            "devices": [
                {
                    "udid": "worker-device",
                    "lt_state": "busy",
                    "tc_worker_state": "standalone",
                    "running_lt_job": True,
                    "finding": None,
                    "severity": None,
                }
            ],
        }
    )

    output = capsys.readouterr().out
    assert "worker-device  busy      ok" in output
    assert "standalone" not in output
