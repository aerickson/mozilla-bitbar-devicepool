from unittest.mock import patch

import pytest

from mozilla_bitbar_devicepool.lambdatest import device_availability


@pytest.fixture
def device_response():
    return {
        "data": {
            "private_cloud_devices": [
                {"udid": "RZCXC19G1DM", "name": "Galaxy A55 5G", "status": "active"},
                {"udid": "RZCXC19G1DN", "name": "Galaxy A55 5G", "status": "busy"},
                {"udid": "RZ8NB0WJ47H", "name": "Galaxy A51", "status": "faulty"},
            ]
        }
    }


@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.get_devices")
def test_get_requested_devices_by_udid(mock_get_devices, device_response):
    mock_get_devices.return_value = device_response

    devices = device_availability.get_requested_devices(["RZCXC19G1DM"], "user", "key")

    assert devices == [device_response["data"]["private_cloud_devices"][0]]
    mock_get_devices.assert_called_once_with("user", "key")


@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.get_devices")
def test_get_requested_devices_by_model_name(mock_get_devices, device_response):
    mock_get_devices.return_value = device_response

    devices = device_availability.get_requested_devices(["Galaxy A55 5G"], "user", "key")

    assert [device["udid"] for device in devices] == ["RZCXC19G1DM", "RZCXC19G1DN"]


@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.get_devices")
def test_get_requested_devices_rejects_missing_identifier(mock_get_devices, device_response):
    mock_get_devices.return_value = device_response

    with pytest.raises(ValueError, match="MISSING"):
        device_availability.get_requested_devices(["MISSING"], "user", "key")


def test_print_device_statuses(capsys):
    all_available = device_availability.print_device_statuses(
        [
            {"udid": "one", "name": "Phone One", "status": "active"},
            {"udid": "two", "name": "Phone Two", "status": "busy"},
        ]
    )

    assert capsys.readouterr().out == "one\tPhone One\tactive\ntwo\tPhone Two\tbusy\n"
    assert not all_available


@patch.dict("os.environ", {"LT_USERNAME": "user", "LT_ACCESS_KEY": "key"})
@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.get_requested_devices")
def test_main_status_mode_exits_after_one_check(mock_get_requested_devices):
    mock_get_requested_devices.return_value = [{"udid": "one", "name": "Phone", "status": "busy"}]

    assert device_availability.main(["one"]) == 0
    mock_get_requested_devices.assert_called_once_with(["one"], "user", "key")


@patch.dict("os.environ", {"LT_USERNAME": "user", "LT_ACCESS_KEY": "key"})
@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.time.sleep")
@patch("mozilla_bitbar_devicepool.lambdatest.device_availability.get_requested_devices")
def test_main_waits_until_every_device_is_active(mock_get_requested_devices, mock_sleep):
    mock_get_requested_devices.side_effect = [
        [{"udid": "one", "name": "Phone", "status": "busy"}],
        [{"udid": "one", "name": "Phone", "status": "active"}],
    ]

    assert device_availability.main(["one", "--wait", "--interval", "2"]) == 0
    assert mock_get_requested_devices.call_count == 2
    mock_sleep.assert_called_once_with(2)
