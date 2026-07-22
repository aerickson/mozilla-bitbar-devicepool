import os
import sys
from unittest.mock import patch

import pytest

from mozilla_bitbar_devicepool.lambdatest import status as status_module
from mozilla_bitbar_devicepool.lambdatest.status import Status


# Sample mock data
@pytest.fixture
def mock_jobs_data():
    # load this from a file (test_data/lt_get_jobs_1.txt) and use it
    this_file_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(this_file_dir, "test_data", "lt_get_jobs_shortened.txt")
    with open(data_path) as f:
        # evaluate it as a dict and return it
        return eval(f.read())


@pytest.fixture
def mock_jobs_data_with_initiated():
    # load this from a file (test_data/lt_get_jobs_1.txt) and use it
    this_file_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(this_file_dir, "test_data", "lt_get_jobs_2.txt")
    with open(data_path) as f:
        # evaluate it as a dict and return it
        return eval(f.read())


@pytest.fixture
def mock_devices_data():
    this_file_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(this_file_dir, "test_data", "lt_get_devices_1.txt")
    with open(data_path) as f:
        return eval(f.read())


@pytest.fixture
def status_instance():
    return Status("test_user", "test_key")


class TestStatus:
    def test_init(self):
        status = Status("test_user", "test_key")
        assert status.lt_username == "test_user"
        assert status.lt_api_key == "test_key"

    # verify the mock is working basically
    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    def test_get_jobs(self, mock_get_jobs, status_instance, mock_jobs_data):
        mock_get_jobs.return_value = mock_jobs_data
        result = status_instance.get_jobs(jobs=50)
        mock_get_jobs.assert_called_once_with("test_user", "test_key", jobs=50)
        assert result == mock_jobs_data

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    def test_get_job_dict(self, mock_get_jobs, status_instance, mock_jobs_data):
        mock_get_jobs.return_value = mock_jobs_data
        result = status_instance.get_job_dict(jobs=50)
        mock_get_jobs.assert_called_once_with("test_user", "test_key", jobs=50)
        expected = {
            9821: "running",
            9816: "completed",
            9812: "failed",
            9813: "completed",
            9815: "running",
            9775: "aborted",
            9790: "lambda_error",
            9766: "timeout",
        }
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    def test_get_job_summary(self, mock_get_jobs, status_instance, mock_jobs_data):
        mock_get_jobs.return_value = mock_jobs_data
        result = status_instance.get_job_summary(jobs=50)
        mock_get_jobs.assert_called_once_with("test_user", "test_key", label_filter_arr=None, jobs=50)
        expected = {"running": 2, "completed": 2, "failed": 1, "aborted": 1, "lambda_error": 1, "timeout": 1}
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    def test_get_initiated_job_count(self, mock_get_jobs, status_instance, mock_jobs_data_with_initiated):
        mock_get_jobs.return_value = mock_jobs_data_with_initiated
        result = status_instance.get_initiated_job_count(jobs=50)
        mock_get_jobs.assert_called_once_with("test_user", "test_key", label_filter_arr=None, jobs=50)
        # The initiated job has Tasks=3
        assert result == 2

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    def test_get_running_job_count(self, mock_get_jobs, status_instance, mock_jobs_data):
        mock_get_jobs.return_value = mock_jobs_data
        result = status_instance.get_running_job_count(jobs=50)
        mock_get_jobs.assert_called_once_with("test_user", "test_key", label_filter_arr=None, jobs=50)
        # One running job with Tasks=1 and one with Tasks=2 but only 1 in_progress
        assert result == 2

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_list(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_list()
        mock_get_devices.assert_called_once_with("test_user", "test_key")
        expected = {
            "Galaxy A51": {"RZ8NB0WJ47H": "active"},
            "Galaxy A55 5G": {
                "RZCXA0H3T9P": "active",
                "R5CY128X71B": "active",
                "R5CXC1AP2KT": "active",
                "R5CXC1AMMNK": "active",
                "R5CXC1ANGLT": "active",
                "R5CXC1ASA0L": "active",
                "R5CXC1ASLHH": "active",
                "RZCX821GXDJ": "active",
                "RZCY10LGB6W": "active",
                "RZCY10Y4HWD": "active",
                "RZCY10Y4QVX": "active",
                "RZCY10Y4TAV": "active",
                "RZCY10Y4TBY": "active",
                "RZCY10Y4TJX": "active",
                "RZCY10Y548K": "active",
                "R5CXC1AHV4M": "active",
                "R5CXC1ALFED": "active",
                "R5CXC1ARCER": "active",
                "R5CXC1ARELR": "active",
                "R5CX4089QNL": "active",
                "R5CXC1AMNFY": "active",
                "R5CY21T22NH": "active",
                "RZCX31FDGJE": "active",
                "RZCX50TW03H": "active",
                "RZCX71ZVF6J": "active",
                "RZCY204AAZD": "active",
                "R5CXC1ASA3P": "busy",
                "R5CXC1HZKLR": "busy",
                "RZCY2011M7N": "busy",
                "RZCY203N75Z": "busy",
                "R5CXC1ARM0A": "busy",
                "R5CXC1ASA2E": "busy",
                "R5CXC1HZK0W": "busy",
                "RZCX821GYPX": "faulty",
            },
        }
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_list_with_filter(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_list(device_type_and_os_filter="Galaxy A55 5G-14")
        mock_get_devices.assert_called_once_with("test_user", "test_key")
        expected = {
            "Galaxy A55 5G": {
                "RZCXA0H3T9P": "active",
                "R5CY128X71B": "active",
                "R5CXC1AP2KT": "active",
                "R5CXC1AMMNK": "active",
                "R5CXC1ANGLT": "active",
                "R5CXC1ASA0L": "active",
                "R5CXC1ASLHH": "active",
                "RZCX821GXDJ": "active",
                "RZCY10LGB6W": "active",
                "RZCY10Y4HWD": "active",
                "RZCY10Y4QVX": "active",
                "RZCY10Y4TAV": "active",
                "RZCY10Y4TBY": "active",
                "RZCY10Y4TJX": "active",
                "RZCY10Y548K": "active",
                "R5CXC1AHV4M": "active",
                "R5CXC1ALFED": "active",
                "R5CXC1ARCER": "active",
                "R5CXC1ARELR": "active",
                "R5CX4089QNL": "active",
                "R5CXC1AMNFY": "active",
                "R5CY21T22NH": "active",
                "RZCX31FDGJE": "active",
                "RZCX50TW03H": "active",
                "RZCX71ZVF6J": "active",
                "RZCY204AAZD": "active",
                "R5CXC1ASA3P": "busy",
                "R5CXC1HZKLR": "busy",
                "RZCY2011M7N": "busy",
                "RZCY203N75Z": "busy",
                "R5CXC1ARM0A": "busy",
                "R5CXC1ASA2E": "busy",
                "R5CXC1HZK0W": "busy",
                "RZCX821GYPX": "faulty",
            }
        }
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_state_summary(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_state_summary()
        expected = {"active": 27, "busy": 7, "faulty": 1}
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_state_summary_with_filter(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_state_summary(device_type_and_os_filter="Galaxy A55 5G-14")
        expected = {"active": 26, "busy": 7, "faulty": 1}
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_state_summary_by_device(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_state_summary_by_device()
        expected = {"Galaxy A51": {"active": 1}, "Galaxy A55 5G": {"active": 26, "busy": 7, "faulty": 1}}
        assert result == expected

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_device_state_count(self, mock_get_devices, status_instance, mock_devices_data):
        mock_get_devices.return_value = mock_devices_data
        result = status_instance.get_device_state_count("Galaxy A55 5G-14", "online")
        assert result == 0

        result = status_instance.get_device_state_count("Galaxy A55 5G-14", "busy")
        assert result == 7

        # Test with a non-existent state
        result = status_instance.get_device_state_count("Galaxy A55 5G-14", "offline")
        assert result == 0

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_jobs")
    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_get_busy_devices_without_running_jobs(self, mock_get_devices, mock_get_jobs, status_instance):
        mock_get_devices.return_value = {
            "data": {
                "private_cloud_devices": [
                    {"name": "Galaxy A55 5G", "udid": "busy-with-job", "status": "busy"},
                    {"name": "Galaxy A55 5G", "udid": "stuck-device", "status": "busy"},
                    {"name": "Galaxy A55 5G", "udid": "available-device", "status": "active"},
                ]
            }
        }
        mock_get_jobs.return_value = {
            "data": [
                {"job_label": '["tcdp", "pool", "busy-with-job"]'},
                {"job_label": '["tcdp", "pool", "available-device"]'},
            ]
        }

        result = status_instance.get_busy_devices_without_running_jobs(jobs=25)

        assert result == [{"udid": "stuck-device", "device_type": "Galaxy A55 5G"}]
        mock_get_jobs.assert_called_once_with("test_user", "test_key", jobs=25, status="running")

    def test_lt_stuck_device_report(self, monkeypatch, capsys):
        class FakeStatus:
            def __init__(self, username, api_key):
                assert (username, api_key) == ("test_user", "test_key")

            def get_busy_devices_without_running_jobs(self, jobs):
                assert jobs == 25
                return [{"udid": "stuck-device", "device_type": "Galaxy A55 5G"}]

        monkeypatch.setenv("LT_USERNAME", "test_user")
        monkeypatch.setenv("LT_ACCESS_KEY", "test_key")
        monkeypatch.setattr(sys, "argv", ["lt_stuck_device_report", "--jobs", "25"])
        monkeypatch.setattr(status_module, "Status", FakeStatus)

        status_module.lt_stuck_device_report()

        output = capsys.readouterr().out
        assert "Stuck LambdaTest devices (1):" in output
        assert "stuck-device (Galaxy A55 5G)" in output

    @patch("mozilla_bitbar_devicepool.lambdatest.status.get_devices")
    def test_empty_response(self, mock_get_devices, status_instance):
        mock_get_devices.return_value = None
        result = status_instance.get_device_list()
        assert result == {}
