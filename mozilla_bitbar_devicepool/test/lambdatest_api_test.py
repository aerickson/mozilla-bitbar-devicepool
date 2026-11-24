import requests

from mozilla_bitbar_devicepool.lambdatest import api


def job_page(mocker, *jobs):
    response = mocker.Mock(status_code=200)
    response.json.return_value = {"data": list(jobs)}
    return response


def test_jobs_stop_on_empty_first_page(mocker):
    fetch = mocker.patch.object(api.cached_session, "get", return_value=job_page(mocker))

    result = api.get_jobs("user", "key", allow_partial=True)

    assert result == {"data": [], "incomplete_reason": None}
    fetch.assert_called_once()


def test_jobs_stop_on_repeated_cursor_and_keep_unique_jobs(mocker):
    first_job = {"job_number": 42}
    last_job = {"job_number": 40}
    fetch = mocker.patch.object(
        api.cached_session,
        "get",
        side_effect=[job_page(mocker, first_job), job_page(mocker, last_job), job_page(mocker, last_job)],
    )

    result = api.get_jobs("user", "key", allow_partial=True)

    assert result["data"] == [first_job, last_job]
    assert result["incomplete_reason"] == "HyperExecute pagination cursor did not advance"
    assert [call.args[0].partition("&cursor=")[2] for call in fetch.call_args_list] == ["", "42", "40"]


def test_jobs_paginate_past_unmatched_labels_until_empty_page(mocker):
    match = {"job_number": 40, "job_label": ["wanted"]}
    fetch = mocker.patch.object(
        api.cached_session,
        "get",
        side_effect=[job_page(mocker, {"job_number": 42}), job_page(mocker, match), job_page(mocker)],
    )

    result = api.get_jobs("user", "key", label_filter_arr=["wanted"], allow_partial=True)

    assert result["data"] == [match]
    assert result["incomplete_reason"] is None
    assert [call.args[0].partition("&cursor=")[2] for call in fetch.call_args_list] == ["", "42", "40"]


def test_jobs_time_budget_is_shared_across_pages(mocker):
    first_job = {"job_number": 42}
    mocker.patch.object(api, "monotonic", side_effect=[0, 0, 8, 15])
    fetch = mocker.patch.object(
        api.bounded_jobs_session,
        "get",
        side_effect=[job_page(mocker, first_job), job_page(mocker, {"job_number": 40})],
    )

    result = api.get_jobs("user", "key", allow_partial=True, time_budget=15)

    assert result["data"] == [first_job, {"job_number": 40}]
    assert result["incomplete_reason"] == "time budget exhausted"
    assert [call.kwargs["timeout"].total for call in fetch.call_args_list] == [15, 7]
    assert api.bounded_jobs_session.get_adapter("https://").max_retries.total == 0


def test_jobs_keep_first_page_after_timeout(mocker):
    first_job = {"job_number": 42}
    mocker.patch.object(api.cached_session, "get", side_effect=[job_page(mocker, first_job), requests.ReadTimeout()])

    result = api.get_jobs("user", "key", allow_partial=True)

    assert result["data"] == [first_job]
    assert result["incomplete_reason"] == "request timed out"


def test_jobs_report_incomplete_coverage_at_job_limit(mocker):
    first_job = {"job_number": 42}
    mocker.patch.object(api.cached_session, "get", return_value=job_page(mocker, first_job))

    result = api.get_jobs("user", "key", jobs=1, allow_partial=True)

    assert result["data"] == [first_job]
    assert result["incomplete_reason"] == "reached the 1-job scan limit"
