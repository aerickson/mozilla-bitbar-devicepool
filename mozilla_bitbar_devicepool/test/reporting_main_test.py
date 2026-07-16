import datetime
import json
import sys
import xml.etree.ElementTree as ET

import pytest

from mozilla_bitbar_devicepool.reporting import main


def _write_cache(path, fetched_at, jobs):
    path.write_text(json.dumps({"fetched_at": fetched_at.isoformat(), "jobs": jobs}))


def test_get_report_jobs_uses_fresh_cache(monkeypatch, tmp_path, capsys):
    now = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.timezone.utc)
    jobs = [{"job_number": number} for number in range(5)]
    cache_path = tmp_path / "jobs.json"
    _write_cache(cache_path, now - datetime.timedelta(minutes=30), jobs)
    monkeypatch.setattr(main, "get_jobs", lambda *args, **kwargs: pytest.fail("API should not be called"))

    result = main.get_report_jobs("user", "key", 3, cache_path=cache_path, now=now)

    assert result == jobs[:3]
    assert "Job cache: 5 jobs" in capsys.readouterr().out


def test_get_report_jobs_requires_refresh_for_larger_request(tmp_path):
    now = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.timezone.utc)
    cache_path = tmp_path / "jobs.json"
    _write_cache(cache_path, now - datetime.timedelta(minutes=30), [{"job_number": 1}])

    with pytest.raises(SystemExit, match="--refresh"):
        main.get_report_jobs("user", "key", 2, cache_path=cache_path, now=now)


def test_get_report_jobs_refreshes_and_caches_minimal_fields(monkeypatch, tmp_path):
    now = datetime.datetime(2026, 7, 16, 12, 0, tzinfo=datetime.timezone.utc)
    cache_path = tmp_path / "jobs.json"
    api_jobs = [
        {
            "job_number": 123,
            "job_label": '["tcdp","a55-perf","device-1"]',
            "status": "completed",
            "unused_large_field": "not cached",
        }
    ]
    monkeypatch.setattr(main, "get_jobs", lambda *args, **kwargs: {"data": api_jobs})

    result = main.get_report_jobs("user", "key", 1, refresh=True, cache_path=cache_path, now=now)

    assert result == api_jobs
    cached_jobs = json.loads(cache_path.read_text())["jobs"]
    assert cached_jobs == [
        {
            "job_number": 123,
            "job_label": '["tcdp","a55-perf","device-1"]',
            "status": "completed",
        }
    ]


def test_job_distribution_report_filters_device_counts_and_unseen_devices_by_pool(monkeypatch, capsys):
    class FakeConfiguration:
        config = {
            "device_groups": {
                "a55-perf": ["a55-1", "a55-2"],
                "test-1": ["test-device"],
            }
        }

        def __init__(self, **kwargs):
            pass

        def configure(self):
            pass

    class FakeStatus:
        def __init__(self, username, access_key):
            pass

        def get_device_list(self):
            return {"a55": {"a55-1": "active", "a55-2": "active", "test-device": "active"}}

    class FakeTaskclusterClient:
        def __init__(self, verbose=False):
            pass

        def get_quarantined_worker_names(self, provisioner_id, worker_type):
            return []

    jobs = [
        {"job_label": '["tcdp","a55-perf","a55-1"]', "status": "completed"},
        {"job_label": '["tcdp","a55-perf","a55-1"]', "status": "failed"},
        {"job_label": '["tcdp","test-1","test-device"]', "status": "completed"},
        {"job_label": '["tcdp","a55-perf","test-device"]', "status": "completed"},
    ]

    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    monkeypatch.setattr(sys, "argv", ["lt_job_distribution_report", "-j", "4", "--pool", "a55-perf"])
    monkeypatch.setattr(main, "ConfigurationLt", FakeConfiguration)
    monkeypatch.setattr(main.status, "Status", FakeStatus)
    monkeypatch.setattr(main, "TaskclusterClient", FakeTaskclusterClient)
    monkeypatch.setattr(main, "get_report_jobs", lambda *args, **kwargs: jobs)

    main.job_distribution_report()

    output = capsys.readouterr().out
    assert "Device job counts (a55-perf pool):" in output
    assert "a55-1: 2 jobs, 1 failures" in output
    assert "test-device: 1 jobs, 0 failures" in output
    assert "Jobs matching pool a55-perf: 3" in output
    assert "Devices not seen that aren't quarantined (1 devices):" in output
    assert "a55-2 (lt api: active)" in output


def test_job_distribution_report_can_limit_counts_to_current_pool_members(monkeypatch, capsys):
    class FakeConfiguration:
        config = {"device_groups": {"a55-perf": ["a55-1"], "test-1": ["former-a55"]}}

        def __init__(self, **kwargs):
            pass

        def configure(self):
            pass

    class FakeStatus:
        def __init__(self, username, access_key):
            pass

        def get_device_list(self):
            return {"a55": {"a55-1": "active", "former-a55": "active"}}

    class FakeTaskclusterClient:
        def __init__(self, verbose=False):
            pass

        def get_quarantined_worker_names(self, provisioner_id, worker_type):
            return []

    jobs = [
        {"job_label": '["tcdp","a55-perf","a55-1"]', "status": "completed"},
        {"job_label": '["tcdp","a55-perf","former-a55"]', "status": "completed"},
    ]

    monkeypatch.setenv("LT_USERNAME", "user")
    monkeypatch.setenv("LT_ACCESS_KEY", "key")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lt_job_distribution_report",
            "-j",
            "2",
            "--pool",
            "a55-perf",
            "--current-members-only",
        ],
    )
    monkeypatch.setattr(main, "ConfigurationLt", FakeConfiguration)
    monkeypatch.setattr(main.status, "Status", FakeStatus)
    monkeypatch.setattr(main, "TaskclusterClient", FakeTaskclusterClient)
    monkeypatch.setattr(main, "get_report_jobs", lambda *args, **kwargs: jobs)

    main.job_distribution_report()

    output = capsys.readouterr().out
    assert "Device job counts (current a55-perf pool members):" in output
    assert "a55-1: 1 jobs, 0 failures" in output
    assert "former-a55:" not in output
    assert "Jobs matching pool a55-perf: 2" in output
    assert "Jobs excluded from former pool members: 1" in output


def test_write_device_job_counts_svg(tmp_path):
    output_path = tmp_path / "device-counts.svg"

    main.write_device_job_counts_svg(
        output_path,
        {"device-1": 10, "device-2": 5},
        {"device-1": 2},
        pool="a55-perf",
        jobs_inspected=5000,
        jobs_matching_pool=1200,
    )

    svg = output_path.read_text()
    ET.fromstring(svg)
    assert "Device job distribution — a55-perf pool" in svg
    assert "1,200 a55-perf jobs from 5,000 recent jobs inspected" in svg
    assert "device-1" in svg
    assert "10 jobs, 2 failed" in svg
    assert main.SVG_SUCCESS_COLOR in svg
    assert main.SVG_FAILURE_COLOR in svg
