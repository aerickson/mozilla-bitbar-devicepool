# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import base64
import os
import pprint
from datetime import timedelta
from time import monotonic

import requests
import requests_cache
from urllib3.util import Retry, Timeout

# Create a cached session with 10 second expiry
# Only requests using this session will be cached
cached_session = requests_cache.CachedSession(
    cache_name="lambdatest_cache", backend="memory", expire_after=timedelta(seconds=8)
)

# Configure retry strategy
retry_strategy = Retry(
    total=5,
    backoff_factor=0.1,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET", "POST"],
)
adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
cached_session.mount("http://", adapter)
cached_session.mount("https://", adapter)
bounded_jobs_session = requests.Session()

# https://www.lambdatest.com/support/api-doc/


# WORKS
#   - must use is_cursor_base_pagination=true
#  curl -X GET "https://api.hyperexecute.cloud/v1.0/jobs?show_test_summary=false&is_cursor_base_pagination=true" -H  "accept: application/json" -H  "Authorization: Basic REDACTED" | jsonpp
#
# /v1.0/jobs
# timeout arg: 10 seconds to establish connection, 30 seconds to read response
def get_jobs(
    lt_username,
    lt_api_key,
    label_filter_arr=None,
    jobs=100,
    page_size=100,
    show_test_summary=False,
    timeout=(10, 30),
    status=None,
    print_url=False,
    *,
    allow_partial=False,
    time_budget=None,
):
    """Fetch unique jobs, optionally returning data and an incomplete_reason on a partial scan."""
    page_size = min(page_size, jobs)
    url_base = (
        "https://api.hyperexecute.cloud/v1.0/jobs"
        f"?show_test_summary={show_test_summary}"
        f"&is_cursor_base_pagination=true"
        f"&limit={page_size}"
    )

    # add status filter if provided
    if status:
        if isinstance(status, str):
            status = [status]
        status_filter = ",".join(status)
        url_base += f"&status={status_filter}"

    headers = {}
    auth_string = f"{lt_username}:{lt_api_key}"
    base64_auth_string = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
    headers["Authorization"] = f"Basic {base64_auth_string}"

    deadline = None if time_budget is None else monotonic() + time_budget
    all_jobs = []
    seen_jobs = set()
    seen_cursors = set()
    next_cursor = None
    result = {}
    incomplete_reason = None

    while len(all_jobs) < jobs:
        url = url_base
        if next_cursor is not None:
            url += f"&cursor={next_cursor}"

        if print_url:
            print(f"Fetching {url}...")
        try:
            if deadline is None:
                response = cached_session.get(url, headers=headers, timeout=timeout)
            else:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    incomplete_reason = "time budget exhausted"
                    break
                connect_timeout, read_timeout = timeout
                response = bounded_jobs_session.get(
                    url,
                    headers=headers,
                    timeout=Timeout(total=remaining, connect=connect_timeout, read=read_timeout),
                    allow_redirects=False,
                )
        except requests.RequestException as exc:
            if not allow_partial:
                raise
            incomplete_reason = "request timed out" if isinstance(exc, requests.Timeout) else "request failed"
            break
        if response.status_code != 200:
            if not allow_partial:
                print(f"Error: {response.status_code}")
                print(f"  while fetching {url}")
                print(response.text)
                return None
            incomplete_reason = f"HyperExecute returned HTTP {response.status_code}"
            break
        try:
            page = response.json()
        except requests.exceptions.JSONDecodeError:
            if not allow_partial:
                raise
            incomplete_reason = "HyperExecute returned invalid JSON"
            break

        jobs_data = page.get("data") if isinstance(page, dict) else None
        if not isinstance(jobs_data, list):
            incomplete_reason = "HyperExecute returned an invalid jobs page"
            break
        result = page
        if not jobs_data:
            break
        for job in jobs_data:
            job_number = job.get("job_number")
            if job_number is not None:
                if job_number in seen_jobs:
                    continue
                seen_jobs.add(job_number)
            if not label_filter_arr or all(label in (job.get("job_label") or []) for label in label_filter_arr):
                all_jobs.append(job)
        # A page with no matching labels can still advance pagination.
        next_cursor = jobs_data[-1].get("job_number")
        if next_cursor is None or next_cursor in seen_cursors:
            incomplete_reason = "HyperExecute pagination cursor did not advance"
            break
        seen_cursors.add(next_cursor)
    else:
        incomplete_reason = f"reached the {jobs}-job scan limit"

    result["data"] = all_jobs[:jobs]
    if allow_partial:
        result["incomplete_reason"] = incomplete_reason
    return result


# WORKS
# timeout arg: 10 seconds to establish connection, 30 seconds to read response
def get_devices(lt_username, lt_api_key, timeout=(10, 30), *, raise_on_error=False):
    # curl --location --request GET 'https://mobile-api.lambdatest.com/mobile-automation/api/v1/privatecloud_devices' -H  "Authorization: Basic REDACTED"

    url = "https://mobile-api.lambdatest.com/mobile-automation/api/v1/privatecloud_devices"

    # do basic auth
    headers = {"accept": "application/json"}
    # craft a header that does basic auth with username and api key
    auth_string = f"{lt_username}:{lt_api_key}"
    base64_auth_string = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
    headers["Authorization"] = f"Basic {base64_auth_string}"

    # Use cached_session instead of requests directly
    response = cached_session.get(url, headers=headers, timeout=timeout)
    # check the response code
    if response.status_code != 200:
        if raise_on_error:
            raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
        print(f"Error: {response.status_code}")
        print(f"  while fetching {url}")
        print(response.text)
        return None
    return response.json()  # list of jobs


if __name__ == "__main__":  # pragma: no cover
    lt_username = os.environ["LT_USERNAME"]
    lt_api_key = os.environ["LT_ACCESS_KEY"]

    # output = get_devices(lt_username, lt_api_key)
    # pprint.pprint(output)

    # show get_jobs() output
    output = get_jobs(lt_username, lt_api_key)
    pprint.pprint(output)

    import sys

    sys.exit(0)

    # jobs = get_jobs(lt_username, lt_api_key, ['aje_123', 'fun_fun_456'])
    # jobs = get_jobs(lt_username, lt_api_key, ["123", "456"])
    jobs = get_jobs(lt_username, lt_api_key, ["mbd"])
    pprint.pprint(jobs)

    # this code moved to status.py
    # job_result_dict = {}
    # for job in jobs['data']:
    #     # pprint.pprint(job)
    #     # print(f"{job["job_number"]} {job["status"]}")
    #     job_result_dict[job["job_number"]] = job["status"]
    # pprint.pprint(job_result_dict)
