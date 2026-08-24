# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import os
import pprint

# import datetime
from datetime import datetime

import requests
import taskcluster
from natsort import natsorted
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

ROOT_URL = "https://firefox-ci-tc.services.mozilla.com"


class TaskclusterClient:
    def __init__(self, verbose=False):
        self.verbose = verbose
        # self.queue = taskcluster.Queue()
        cfg = {"rootUrl": ROOT_URL}

        # load credentials
        data = {}
        if "TC_CLIENT_ID" in os.environ and "TC_ACCESS_TOKEN" in os.environ:
            if verbose:
                print("Using Taskcluster credentials from environment variables")
            # Load credentials from environment variables
            data = {"clientId": os.environ["TC_CLIENT_ID"], "accessToken": os.environ["TC_ACCESS_TOKEN"]}
        elif os.path.exists(os.path.expanduser("~/.tc_token")):
            if verbose:
                print("Using Taskcluster credentials from ~/.tc_token")
            # Load credentials from file
            with open(os.path.expanduser("~/.tc_token")) as json_file:
                data = json.load(json_file)
        else:
            # raise Exception("No Taskcluster credentials found in environment variables or ~/.tc_token")
            # allow anonymous access
            if verbose:
                print(
                    "No Taskcluster credentials found in environment variables or ~/.tc_token, using anonymous access."
                )
            data["clientId"] = "anonymous"
            data["accessToken"] = ""
        if verbose:
            # mention the clientid but not the access token
            print("Using Taskcluster clientId: %s" % data["clientId"])
        # set for later use
        self.tc_client_id = data["clientId"]

        creds = {"clientId": data["clientId"], "accessToken": data["accessToken"]}

        self.tc_wm = taskcluster.WorkerManager({"rootUrl": ROOT_URL, "credentials": creds})
        self.tc_queue = taskcluster.Queue({"rootUrl": ROOT_URL, "credentials": creds})
        self.tc_ai = taskcluster.Auth({"rootUrl": ROOT_URL, "credentials": creds})

    def get_quarantined_worker_names(self, provisioner, worker_type, results=None):
        if results is None:
            results = self.get_quarantined_workers(provisioner, worker_type)
        return_arr = []
        for result in results:
            return_arr.append(result["workerId"])
        # pprint.pprint(natsorted(return_arr))
        return natsorted(return_arr)

    def get_workers(self, provisioner, worker_type):
        """Return every active worker for a worker type.

        Worker Manager's ``listWorkers`` response is paginated.  Passing a
        pagination handler lets the Taskcluster client follow continuation
        tokens while keeping the rest of this package independent of the API
        response shape.
        """
        workers = []

        def add_page(page):
            workers.extend(page.get("workers", []))

        self.tc_wm.listWorkers(provisioner, worker_type, paginationHandler=add_page)
        return workers

    def get_worker_latest_task_activity(self, worker):
        """Return the latest task's resolved time, or start time while it runs."""
        latest_task = worker.get("latestTask") or {}
        task_id = latest_task.get("taskId")
        if not task_id:
            return None

        status = self.tc_queue.status(task_id).get("status", {})
        latest_run_id = latest_task.get("runId")
        run = next((run for run in status.get("runs", []) if run.get("runId") == latest_run_id), None)
        if not run:
            return None
        return run.get("resolved") or run.get("started")

    # TODO: implement retries like in outer function
    def get_pending_tasks(self, provisioner_id, worker_type):
        # results = self.tc_ai.currentScopes()
        # pprint.pprint(results)
        results = self.tc_queue.taskQueueCounts(f"{provisioner_id}/{worker_type}")
        return results.get("pendingTasks", 0)

    # TODO: implement retries like in outer function
    # uses a deprecated call
    def get_pending_tasks_old(self, provisioner_id, worker_type):
        # results = self.tc_ai.currentScopes()
        # pprint.pprint(results)
        results = self.tc_queue.pendingTasks(f"{provisioner_id}/{worker_type}")
        return results.get("pendingTasks", 0)

    def get_quarantined_workers(self, provisioner, worker_type, results=None):
        if results is None:
            results = self.get_workers(provisioner, worker_type)
        elif isinstance(results, dict):
            results = results.get("workers", [])
        # do filtering
        quarantined_workers = []
        for item in results:
            if self.verbose:
                pprint.pprint(item)
            # check if quarantineUntil is set and in the future
            if "quarantineUntil" in item:
                if item["quarantineUntil"] is None:
                    # if self.verbose:
                    #     print("Not quarantined: %s" % item["workerId"])
                    item["quarantined"] = False
                else:
                    # if self.verbose:
                    #     print("Quarantined: %s" % item["workerId"])

                    # cast date string to datetime object
                    dt = datetime.fromisoformat(item["quarantineUntil"].replace("Z", "+00:00"))

                    # check if date is in the future
                    if dt > taskcluster.utils.fromNow("0 hour"):
                        # print("Quarantined (date in future): %s" % item["workerId"])
                        item["quarantined"] = True
                        quarantined_workers.append(item)
                    else:
                        # print("Not quarantined (date in past): %s" % item["workerId"])
                        pass
            else:
                # if self.verbose:
                #     print("Not quarantined: %s" % item["workerId"])
                item["quarantined"] = False

        return quarantined_workers


# TODO: move to call in TaskclusterClient class
def get_taskcluster_pending_tasks(provisioner_id, worker_type, verbose=False):
    # define the retry strategy
    retry_strategy = Retry(
        total=4,  # maximum number of retries
        backoff_factor=2,
        status_forcelist=[
            429,
            500,
            502,
            503,
            504,
        ],  # the HTTP status codes to retry on
    )

    # create an HTTP adapter with the retry strategy and mount it to the session
    adapter = HTTPAdapter(max_retries=retry_strategy)

    # create a new session object
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    taskcluster_queue_url = "https://firefox-ci-tc.services.mozilla.com/api/queue/v1/pending/%s/%s" % (
        provisioner_id,
        worker_type,
    )
    if verbose:
        print("taskcluster_queue_url: %s" % taskcluster_queue_url)
    # Adding timeouts: 10 seconds to establish connection, 30 seconds to read response
    r = session.get(taskcluster_queue_url, timeout=(10, 30))
    if verbose:
        print("r.status_code: %s" % r.status_code)
        print("r.text: %s" % r.text if r.text else "r.content: %s" % r.content)
    if r.ok:
        return r.json()["pendingTasks"]
    return 0


# main
if __name__ == "__main__":  # pragma: no cover
    # setup logging
    logging.basicConfig(level=logging.INFO)
    # enable verbose logs if having issues
    # logging.basicConfig(level=logging.DEBUG)
    # logging.getLogger("taskcluster").setLevel(logging.DEBUG)

    tci = TaskclusterClient(verbose=False)
    provisioner_id = "proj-autophone"
    # worker_type = "t-lambda-a55-perf"
    worker_type = "gecko-t-lambda-perf-a55"

    print("TC Client id is: %s" % tci.tc_client_id)
    print(f"Current scopes: {pprint.pformat(tci.tc_ai.currentScopes())}")

    # pending tasks
    #
    # old
    pending_tasks = get_taskcluster_pending_tasks(provisioner_id, worker_type, verbose=True)
    print("Pending tasks: %s" % pending_tasks)
    # new
    pending_tasks = tci.get_pending_tasks(provisioner_id, worker_type)
    print("Pending tasks (new): %s" % pending_tasks)
    pending_tasks = tci.get_pending_tasks_old(provisioner_id, worker_type)
    print("Pending tasks (old): %s" % pending_tasks)

    print("")

    # quarantined workers
    quarantined_workers = tci.get_quarantined_worker_names(provisioner_id, worker_type)
    print("Number of quarantined workers: %s" % len(quarantined_workers))
    print(f"Quarantined workers: {pprint.pformat(quarantined_workers)}")
