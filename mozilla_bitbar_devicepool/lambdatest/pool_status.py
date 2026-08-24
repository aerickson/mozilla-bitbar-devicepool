"""Cross-check the configured, LambdaTest, and Taskcluster views of a pool."""

import argparse
import datetime
import json
import os
import sys

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


def is_recent_taskcluster_activity(worker, now, recent_activity_minutes):
    """Whether Worker Manager observed this worker active within the configured window."""
    last_active = worker.get("lastDateActive")
    if not last_active:
        return False
    last_active_at = datetime.datetime.fromisoformat(last_active.replace("Z", "+00:00"))
    return now - last_active_at <= datetime.timedelta(minutes=recent_activity_minutes)


def build_pool_report(
    config, lt_device_list, tc_workers, running_jobs, pool_name, recent_activity_minutes=10, now=None
):
    """Join the three service views into a serializable per-device report."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
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
        recent_tc_activity = bool(worker and is_recent_taskcluster_activity(worker, now, recent_activity_minutes))
        finding = None
        severity = None
        if not lt_device:
            finding, severity = "missing_from_lambdatest", "warning"
        elif lt_state == "busy" and udid not in running_devices:
            if recent_tc_activity:
                finding, severity = "busy_without_lt_job_after_recent_tc_activity", "info"
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
                "recent_tc_activity": recent_tc_activity,
                "running_lt_job": udid in running_devices,
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


def print_pool_report(report, only_problems=False, color=False):
    """Render a compact, human-readable version of a pool report."""
    devices = report["devices"]
    if only_problems:
        # ``no_active_taskcluster_worker`` is informational because workers
        # may be short-lived, but it is still a non-OK state worth seeing in
        # a focused diagnostic report.
        devices = [device for device in devices if device["finding"]]

    print(f"Pool: {report['pool']} ({report['worker_type']})")
    print(
        f"Configured devices: {report['configured_device_count']}; "
        f"active Taskcluster workers: {report['taskcluster_worker_count']}"
    )
    rows = [
        (
            device["udid"],
            device["lt_state"],
            "missing" if device["tc_worker_state"] == "missing" else "ok",
            "running" if device["running_lt_job"] else "-",
            device["finding"] or "ok",
        )
        for device in devices
    ]
    headings = ("UDID", "LT state", "TC worker", "LT job", "finding")
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
        "--recent-tc-activity-minutes",
        type=int,
        default=10,
        help="Treat busy devices with TC activity this recent as informational (default: 10)",
    )
    parser.add_argument("--only-problems", action="store_true", help="Hide healthy rows")
    parser.add_argument("--json", action="store_true", help="Write the report as JSON")
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Color findings in terminal output (default: auto)",
    )
    args = parser.parse_args()
    if args.recent_tc_activity_minutes < 0:
        parser.error("--recent-tc-activity-minutes must be non-negative")

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

    report = build_pool_report(
        config,
        lt_device_list,
        workers,
        running_jobs,
        args.pool,
        recent_activity_minutes=args.recent_tc_activity_minutes,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        use_color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())
        print_pool_report(report, only_problems=args.only_problems, color=use_color)


if __name__ == "__main__":  # pragma: no cover
    main()
