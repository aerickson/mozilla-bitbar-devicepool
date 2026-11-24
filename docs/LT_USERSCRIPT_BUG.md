# LambdaTest userscript USB-device detection bug

Taskcluster task `Os68DNZ5QniJc0xTQkwXgg` emitted this message during setup:

```
TEST-UNEXPECTED-FAIL | lambdatest | Must have exactly one connected Android USB device. 0 found.
```

That diagnostic is incorrect for this run. `adbhost.devices()` reported two
devices, with ADB transport IDs `3` and `2`; one of the entries also had a USB
path (`"usb": "1-10.1"`). The userscript counted USB devices with:

```python
if int(device["transport_id"]) == 1:
    usb_device_count += 1
```

`transport_id` is an ADB-assigned, runtime-local identifier. It is neither a
transport kind nor guaranteed to begin at `1`. Consequently, neither device
was counted and the script reported zero devices.

The count should instead use the device's USB field (when present) or identify
the expected device by the configured `DEVICE_SERIAL`.

## Why setup continued

The `fatal()` helper only writes a `TEST-UNEXPECTED-FAIL` line. Its exit logic
is commented out, so the script continues after this false failure report.

## Actual task failure

Later in the same task, the expected device `RZCXC19G1DM` genuinely became
unavailable:

```
LIBUSB_ERROR_NO_DEVICE
adb error: device 'RZCXC19G1DM' not found
```

That subsequent disconnect, rather than the initial USB-count message, is what
prevented the Raptor run from starting.
