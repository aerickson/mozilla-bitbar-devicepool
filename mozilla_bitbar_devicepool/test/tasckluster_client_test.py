import pytest

from mozilla_bitbar_devicepool.taskcluster_client import TaskclusterClient


@pytest.fixture
def client():
    return TaskclusterClient(verbose=False)


def test_get_quarantined_worker_names(client):
    # Injecting results directly to avoid api call mocking
    results = [
        {"workerId": "worker-2"},
        {"workerId": "worker-1"},
        {"workerId": "worker-3"},
    ]
    result = client.get_quarantined_worker_names("prov", "type", results=results)
    assert result == ["worker-1", "worker-2", "worker-3"]


def test_get_workers_collects_paginated_results(client):
    class FakeWorkerManager:
        def listWorkers(self, provisioner, worker_type, paginationHandler):
            assert (provisioner, worker_type) == ("prov", "type")
            paginationHandler({"workers": [{"workerId": "worker-1"}]})
            paginationHandler({"workers": [{"workerId": "worker-2"}]})

    client.tc_wm = FakeWorkerManager()

    assert client.get_workers("prov", "type") == [{"workerId": "worker-1"}, {"workerId": "worker-2"}]


def test_get_worker_latest_task_activity_prefers_resolved_time(client):
    class FakeQueue:
        def status(self, task_id):
            assert task_id == "task-id"
            return {
                "status": {
                    "runs": [
                        {"runId": 0, "started": "2026-08-24T21:45:00Z"},
                        {
                            "runId": 1,
                            "started": "2026-08-24T21:50:00Z",
                            "resolved": "2026-08-24T21:55:00Z",
                        },
                    ]
                }
            }

    client.tc_queue = FakeQueue()

    assert client.get_worker_latest_task_activity({"latestTask": {"taskId": "task-id", "runId": 1}}) == (
        "2026-08-24T21:55:00Z"
    )


def test_get_quarantined_workers(client):
    # Injecting results directly to avoid api call mocking
    results = {
        "workers": [
            {"workerId": "worker-1", "quarantineUntil": None},
            {"workerId": "worker-2", "quarantineUntil": "2099-01-01T00:00:00Z"},
            {"workerId": "worker-3"},
            {"workerId": "worker-4", "quarantineUntil": "2099-01-01T00:00:00Z"},
        ]
    }
    result = client.get_quarantined_workers("prov", "type", results=results)
    assert [w["workerId"] for w in result] == ["worker-2", "worker-4"]
    for w in result:
        assert w["quarantined"]
