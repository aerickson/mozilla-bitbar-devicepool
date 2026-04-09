import script

json_blob_1 = [
    {
        "device_serial": "R5CXC1ASA3P",
        "state": "device",
        "usb": "1-4.3.2",
        "product": "a55xnsxx",
        "model": "SM_A556E",
        "device": "a55x",
        "transport_id": "1",
    }
]

json_blob_2 = [
    {
        "device_serial": "R5CXC1ASA3P",
        "state": "device",
        "usb": "1-4.3.2",
        "product": "a55xnsxx",
        "model": "SM_A556E",
        "device": "a55x",
        "transport_id": "1",
    },
    {
        "device_serial": "10.146.5.232:5555",
        "state": "device",
        "product": "a55xnsxx",
        "model": "SM_A556E",
        "device": "a55x",
        "transport_id": "2",
    },
]


def test_get_usb_device_count():
    assert script.get_usb_device_count(json_blob_1) == 1
    assert script.get_usb_device_count(json_blob_2) == 1
    assert script.get_usb_device_count([]) == 0
