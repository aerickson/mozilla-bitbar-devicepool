# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import datetime
import os
import pprint
import sys

import mozilla_bitbar_devicepool.lambdatest.util as util
from mozilla_bitbar_devicepool.lambdatest.api import get_devices, get_jobs

RUNNING_JOB_STATUS = "running"

# idea: uses api data to build a status/state
#   - a presentation layer for data from api.py


# TODO: make these constants and use them everywhere
# list of possible lt states:
# 'aborted': 0,
# 'cancelled': 0,
# 'completed': 0,
# 'created': 0,
# 'error': 0,
# 'failed': 0,
# 'ignored': 0,
# 'in_progress': 1,
# 'lambda_error': 0,
# 'log_available': 0,
# 'muted': 0,
# 'passed': 0,
# 'skipped': 0,
# 'stopped': 0,
# 'timeout': 0},


class Status:
    def __init__(self, lt_username, lt_api_key):
        self.lt_username = lt_username
        self.lt_api_key = lt_api_key

    # jobs

    def get_jobs(self, jobs=100):
        jobs = get_jobs(self.lt_username, self.lt_api_key, jobs=jobs)
        return jobs

    def get_job_dict(self, jobs=100):
        jobs = get_jobs(self.lt_username, self.lt_api_key, jobs=jobs)
        pprint.pprint(jobs)
        job_result_dict = {}
        for job in jobs["data"]:
            job_result_dict[job["job_number"]] = job["status"]
        # TODO?: return sorted?
        return job_result_dict

    # format:
    # {
    #   'running': 12,
    #   'aborted': 5,
    #   ...
    # }
    #
    # possible states:
    #  - initiated
    #  - running
    #  - completed
    #  - aborted
    #  - failed
    #  - timeout
    #
    def get_job_summary(self, label_filter_arr=None, jobs=100):
        # TODO: make label_filter work
        gj_output = get_jobs(
            self.lt_username,
            self.lt_api_key,
            label_filter_arr=label_filter_arr,
            jobs=jobs,
        )
        result_dict = {}
        for job in gj_output["data"]:
            status = job["status"]
            if status in result_dict:
                result_dict[status] += 1
            else:
                result_dict[status] = 1
        return result_dict

    # includes concurrent shards
    def get_initiated_job_count(self, label_filter_arr=None, jobs=100):
        # TODO: make label_filter work
        gj_output = get_jobs(
            self.lt_username,
            self.lt_api_key,
            label_filter_arr=label_filter_arr,
            jobs=jobs,
        )
        initiated_job_count = 0
        for job in gj_output["data"]:
            if job["status"] == "initiated":
                concurrency = int(job["Tasks"])
                if concurrency > 1:
                    # TODO: running calculates this based on the sub-tasks... should we also do here?
                    initiated_job_count += concurrency
                else:
                    initiated_job_count += 1
        return initiated_job_count

    # TODO: write this so we don't need get_initiated_job_count and get_running_job_count
    # def get_job_count(self, state_filter=None, label_filter=None, jobs=100):
    #     pass

    # includes concurrent shards
    def get_running_job_count(self, label_filter_arr=None, jobs=100):
        # TODO: make label_filter work
        gj_output = get_jobs(
            self.lt_username,
            self.lt_api_key,
            label_filter_arr=label_filter_arr,
            jobs=jobs,
        )
        running_job_count = 0
        for job in gj_output["data"]:
            # TODO: we need to check if the concurrent tasks are running, outer job could be runing but 4/5 jobs done!
            if job["status"] == "running":
                # print(job['id'])
                # print(job['job_label'])
                concurrency = int(job["Tasks"])
                # print(concurrency)
                if concurrency > 1:
                    # print("c")
                    # issue with this is that the tasks could have finished
                    # running_job_count += int(concurrency.split("=")[1])
                    running_job_count += int(
                        job["job_summary"]["scenario_stage_summary"]["status_counts_excluding_retries"]["in_progress"]
                    )
                else:
                    running_job_count += 1
        return running_job_count

    # TODO: find out which job is for which 'workerType' otherwise we can only run one workerType...
    #   - use job label? `--labels` arg to hyperexecute

    # devices

    # format:
    # {
    #   {'a55': {'RXYA1821': 'online',
    #            'RXYA1823': 'busy'
    #            'RXYA1824': 'online'},
    #   {'a51': {'DB123212': 'online'}
    # }
    def get_device_list(self, device_type_and_os_filter=None, verbose=False):
        result_dict = {}
        output = get_devices(self.lt_username, self.lt_api_key)
        if not output:
            return result_dict
        # if verbose:
        #     pprint.pprint(output)

        device_type = None
        device_os = None
        # TODO: sanity check this arg
        if device_type_and_os_filter:
            device_type = device_type_and_os_filter.split("-")[0]
            device_os = device_type_and_os_filter.split("-")[1]

        for device in output["data"]["private_cloud_devices"]:
            if verbose:
                pprint.pprint(device)
            # TODO: make the key include OS? 'fullOsVersion'
            # get the current value in result_dict['name'] or create a new dict
            device_type_entry = result_dict.get(device["name"], {})
            device_type_entry[device["udid"]] = device["status"]
            if device_type_and_os_filter:
                # pprint.pprint(device)
                # result_dict[device["name"]] = device_type_entry
                if device_type == device["name"] and device_os == device["fullOsVersion"]:
                    result_dict[device["name"]] = device_type_entry
            else:
                result_dict[device["name"]] = device_type_entry
        return result_dict

    def get_device_state_summary(self, device_type_and_os_filter=None):
        results = self.get_device_list(device_type_and_os_filter=device_type_and_os_filter)
        # results dict format: {state: count, ...}
        result_dict = {}
        for dev_type in results:
            for udid in results[dev_type]:
                # get or set the state
                state = results[dev_type][udid]
                if state in result_dict:
                    result_dict[state] += 1
                else:
                    result_dict[state] = 1
        return result_dict

    def get_device_state_summary_by_device(self):
        results = self.get_device_list()
        result_dict = {}
        for dev_type in results:
            for udid in results[dev_type]:
                # get or set the state
                state = results[dev_type][udid]
                if dev_type in result_dict and state in result_dict[dev_type]:
                    result_dict[dev_type][state] += 1
                elif dev_type in result_dict:
                    result_dict[dev_type][state] = 1
                else:
                    result_dict[dev_type] = {state: 1}
        return result_dict

    def get_device_state_count(self, device_type_and_os_filter, state):
        results = self.get_device_list(device_type_and_os_filter=device_type_and_os_filter)
        result_int = 0
        for dev_type in results:
            for udid in results[dev_type]:
                # get or set the state
                device_state = results[dev_type][udid]
                if device_state == state:
                    result_int += 1
        return result_int

    def get_busy_devices_without_running_jobs(self, jobs=100):
        """Return busy devices that are not labeled by a running HyperExecute job.

        LambdaTest's device API and the HyperExecute jobs API are separate views
        of the service.  A device reported as ``busy`` with no matching running
        job is a candidate for a stale LambdaTest allocation.
        """
        device_list = self.get_device_list()
        devices_by_udid = {
            udid: device_type
            for device_type, devices in device_list.items()
            for udid, state in devices.items()
            if state == "busy"
        }
        if not devices_by_udid:
            return []

        job_result = get_jobs(
            self.lt_username,
            self.lt_api_key,
            jobs=jobs,
            status=RUNNING_JOB_STATUS,
        )
        running_jobs = (job_result or {}).get("data", [])
        busy_udids = set(devices_by_udid)
        running_udids = {
            util.get_device_from_job_labels(util.string_list_to_list(job.get("job_label")), known_device_ids=busy_udids)
            for job in running_jobs
        }
        unmatched_udids = busy_udids - running_udids
        return [{"udid": udid, "device_type": devices_by_udid[udid]} for udid in sorted(unmatched_udids)]


def lt_status_main():
    import os

    lt_username = os.environ["LT_USERNAME"]
    lt_api_key = os.environ["LT_ACCESS_KEY"]

    status = Status(lt_username, lt_api_key)

    print("device list: ")
    pprint.pprint(status.get_device_list())
    print("")

    print("device summary by device:")
    pprint.pprint(status.get_device_state_summary_by_device())
    print("")

    print("device summary:")
    r = status.get_device_state_summary()
    pprint.pprint(r)

    print("")

    print("job summary:")
    pprint.pprint(status.get_job_summary())

    # Check if there are busy devices and no running jobs
    device_summary = status.get_device_state_summary()
    busy_device_count = device_summary.get("busy", 0)
    running_job_count = status.get_running_job_count()

    if busy_device_count > 0 and running_job_count == 0:
        # Collect UDIDs of busy devices
        device_list = status.get_device_list()
        busy_udids = []
        for dev_type in device_list:
            for udid, state in device_list[dev_type].items():
                if state == "busy":
                    busy_udids.append(f"{udid} ({dev_type})")

        print(
            "\n⚠️ WARNING: There are {0} busy devices but no running jobs. Devices may be stuck.".format(
                busy_device_count
            )
        )
        print("  Busy device UDIDs:")
        for udid in busy_udids:
            print(f"    - {udid}")


def lt_stuck_device_report():
    """Report LambdaTest devices allocated without a matching running job."""
    parser = argparse.ArgumentParser(
        description="Find LambdaTest devices marked busy without a matching running HyperExecute job."
    )
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=100,
        help="Maximum running jobs to inspect (default: 100)",
    )
    args = parser.parse_args()

    status = Status(os.environ["LT_USERNAME"], os.environ["LT_ACCESS_KEY"])
    stuck_devices = status.get_busy_devices_without_running_jobs(jobs=args.jobs)
    if not stuck_devices:
        print("No stuck LambdaTest devices found.")
        return

    print(f"Stuck LambdaTest devices ({len(stuck_devices)}):")
    print("  These are busy in the device API but have no matching running HyperExecute job.")
    for device in stuck_devices:
        print(f"  - {device['udid']} ({device['device_type']})")


# TODO: idea: report that gets percentage of failing/total jobs
def lt_success_rate_report():
    DEFAULT_JOBS = 100

    # use argparse to get the count of jobs to fetch
    parser = argparse.ArgumentParser(description="Generate a report on the success rate of jobs.")
    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=DEFAULT_JOBS,
        help=f"Number of jobs to fetch (default: {DEFAULT_JOBS})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        dest="verbose",
        default=False,
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()

    lt_username = os.environ["LT_USERNAME"]
    lt_api_key = os.environ["LT_ACCESS_KEY"]

    status = Status(lt_username, lt_api_key)

    # count success and failure jobs
    skipped_count = 0
    success_count = 0
    failure_count = 0
    running_count = 0
    completed_count = 0
    total_count = 0
    failure_phase_dict = {}
    # dict of lists, {'pre': ['device1', 'device2'], 'post': ['device3']}
    failure_phase_device_list_dict = {}

    start_times = []

    for job in get_jobs(lt_username, lt_api_key, jobs=args.jobs)["data"]:
        # Collect start_time for date range
        if "start_time" in job and job["start_time"]:
            try:
                # Try parsing as ISO 8601, fallback to int if needed
                if isinstance(job["start_time"], str):
                    start_times.append(datetime.datetime.fromisoformat(job["start_time"].replace("Z", "+00:00")))
                else:
                    # If it's a timestamp (int/float)
                    start_times.append(datetime.datetime.fromtimestamp(job["start_time"]))
            except Exception:
                pass

        job_labels_list = util.string_list_to_list(job["job_label"])
        device_id = util.get_device_from_job_labels(job_labels_list)

        # only inspect tcdp jobs
        if "tcdp" not in job_labels_list:
            skipped_count += 1
            continue

        if args.verbose:
            pprint.pprint(job)  # verbose output

        if job["status"] == "completed":
            success_count += 1
            completed_count += 1
        elif job["status"] == "timeout" or job["status"] == "failed":
            failure_count += 1
            completed_count += 1
            failure_phase = extract_failure_phase(job)
            failure_phase_dict[failure_phase] = failure_phase_dict.get(failure_phase, 0) + 1
            failure_phase_device_list_dict.setdefault(failure_phase, []).append(device_id)
        elif job["status"] == "running" or job["status"] == "initiated":
            # count initiated as running for now
            running_count += 1
        else:
            print(f"Unknown job status: {job['status']}")
            if args.verbose:
                pprint.pprint(job)
            continue
    total_count = completed_count + running_count + skipped_count

    # create a summary datastructure of failure_phase_device_list_dict with counts per device
    failure_phase_device_list_summary = {}
    for phase, device_list in failure_phase_device_list_dict.items():
        device_count = {}
        for device in device_list:
            if device in device_count:
                device_count[device] += 1
            else:
                device_count[device] = 1
        failure_phase_device_list_summary[phase] = device_count
    # order the summary by count descending
    for phase in failure_phase_device_list_summary:
        failure_phase_device_list_summary[phase] = dict(
            sorted(failure_phase_device_list_summary[phase].items(), key=lambda item: item[1], reverse=True)
        )

    # Compute date range string
    if start_times:
        min_time = min(start_times)
        max_time = max(start_times)
        date_range_string = f"{min_time.isoformat()} to {max_time.isoformat()}"
    else:
        date_range_string = "(no start_time data found)"

    print(f"Job Success Report:")
    print(f"  Total Jobs: {total_count}")
    print(f"    Job Date Range: {date_range_string}")
    print(f"    Skipped Jobs: {skipped_count}")
    print(f"    Running Jobs: {running_count}")
    print(f"    Completed Jobs: {completed_count}")
    print(f"      Successful Jobs: {success_count}")
    print(f"      Failed Jobs: {failure_count}")
    print(f"        Failure Phase Counts: {failure_phase_dict}")
    print(
        f"        Failure Phase Device Frequency: {pprint.pformat(failure_phase_device_list_summary, sort_dicts=False)}"
    )
    if success_count == 0:
        print(f"  Success Rate (success_count / completed_count): 0%")
    else:
        print(f"  Success Rate (success_count / completed_count): {success_count / completed_count * 100:.2f}%")


def extract_failure_phase(job):
    test_failure_phase = "testing"  # default phase
    # TODO: should we not have a default? should we raise in some cases?
    if "job_summary" in job and job["job_summary"] is not None:
        # print("job summary:")
        # pprint.pprint(job["job_summary"])
        if len(job["job_summary"]) == 0:
            print("job summary is empty")
            pprint.pprint(job)
            return test_failure_phase
        for phase, phase_details in job["job_summary"].items():
            # print(f"  - {phase}: {phase_details}")
            # pprint.pprint(phase_details)
            if phase_details and "failed" in phase_details and int(phase_details["failed"]) > 0:
                # print(f"    - {phase_details['name']}: {phase_details['status']}")
                # print(f"{phase}: failed zazaaz")
                test_failure_phase = phase.split("_")[0]
    else:
        print("job summary not in job or is None")
        pprint.pprint(job)
    return test_failure_phase


def lt_failed_job_report(verbose=True):
    DEFAULT_JOBS = 400

    # use argparse to get the count of jobs to fetch
    parser = argparse.ArgumentParser(description="Generate a report of failed jobs.")
    parser.add_argument(
        "--jobs",
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

    status = Status(lt_username, lt_api_key)

    # pprint.pprint(status.get_running_job_count())
    # sys.exit()

    # maintain a data structure tracking failure counts to devices
    device_failure_count = {}
    failure_phase_count = {}

    # pprint.pprint(status.get_jobs())
    for job in get_jobs(lt_username, lt_api_key, status="failed", jobs=args.jobs)["data"]:
        inspection_flag = False

        job_labels_list = util.string_list_to_list(job["job_label"])

        device_id = util.get_device_from_job_labels(job_labels_list)
        if device_id:
            # if verbose:
            #     print(f"device id: {device_id}")
            pass

        if job["status"] == "failed" and "tcdp" in job_labels_list:
            inspection_flag = True

        if inspection_flag == True:
            # raw debug output
            # pprint.pprint(job)

            # inspect job_summary
            test_failure_phase = "testing"
            if "job_summary" in job:
                # print("job summary:")
                # pprint.pprint(job["job_summary"])
                for phase, phase_details in job["job_summary"].items():
                    # print(f"  - {phase}: {phase_details}")
                    # pprint.pprint(phase_details)
                    if phase_details and "failed" in phase_details and int(phase_details["failed"]) > 0:
                        # print(f"    - {phase_details['name']}: {phase_details['status']}")
                        # print(f"{phase}: failed zazaaz")
                        test_failure_phase = phase.split("_")[0]
                failure_phase_count[test_failure_phase] = failure_phase_count.get(test_failure_phase, 0) + 1

            if device_id:
                # increment the failure count for this device
                if device_id in device_failure_count:
                    device_failure_count[device_id] += 1
                else:
                    device_failure_count[device_id] = 1

            if verbose:
                print(
                    f"job number: {job['job_number']}: device id: {device_id}: {job['status']}: test_failure_phase: {test_failure_phase}  "
                )

                # more advanced debugging output
                # print(f"job number: {job['job_number']}")
                # # print(f"status: {job['status']}")
                # print(f"job label: {job['job_label']} type: {type(job['job_label'])}")
                # print(f"test failure phase: {test_failure_phase}")
                # print("device udid: %s" % job["device_udid"])
                # print("device name: %s" % job["device_name"])
                # print("device os: %s" % job["device_os"])
                # print("device status: %s" % job["device_status"])
                # if job["status"] == "running":
                #     # pprint.pprint(job)
                #     # where number of currently running is for concurrent jobs
                #     # TODO: incorporate into functions above
                #     # print(job["job_summary"]["scenario_stage_summary"]["status_counts_excluding_retries"]["in_progress"])
                #     print(job["Tasks"])
                # print("")

    print("")
    print("Device failure counts:")
    if not device_failure_count:
        print("  No failed jobs found.")
    else:
        # sort by count descending
        device_failure_count = dict(sorted(device_failure_count.items(), key=lambda item: item[1], reverse=True))
        for device_id, count in device_failure_count.items():
            print(f"  {device_id}: {count} failures")

    print("")
    # show failure_phase_count
    print("Failure phase counts:")
    if not failure_phase_count:
        print("  No failed jobs found.")
    else:
        # sort by count descending
        failure_phase_count = dict(sorted(failure_phase_count.items(), key=lambda item: item[1], reverse=True))
        for phase, count in failure_phase_count.items():
            print(f"  {phase}: {count} failures")


if __name__ == "__main__":  # pragma: no cover
    import os
    import pprint
    import sys

    lt_username = os.environ["LT_USERNAME"]
    lt_api_key = os.environ["LT_ACCESS_KEY"]

    status = Status(lt_username, lt_api_key)

    # pprint.pprint(status.get_running_job_count())
    # sys.exit()

    # pprint.pprint(status.get_jobs())
    for job in status.get_jobs()["data"]:
        output_flag = False

        if job["status"] == "failed":
            output_flag = True

        if output_flag == True:
            # raw debug output
            pprint.pprint(job)

            # inspect job_summary
            # test_failure_phase = "testing"
            # if "job_summary" in job:
            #     # print("job summary:")
            #     # pprint.pprint(job["job_summary"])
            #     for phase, phase_details in job["job_summary"].items():
            #         print(f"  - {phase}: {phase_details}")
            #         # pprint.pprint(phase_details)
            #         if phase_details and "failed" in phase_details and int(phase_details["failed"]) > 0:
            #             # print(f"    - {phase_details['name']}: {phase_details['status']}")
            #             # print(f"{phase}: failed zazaaz")
            #             test_failure_phase = phase.split("_")[0]
            #     print(f"test failure phase: {test_failure_phase}")

            # more advanced debugging output
            # print(f"job number: {job['job_number']}")
            # print(f"status: {job['status']}")
            # print(f"job label: {job['job_label']}")
            # # print("device udid: %s" % job["device_udid"])
            # # print("device name: %s" % job["device_name"])
            # # print("device os: %s" % job["device_os"])
            # # print("device status: %s" % job["device_status"])
            # if job["status"] == "running":
            #     # pprint.pprint(job)
            #     # where number of currently running is for concurrent jobs
            #     # TODO: incorporate into functions above
            #     # print(job["job_summary"]["scenario_stage_summary"]["status_counts_excluding_retries"]["in_progress"])
            #     print(job["Tasks"])
            print("")
    print("")
    sys.exit()

    # print("device list: ")
    # pprint.pprint(status.get_device_list())
    # print("")

    # print("device summary by device:")
    # pprint.pprint(status.get_device_state_summary_by_device())
    # print("")

    # # r = status.get_device_list("Galaxy A55 5G-14")
    # print("device summary:")
    # # pprint.pprint(r)
    # r = status.get_device_state_summary()
    # # # r = status.get_device_state_summary("Galaxy A55 5G-14")
    # # r = status.get_device_state_summary("Galaxy A55 5G-14")
    # pprint.pprint(r)
    # # r = status.get_device_state_count("Galaxy A55 5G-14", "active")
    # # pprint.pprint(r)

    # # r = status.get_job_summary(["mbd"])
    # # pprint.pprint(r)

    # print("")

    # # pprint.pprint(status.get_job_dict())
    # # # print("")
    # # # sys.exit(0)
    # # print(f"initiated job count: {status.get_initiated_job_count()}")
    # print("job summary:")
    # pprint.pprint(status.get_job_summary())

    # # print("")

    # # print("device list:")
    # # pprint.pprint(status.get_device_list())

    # # sys.exit(0)
