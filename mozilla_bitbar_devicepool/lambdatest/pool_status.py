"""Cross-check the configured, LambdaTest, and Taskcluster views of a pool."""

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

from mozilla_bitbar_devicepool.configuration_lt import ConfigurationLt
from mozilla_bitbar_devicepool.lambdatest.api import get_jobs
from mozilla_bitbar_devicepool.lambdatest.status import RUNNING_JOB_STATUS, Status
from mozilla_bitbar_devicepool.lambdatest.util import get_device_from_job_labels, string_list_to_list
from mozilla_bitbar_devicepool.taskcluster_client import TaskclusterClient

PROVISIONER_ID = "proj-autophone"
RESET = "\033[0m"
FINDING_COLORS = {"warning": "\033[31m", "info": "\033[33m", None: "\033[32m"}
LT_STATE_COLORS = {
    "active": "\033[32m",
    "busy": "\033[36m",
    "maintenance": "\033[33m",
    "cleanup": "\033[35m",
    "missing": "\033[31m",
}
TC_WORKER_COLORS = {"ok": "\033[32m", "missing": "\033[31m"}
STUCK_FINDING = "busy_without_running_job"


def default_observation_path():
    """Return the private, tool-specific cache path for device observations."""
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "mozilla-bitbar-devicepool" / "lt-pool-status" / "observations.json"


def format_duration(duration):
    seconds = max(0, int(duration.total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {seconds % 3600 // 60}m"


def load_observations(observation_path):
    """Load prior observations, treating an unreadable cache as empty."""
    try:
        contents = json.loads(observation_path.read_text())
        observations = contents.get("observations", {})
        return observations if isinstance(observations, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_observations(observation_path, observations):
    """Atomically write the private observation cache."""
    observation_path.parent.mkdir(parents=True, exist_ok=True)
    observation_path.parent.chmod(0o700)
    with tempfile.NamedTemporaryFile("w", dir=observation_path.parent, delete=False) as temp_file:
        json.dump({"version": 1, "observations": observations}, temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_path = Path(temp_file.name)
    temp_path.chmod(0o600)
    temp_path.replace(observation_path)


def observed_duration(observed_since, now):
    """Return a valid start timestamp and elapsed seconds for an observation."""
    try:
        observed_at = datetime.datetime.fromisoformat(observed_since.replace("Z", "+00:00"))
        if observed_at.tzinfo is None or observed_at > now:
            raise ValueError("Invalid observation timestamp")
    except (AttributeError, ValueError):
        observed_since = now.isoformat()
        observed_at = now
    return observed_since, int((now - observed_at).total_seconds())


def update_state_observations(report, lt_username, observation_path=None, now=None):
    """Track current LT state durations, retaining separate stuck durations."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    observation_path = observation_path or default_observation_path()
    previous_observations = load_observations(observation_path)
    observation_prefix = f"{lt_username}:{report['pool']}:"
    observations = {
        key: observation for key, observation in previous_observations.items() if not key.startswith(observation_prefix)
    }

    for device in report["devices"]:
        key = f"{observation_prefix}{device['udid']}"
        previous = previous_observations.get(key, {})
        observed_since = None
        if previous.get("lt_state") == device["lt_state"]:
            observed_since = previous.get("state_observed_since")
        elif "lt_state" not in previous and device["lt_state"] == "busy":
            # Older caches only recorded stuck devices, which were always busy.
            observed_since = previous.get("observed_since")
        device["state_observed_since"], device["state_observed_for_seconds"] = observed_duration(observed_since, now)
        observation = {
            "lt_state": device["lt_state"],
            "state_observed_since": device["state_observed_since"],
            "last_seen": now.isoformat(),
        }
        device["stuck_observed_since"] = None
        device["stuck_observed_for_seconds"] = None
        if device["finding"] == STUCK_FINDING:
            device["stuck_observed_since"], device["stuck_observed_for_seconds"] = observed_duration(
                previous.get("observed_since"), now
            )
            observation["observed_since"] = device["stuck_observed_since"]
        observations[key] = observation

    write_observations(observation_path, observations)


def is_recent_timestamp(timestamp, now, recent_activity_minutes):
    """Whether an ISO 8601 timestamp is within the configured window."""
    if not timestamp:
        return False
    timestamp_at = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return now - timestamp_at <= datetime.timedelta(minutes=recent_activity_minutes)


def build_pool_report(
    config,
    lt_device_list,
    tc_workers,
    running_jobs,
    pool_name,
    tc_task_activity_by_udid=None,
    recent_activity_minutes=10,
    now=None,
):
    """Join the three service views into a serializable per-device report."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    tc_task_activity_by_udid = tc_task_activity_by_udid or {}
    pool_devices = set(config["device_groups"].get(pool_name) or [])
    worker_type = config["projects"][pool_name].get("TC_WORKER_TYPE")
    lt_devices = {
        udid: {"device_type": device_type, "state": state}
        for device_type, devices in lt_device_list.items()
        for udid, state in devices.items()
    }
    workers_by_id = {worker["workerId"]: worker for worker in tc_workers if worker.get("workerId")}
    running_devices = {
        get_device_from_job_labels(string_list_to_list(job.get("job_label")), known_device_ids=pool_devices)
        for job in running_jobs
    }
    running_devices.discard(None)

    devices = []
    for udid in sorted(pool_devices):
        lt_device = lt_devices.get(udid)
        worker = workers_by_id.get(udid)
        lt_state = lt_device["state"] if lt_device else "missing"
        tc_task_activity = tc_task_activity_by_udid.get(udid)
        recent_tc_task = is_recent_timestamp(tc_task_activity, now, recent_activity_minutes)
        finding = None
        severity = None
        if not lt_device:
            finding, severity = "missing_from_lambdatest", "warning"
        elif lt_state == "busy" and udid not in running_devices:
            if recent_tc_task:
                # A worker that just completed or started a task is normally
                # in the LT/TC handoff or teardown window. Keep metadata in
                # JSON, but do not add noise to the human report.
                pass
            else:
                finding, severity = "busy_without_running_job", "warning"
        elif worker and worker.get("quarantined"):
            finding, severity = "taskcluster_quarantined", "warning"
        elif not worker:
            # Worker Manager lists active workers, so this is useful context,
            # but a device that LambdaTest considers active should have one.
            finding = "no_active_taskcluster_worker"
            severity = "warning" if lt_state == "active" else "info"

        devices.append(
            {
                "udid": udid,
                "lt_state": lt_state,
                "lt_device_type": lt_device["device_type"] if lt_device else None,
                "tc_worker_state": worker.get("state", "unknown") if worker else "missing",
                "tc_quarantined": bool(worker and worker.get("quarantined")),
                "tc_quarantine_until": worker.get("quarantineUntil") if worker else None,
                "tc_last_active": worker.get("lastDateActive") if worker else None,
                "tc_latest_task_activity": tc_task_activity,
                "recent_tc_task": recent_tc_task,
                "running_lt_job": udid in running_devices,
                "state_observed_since": None,
                "state_observed_for_seconds": None,
                "stuck_observed_since": None,
                "stuck_observed_for_seconds": None,
                "finding": finding,
                "severity": severity,
            }
        )

    return {
        "pool": pool_name,
        "worker_type": worker_type,
        "configured_device_count": len(pool_devices),
        "taskcluster_worker_count": len(tc_workers),
        "unconfigured_taskcluster_workers": sorted(set(workers_by_id) - pool_devices),
        "devices": devices,
    }


def select_devices(report, only_problems=False):
    """Group actionable findings first, with stable UDID ordering."""
    return sorted(
        (device for device in report["devices"] if not only_problems or device["finding"]),
        key=lambda device: (
            {"warning": 0, "info": 1, None: 2}[device["severity"]],
            device["finding"] or "",
            device["udid"],
        ),
    )


def print_pool_report(report, only_problems=False, color=False):
    """Render a compact, human-readable version of a pool report."""
    devices = select_devices(report, only_problems)

    print(f"Pool: {report['pool']} ({report['worker_type']})")
    print(
        f"Configured devices: {report['configured_device_count']}; "
        f"active Taskcluster workers: {report['taskcluster_worker_count']}; "
        f"pending Taskcluster tasks: {report['pending_task_count']}"
    )
    rows = [
        (
            device["udid"],
            device["lt_state"],
            "missing" if device["tc_worker_state"] == "missing" else "ok",
            "running" if device["running_lt_job"] else "-",
            format_duration(datetime.timedelta(seconds=device["state_observed_for_seconds"]))
            if device.get("state_observed_for_seconds") is not None
            else "-",
            device["finding"] or "ok",
        )
        for device in devices
    ]
    headings = ("UDID", "LT state", "TC worker", "LT job", "observed", "finding")
    widths = [max(len(heading), *(len(row[index]) for row in rows)) for index, heading in enumerate(headings)]
    print("  ".join(f"{heading:<{width}}" for heading, width in zip(headings, widths)))
    for device, row in zip(devices, rows):
        formatted_row = [f"{value:<{width}}" for value, width in zip(row, widths)]
        if color:
            state_color = LT_STATE_COLORS.get(device["lt_state"])
            if state_color:
                formatted_row[1] = f"{state_color}{formatted_row[1]}{RESET}"
            formatted_row[2] = f"{TC_WORKER_COLORS[row[2]]}{formatted_row[2]}{RESET}"
            formatted_row[-1] = f"{FINDING_COLORS[device['severity']]}{formatted_row[-1]}{RESET}"
        print("  ".join(formatted_row))

    warnings = [device for device in report["devices"] if device["severity"] == "warning"]
    print(f"Warnings: {len(warnings)}")
    if report["unconfigured_taskcluster_workers"]:
        print("Taskcluster workers not in this configured pool:")
        for worker_id in report["unconfigured_taskcluster_workers"]:
            print(f"  {worker_id}")
    if not devices:
        print("No matching devices.")


def main():
    parser = argparse.ArgumentParser(
        description="Show configured devices alongside their LambdaTest and Taskcluster status."
    )
    parser.add_argument("--pool", required=True, help="Configured LambdaTest pool to inspect")
    parser.add_argument("--jobs", "-j", type=int, default=100, help="Maximum running LambdaTest jobs to inspect")
    parser.add_argument(
        "--recent-tc-task-minutes",
        type=int,
        default=10,
        help="Suppress busy-without-job findings after a TC task this recent (default: 10)",
    )
    parser.add_argument("--only-problems", action="store_true", help="Hide healthy rows")
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Override the tool-specific device-state observation cache path",
    )
    output_format = parser.add_mutually_exclusive_group()
    output_format.add_argument("--json", action="store_true", help="Write the report as JSON")
    output_format.add_argument("--ids-only", action="store_true", help="Write only device UDIDs, one per line")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Color findings in terminal output (default: auto)",
    )
    args = parser.parse_args()
    if args.recent_tc_task_minutes < 0:
        parser.error("--recent-tc-task-minutes must be non-negative")

    config_object = ConfigurationLt(lightweight=True, quiet=True)
    config_object.configure()
    config = config_object.get_config()
    if args.pool not in config.get("device_groups", {}):
        parser.error(f"unknown pool {args.pool!r}; choose from: {', '.join(sorted(config['device_groups']))}")
    if args.pool not in config.get("projects", {}):
        parser.error(f"pool {args.pool!r} has no Taskcluster project configuration")

    status_client = Status(os.environ["LT_USERNAME"], os.environ["LT_ACCESS_KEY"])
    lt_device_list = status_client.get_device_list()
    running_jobs = (
        get_jobs(status_client.lt_username, status_client.lt_api_key, jobs=args.jobs, status=RUNNING_JOB_STATUS) or {}
    ).get("data", [])

    tc_client = TaskclusterClient(verbose=False)
    workers = tc_client.get_workers(PROVISIONER_ID, config["projects"][args.pool]["TC_WORKER_TYPE"])
    quarantined_ids = {
        worker["workerId"]
        for worker in tc_client.get_quarantined_workers(
            PROVISIONER_ID, config["projects"][args.pool]["TC_WORKER_TYPE"], workers
        )
    }
    for worker in workers:
        worker["quarantined"] = worker.get("workerId") in quarantined_ids

    pool_devices = set(config["device_groups"].get(args.pool) or [])
    busy_devices = {
        udid
        for devices in lt_device_list.values()
        for udid, state in devices.items()
        if state == "busy" and udid in pool_devices
    }
    running_devices = {
        get_device_from_job_labels(string_list_to_list(job.get("job_label")), known_device_ids=pool_devices)
        for job in running_jobs
    }
    tc_task_activity_by_udid = {
        worker["workerId"]: tc_client.get_worker_latest_task_activity(worker)
        for worker in workers
        if worker.get("workerId") in busy_devices - running_devices
    }

    report = build_pool_report(
        config,
        lt_device_list,
        workers,
        running_jobs,
        args.pool,
        tc_task_activity_by_udid=tc_task_activity_by_udid,
        recent_activity_minutes=args.recent_tc_task_minutes,
    )
    if not args.ids_only:
        report["pending_task_count"] = tc_client.get_pending_tasks(
            PROVISIONER_ID, config["projects"][args.pool]["TC_WORKER_TYPE"]
        )
    update_state_observations(report, status_client.lt_username, observation_path=args.state_file)
    if args.json:
        report = {**report, "devices": select_devices(report, args.only_problems)}
        print(json.dumps(report, indent=2, sort_keys=True))
    elif args.ids_only:
        for device in select_devices(report, args.only_problems):
            print(device["udid"])
    else:
        use_color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())
        print_pool_report(report, only_problems=args.only_problems, color=use_color)


if __name__ == "__main__":  # pragma: no cover
    main()
