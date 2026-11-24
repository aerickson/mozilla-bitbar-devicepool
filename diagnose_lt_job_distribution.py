#!/usr/bin/env python3

"""Diagnose how lt_job_distribution_report attributes jobs to a device."""

import argparse
import json
import os
from pathlib import Path

from mozilla_bitbar_devicepool.lambdatest.api import get_jobs
from mozilla_bitbar_devicepool.lambdatest.util import get_device_from_job_labels, string_list_to_list

DEFAULT_TARGET = "RZCY107MCLV"
DEFAULT_FETCH_COUNT = 5000
DEFAULT_REPORT_WINDOW = 1200
DEFAULT_SCREENSHOT_JOBS = {"533321", "533104", "532938", "532904", "532887", "532725"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=DEFAULT_TARGET, help="Device UDID to find in LambdaTest job labels")
    parser.add_argument("--jobs", type=int, default=DEFAULT_FETCH_COUNT, help="Number of recent jobs to fetch")
    parser.add_argument(
        "--report-window",
        type=int,
        default=DEFAULT_REPORT_WINDOW,
        help="Job count used by the distribution report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("rzcy107mclv-diagnostic.json"),
        help="Path for the sanitized JSON output",
    )
    args = parser.parse_args()

    try:
        username = os.environ["LT_USERNAME"]
        access_key = os.environ["LT_ACCESS_KEY"]
    except KeyError as error:
        raise SystemExit(f"Missing {error.args[0]}; run: source ./lt_env.sh") from error

    result = get_jobs(username, access_key, jobs=args.jobs)
    if result is None:
        raise SystemExit("LambdaTest job API request failed")

    jobs = result.get("data", [])
    matches = []

    for rank, job in enumerate(jobs, start=1):
        labels = string_list_to_list(job.get("job_label"))
        job_number = str(job.get("job_number"))

        if args.target in labels or job_number in DEFAULT_SCREENSHOT_JOBS:
            matches.append(
                {
                    "rank_in_api_results": rank,
                    "inside_report_window": rank <= args.report_window,
                    "job_number": job_number,
                    "status": job.get("status"),
                    "raw_job_label": job.get("job_label"),
                    "parsed_labels": labels,
                    "device_selected_by_report": get_device_from_job_labels(labels),
                    "created_at": job.get("created_at"),
                    "start_time": job.get("start_time"),
                }
            )

    output = {
        "target": args.target,
        "jobs_requested": args.jobs,
        "jobs_returned": len(jobs),
        "report_window": args.report_window,
        "first_job_number": jobs[0].get("job_number") if jobs else None,
        "last_job_number": jobs[-1].get("job_number") if jobs else None,
        "matches": matches,
    }

    args.output.write_text(json.dumps(output, indent=2, default=str) + "\n")
    print(f"Wrote {args.output.resolve()} with {len(matches)} matching jobs")


if __name__ == "__main__":
    main()
