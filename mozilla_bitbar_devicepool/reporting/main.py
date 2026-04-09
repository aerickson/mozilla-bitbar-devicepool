# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import datetime
import os
import pprint
import sys

import mozilla_bitbar_devicepool.lambdatest.status as status
import mozilla_bitbar_devicepool.lambdatest.util as util
from mozilla_bitbar_devicepool.configuration_lt import ConfigurationLt
from mozilla_bitbar_devicepool.lambdatest.api import get_devices, get_jobs
from mozilla_bitbar_devicepool.taskcluster_client import TaskclusterClient


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
    all_devices = si.get_device_list()
    import pprint

    # pprint.pprint(all_devices)
    api_udid_list = []
    for dev_type in all_devices:
        for udid in all_devices[dev_type]:
            api_udid_list.append(udid)
    # pprint.pprint(udid_list)
    # print(len(api_udid_list))

    # TODO: load quarantine data from api

    # store the device and a count of jobs run on it
    device_job_count = {}
    # store failures also
    device_failure_count = {}
    jobs_inspected = 0

    # TODO: separate calculation and display logic

    for job in get_jobs(lt_username, lt_api_key, jobs=args.jobs)["data"]:
        job_labels_list = util.string_list_to_list(job["job_label"])

        device_id = util.get_device_from_job_labels(job_labels_list)
        if device_id:
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
        jobs_inspected += 1

    print("")
    print("Device job counts:")
    if not device_job_count:
        print("  No jobs found.")
    else:
        # sort by count descending
        device_job_count = dict(sorted(device_job_count.items(), key=lambda item: item[1], reverse=True))
        for device_id, count in device_job_count.items():
            failure_count = device_failure_count.get(device_id, 0)
            print(f"  {device_id}: {count} jobs, {failure_count} failures")

        # show a total count of seen devices
    print("")

    unseen_devices = set(api_udid_list) - set(device_job_count.keys())
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
        for device_id in sorted(not_seen_non_quarantined_devices):
            group = udid_to_group.get(device_id, "unknown")
            print(f"  {device_id} (lt api: {udid_to_state.get(device_id, 'unknown')}) ({group})")

    print("")

    print("Jobs inspected: ", jobs_inspected)
    # TODO: show how many devices found via api
    print(f"Total devices available (from LT devices): {len(udid_to_state)}")
    print(f"Total devices seen (from LT jobs): {len(device_job_count)}")
    end_time = datetime.datetime.now()
    print("Report generation time: ", end_time - start_time)
