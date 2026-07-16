# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import datetime
import hashlib
import json
import math
import os
from collections import defaultdict
from html import escape
from pathlib import Path

import mozilla_bitbar_devicepool.lambdatest.status as status
import mozilla_bitbar_devicepool.lambdatest.util as util
from mozilla_bitbar_devicepool.configuration_lt import ConfigurationLt
from mozilla_bitbar_devicepool.lambdatest.api import get_jobs
from mozilla_bitbar_devicepool.taskcluster_client import TaskclusterClient

JOB_CACHE_MAX_AGE = datetime.timedelta(hours=1)
SVG_SUCCESS_COLOR = "#2563eb"
SVG_FAILURE_COLOR = "#dc2626"


def _format_bytes(size):
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}"
        size /= 1024


def _format_age(age):
    seconds = max(0, int(age.total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {seconds % 3600 // 60}m"


def _job_cache_path(lt_username):
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    account_id = hashlib.sha256(lt_username.encode()).hexdigest()[:12]
    return cache_root / "mozilla-bitbar-devicepool" / f"lt-job-distribution-{account_id}.json"


def _write_job_cache(cache_path, jobs, fetched_at):
    cached_jobs = [{key: job.get(key) for key in ("job_number", "job_label", "status")} for job in jobs]
    cache_data = {"fetched_at": fetched_at.isoformat(), "jobs": cached_jobs}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache_data))
    cache_path.chmod(0o600)


def get_report_jobs(lt_username, lt_api_key, job_count, refresh=False, cache_path=None, now=None):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cache_path = cache_path or _job_cache_path(lt_username)

    if cache_path.exists() and not refresh:
        cache_data = json.loads(cache_path.read_text())
        fetched_at = datetime.datetime.fromisoformat(cache_data["fetched_at"])
        age = now - fetched_at
        cached_jobs = cache_data.get("jobs", [])
        print(
            f"Job cache: {len(cached_jobs)} jobs, {_format_bytes(cache_path.stat().st_size)}, {_format_age(age)} old."
        )

        if age <= JOB_CACHE_MAX_AGE:
            if len(cached_jobs) < job_count:
                raise SystemExit(
                    f"Cache has {len(cached_jobs)} jobs, but {job_count} were requested. "
                    f"Rerun with --refresh to fetch and cache {job_count} jobs."
                )
            print(f"Using {job_count} jobs from the cache. Use --refresh to fetch fresh data.")
            return cached_jobs[:job_count]

        print("Job cache is older than 1 hour; fetching fresh data.")

    result = get_jobs(lt_username, lt_api_key, jobs=job_count)
    if result is None:
        raise SystemExit("Unable to fetch jobs from LambdaTest.")
    jobs = result.get("data", [])
    _write_job_cache(cache_path, jobs, now)
    print(f"Fetched and cached {len(jobs)} jobs ({_format_bytes(cache_path.stat().st_size)}).")
    return jobs


def write_device_job_counts_svg(
    output_path,
    device_job_count,
    device_failure_count,
    pool=None,
    jobs_inspected=None,
    jobs_matching_pool=None,
):
    output_path = Path(output_path)
    width = 1100
    label_width = 190
    chart_width = 700
    top = 110
    row_height = 30
    bottom = 55
    height = max(220, top + len(device_job_count) * row_height + bottom)

    max_count = max(device_job_count.values(), default=1)
    tick_step = max(1, math.ceil(max_count / 5))
    axis_max = tick_step * math.ceil(max_count / tick_step)
    title = "Device job distribution"
    if pool:
        title += f" — {pool} pool"
    if pool and jobs_matching_pool is not None and jobs_inspected is not None:
        subtitle = f"{jobs_matching_pool:,} {pool} jobs from {jobs_inspected:,} recent jobs inspected"
    else:
        subtitle = f"{jobs_inspected:,} recent jobs inspected" if jobs_inspected is not None else ""

    svg = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        f'  <title id="title">{escape(title)}</title>',
        f'  <desc id="description">{escape(subtitle)}. Blue bars are successful jobs; red bars are failures.</desc>',
        "  <style>",
        "    text { font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; fill: #172033; }",
        "    .title { font-size: 24px; font-weight: 700; }",
        "    .subtitle, .tick, .legend { font-size: 13px; fill: #5b6474; }",
        "    .device { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }",
        "    .count { font-size: 13px; font-weight: 600; }",
        "    .grid { stroke: #dce1e8; stroke-width: 1; }",
        "  </style>",
        '  <rect width="100%" height="100%" fill="#ffffff"/>',
        f'  <text class="title" x="30" y="38">{escape(title)}</text>',
        f'  <text class="subtitle" x="30" y="62">{escape(subtitle)}</text>',
        f'  <rect x="{label_width}" y="76" width="14" height="14" rx="2" fill="{SVG_SUCCESS_COLOR}"/>',
        f'  <text class="legend" x="{label_width + 20}" y="88">successful</text>',
        f'  <rect x="{label_width + 105}" y="76" width="14" height="14" rx="2" fill="{SVG_FAILURE_COLOR}"/>',
        f'  <text class="legend" x="{label_width + 125}" y="88">failed</text>',
    ]

    for tick in range(0, axis_max + 1, tick_step):
        x = label_width + chart_width * tick / axis_max
        svg.append(f'  <line class="grid" x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{height - bottom}"/>')
        svg.append(f'  <text class="tick" x="{x:.1f}" y="{top - 14}" text-anchor="middle">{tick}</text>')

    for index, (device_id, count) in enumerate(device_job_count.items()):
        failure_count = min(device_failure_count.get(device_id, 0), count)
        success_count = count - failure_count
        y = top + index * row_height
        success_width = chart_width * success_count / axis_max
        failure_width = chart_width * failure_count / axis_max
        svg.append(
            f'  <text class="device" x="{label_width - 12}" y="{y + 17}" text-anchor="end">{escape(device_id)}</text>'
        )
        svg.append(
            f'  <rect x="{label_width}" y="{y + 3}" width="{success_width:.1f}" height="19" '
            f'rx="3" fill="{SVG_SUCCESS_COLOR}"/>'
        )
        if failure_count:
            svg.append(
                f'  <rect x="{label_width + success_width:.1f}" y="{y + 3}" width="{failure_width:.1f}" '
                f'height="19" rx="3" fill="{SVG_FAILURE_COLOR}"/>'
            )
        count_label = f"{count} jobs"
        if failure_count:
            count_label += f", {failure_count} failed"
        svg.append(
            f'  <text class="count" x="{label_width + chart_width + 12}" y="{y + 17}">{escape(count_label)}</text>'
        )

    if not device_job_count:
        svg.append(f'  <text class="subtitle" x="{label_width}" y="{top + 30}">No matching device jobs.</text>')

    svg.append("</svg>")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(svg) + "\n")


# inspects x jobs, and presents a report of job distribution across devices
def job_distribution_report(verbose=True):
    start_time = datetime.datetime.now()
    DEFAULT_JOBS = 400

    # use argparse to get the count of jobs to fetch
    parser = argparse.ArgumentParser(description="Generate a report of failed jobs.")
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=DEFAULT_JOBS,
        help=f"Number of jobs to fetch (default: {DEFAULT_JOBS})",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch fresh job data and replace the one-hour cache",
    )
    parser.add_argument(
        "--pool",
        help="Limit device counts and unseen-device analysis to jobs labeled for this configured pool",
    )
    parser.add_argument(
        "--current-members-only",
        action="store_true",
        help="With --pool, exclude jobs run by devices that are no longer configured in that pool",
    )
    parser.add_argument(
        "--svg",
        nargs="?",
        const=Path("device-job-counts.svg"),
        type=Path,
        metavar="PATH",
        help="Write the displayed device job counts as an SVG bar chart",
    )
    args = parser.parse_args()

    lt_username = os.environ["LT_USERNAME"]
    lt_api_key = os.environ["LT_ACCESS_KEY"]

    config_object = ConfigurationLt(ci_mode_envvars=True, quiet=True)
    config_object.configure()
    udid_to_group = {}
    for group_name, devices in config_object.config.get("device_groups", {}).items():
        if devices:
            for udid in devices:
                udid_to_group[udid] = group_name

    #
    si = status.Status(lt_username, lt_api_key)
    lt_device_list = si.get_device_list()
    udid_to_state = {}
    for device_type in lt_device_list:
        # print(device_type)
        for device in lt_device_list[device_type]:
            # print(device)
            # print(lt_device_list[device_type][device])
            # print(device["udid"], device["status"])
            udid_to_state[device] = lt_device_list[device_type][device]
    # print(udid_to_state)
    # sys.exit(0)
    #
    tci = TaskclusterClient(verbose=False)
    provisioner_id = "proj-autophone"
    worker_type = "gecko-t-lambda-perf-a55"
    quarantined_workers = tci.get_quarantined_worker_names(provisioner_id, worker_type)

    # get a list of all available devices from the API, used later
    api_udid_list = list(udid_to_state)
    api_udids = set(api_udid_list)
    config_groups = list(config_object.config.get("device_groups", {}).keys())
    config_group_set = set(config_groups)
    if args.pool and args.pool not in config_group_set:
        parser.error(f"unknown pool {args.pool!r}; choose from: {', '.join(config_groups)}")
    if args.current_members_only and not args.pool:
        parser.error("--current-members-only requires --pool")
    selected_pool_devices = set(config_object.config["device_groups"].get(args.pool) or []) if args.pool else set()

    # TODO: load quarantine data from api

    # store the device and a count of jobs run on it
    device_job_count = {}
    # store failures also
    device_failure_count = {}
    pool_job_count = defaultdict(int)
    pool_failure_count = defaultdict(int)
    pool_devices = defaultdict(set)
    pool_config_mismatch_count = defaultdict(int)
    jobs_inspected = 0
    jobs_matching_pool = 0
    jobs_excluded_non_current_devices = 0
    jobs_counted_by_device = 0

    # TODO: separate calculation and display logic

    jobs = get_report_jobs(lt_username, lt_api_key, args.jobs, refresh=args.refresh)
    for job in jobs:
        job_labels_list = util.string_list_to_list(job["job_label"])

        device_id = util.get_device_from_job_labels(job_labels_list, known_device_ids=api_udids)
        pool = util.get_pool_from_job_labels(job_labels_list, config_group_set)
        pool_job_count[pool] += 1
        if job["status"] == "failed":
            pool_failure_count[pool] += 1

        jobs_inspected += 1
        if args.pool and pool != args.pool:
            continue

        jobs_matching_pool += 1
        if args.current_members_only and device_id and device_id not in selected_pool_devices:
            jobs_excluded_non_current_devices += 1
            continue

        if device_id:
            jobs_counted_by_device += 1
            pool_devices[pool].add(device_id)
            configured_pool = udid_to_group.get(device_id)
            if configured_pool and pool != "unknown" and configured_pool != pool:
                pool_config_mismatch_count[(device_id, pool, configured_pool)] += 1

            # increment the job count for this device
            if device_id in device_job_count:
                device_job_count[device_id] += 1
            else:
                device_job_count[device_id] = 1

            # if the job failed, increment the failure count for this device
            if job["status"] == "failed":
                if device_id in device_failure_count:
                    device_failure_count[device_id] += 1
                else:
                    device_failure_count[device_id] = 1
    print("")
    print("Pool job counts (from job labels):")
    if args.pool:
        ordered_pools = [args.pool]
    else:
        ordered_pools = [pool for pool in config_groups if pool in pool_job_count]
        if "unknown" in pool_job_count:
            ordered_pools.append("unknown")
    for pool in ordered_pools:
        print(
            f"  {pool}: {pool_job_count[pool]} jobs, {pool_failure_count[pool]} failures, "
            f"{len(pool_devices[pool])} devices"
        )
    print("")

    print("Pool label/current-config differences (informational):")
    print("  Historical jobs may differ after devices move between pools.")
    if not pool_config_mismatch_count:
        print("  No differences found.")
    else:
        for (device_id, label_pool, configured_pool), count in sorted(
            pool_config_mismatch_count.items(), key=lambda item: (-item[1], item[0])
        ):
            print(f"  {device_id}: {count} jobs labeled {label_pool}, currently configured in {configured_pool}")
    print("")

    if args.current_members_only:
        device_count_heading = f"Device job counts (current {args.pool} pool members):"
    elif args.pool:
        device_count_heading = f"Device job counts ({args.pool} pool):"
    else:
        device_count_heading = "Device job counts:"
    print(device_count_heading)
    if not device_job_count:
        pool_suffix = f" for pool {args.pool}" if args.pool else ""
        print(f"  No jobs found{pool_suffix}.")
    else:
        # sort by count descending
        device_job_count = dict(sorted(device_job_count.items(), key=lambda item: item[1], reverse=True))
        for device_id, count in device_job_count.items():
            failure_count = device_failure_count.get(device_id, 0)
            print(f"  {device_id}: {count} jobs, {failure_count} failures")

        # show a total count of seen devices
    print("")

    if args.svg:
        write_device_job_counts_svg(
            args.svg,
            device_job_count,
            device_failure_count,
            pool=args.pool,
            jobs_inspected=jobs_inspected,
            jobs_matching_pool=jobs_counted_by_device,
        )
        print(f"SVG report: {args.svg.resolve()}")
        print("")

    if args.pool:
        available_devices = api_udids & selected_pool_devices
    else:
        available_devices = api_udids
    unseen_devices = available_devices - set(device_job_count.keys())
    if args.verbose:
        # TODO: show devices not working (from config or via available devices? use avaiable devices for now)
        print(f"Devices with no jobs run ({len(unseen_devices)} devices):")
        if not unseen_devices:
            print("  All devices have jobs run on them.")
        else:
            for device_id in sorted(unseen_devices):
                print(f"  {device_id}")
        print("")

    # TODO: for these devices show their lt_api status
    not_seen_non_quarantined_devices = unseen_devices - set(quarantined_workers)
    print(f"Devices not seen that aren't quarantined ({len(not_seen_non_quarantined_devices)} devices):")
    if not not_seen_non_quarantined_devices:
        print("  All unseen devices are quarantined.")
    else:
        # Group by config group, preserving config order; unknown devices go last
        by_group = {}
        for device_id in not_seen_non_quarantined_devices:
            group = udid_to_group.get(device_id, "unknown")
            by_group.setdefault(group, []).append(device_id)
        ordered_groups = [g for g in config_groups if g in by_group]
        if "unknown" in by_group:
            ordered_groups.append("unknown")
        for group in ordered_groups:
            print(f"  {group}")
            for device_id in sorted(by_group[group]):
                print(f"    {device_id} (lt api: {udid_to_state.get(device_id, 'unknown')})")

    print("")

    print("Jobs inspected: ", jobs_inspected)
    if args.pool:
        print(f"Jobs matching pool {args.pool}: {jobs_matching_pool}")
        if args.current_members_only:
            print(f"Jobs excluded from former pool members: {jobs_excluded_non_current_devices}")
        print(f"Total devices currently available in pool {args.pool}: {len(available_devices)}")
        print(f"Total devices seen in {args.pool} jobs: {len(device_job_count)}")
    else:
        print(f"Total devices available (from LT devices): {len(udid_to_state)}")
        print(f"Total devices seen (from LT jobs): {len(device_job_count)}")
    end_time = datetime.datetime.now()
    print("Report generation time: ", end_time - start_time)
