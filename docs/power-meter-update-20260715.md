# Power Meter Isolation Update — 2026-07-15

## Summary

LambdaTest enabled a USB-isolation change on one host containing eight Mozilla
Android devices and eight AVHzy CT-3 power meters. Each task container is
intended to receive only two usable USB device nodes:

- the assigned Android phone
- the assigned AVHzy CT-3 power meter

Testing confirms that the isolation is working at the `/dev/bus/usb` device-node
layer. However, host-wide USB devices remain visible through enumeration, and
the separate `cdc_acm` kernel-driver conflict can still prevent access to the
assigned meter.

## Devices in the Initial Rollout

LambdaTest identified these devices as ready for testing:

- `R5CXC1ARZDN`
- `R5CXC1HZ43J`
- `R5CXC1HZ85W`
- `R5CXC1HZA6V`
- `R5CXC1SXMVR`
- `RZCXC19G1DM`
- `RZCXC1BK67D`
- `RZCY107MCLV`

## Observed Container Layout

Task `rk7gYSuvRkW0xc_A5LPScw`, which ran on `R5CXC1ARZDN`, directly listed
the character devices under `/dev/bus/usb`:

```text
/dev/bus/usb/001/017  # assigned AVHzy power meter
/dev/bus/usb/001/100  # assigned Samsung phone
```

This matches LambdaTest's claim that the container receives exactly two usable
USB device nodes.

The same container's `lsusb` output and PyUSB discovery still enumerated all
eight AVHzy meters on the physical host. This appears to happen because the
container retains host-wide USB visibility through sysfs even though only the
assigned phone and meter have usable character-device nodes under
`/dev/bus/usb`.

The other seven meters are therefore visible during discovery but cannot be
opened. Attempts to use one of those entries can fail with:

```text
usb.core.USBError: [Errno 19] No such device
```

The isolation is best described as **two usable USB devices per container**, not
two enumerated USB devices per container.

## Device Selection

The diagnostic must continue selecting the assigned meter using
`PowerMeterSerial` or `USB_POWER_METER_SERIAL_NUMBER`. Selecting the first
device returned by `usb.core.find()` is unsafe because the host-wide discovery
results include inaccessible meters.

With serial-based selection, task `rk7gYSuvRkW0xc_A5LPScw` selected the meter
at `/dev/bus/usb/001/017`, opened its bulk endpoints, received a sample frame,
and passed.

## Remaining `cdc_acm` Problem

Per-container device-node isolation should prevent other containers and stale
processes from opening the assigned meter. It does not prevent the physical
host's `cdc_acm` kernel driver from binding to that meter's USB interfaces.

Task `vp9_sf51Qzurr1UnXKBJFA` selected its assigned meter by serial number but
failed during `libusb_set_configuration()` with:

```text
usb.core.USBError: [Errno 16] Resource busy
```

Another task succeeded without explicit recovery, showing that this remains an
intermittent binding race. USB isolation may improve the pass rate by removing
cross-container contention, but reliable operation still requires preventing
`cdc_acm` from binding or detaching it before libusb claims the interface.

## Recommended Host udev Rule

Ask LambdaTest to install a host-level udev rule that immediately unbinds
`cdc_acm` from AVHzy CT-3 USB interfaces. The rule must run on the physical host,
not inside task containers.

```udev
# /etc/udev/rules.d/99-avhzy-power-meter.rules
ACTION=="add|bind", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_interface", DRIVER=="cdc_acm", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="fffe", RUN+="/bin/sh -c 'echo -n %k > /sys/bus/usb/drivers/cdc_acm/unbind'"
```

Reload the rules and replug the meters:

```bash
sudo udevadm control --reload-rules
```

If AVHzy meters using product IDs `ffff` or `374b` are deployed, add equivalent
rules for those product IDs.

The rule intentionally unbinds the USB **interface** identified by `%k`, rather
than the parent USB device. Unbinding the parent device can disconnect it from
USB core and should be avoided.

`ID_MM_DEVICE_IGNORE=1` is not required for this fix. That property controls
ModemManager behavior; it does not prevent the kernel's `cdc_acm` driver from
binding.

## Rollout Acceptance Criteria

Before rollout to the remaining hosts, run eight concurrent jobs on the initial
host and verify:

- each container has exactly two character-device nodes under `/dev/bus/usb`
- the two nodes correspond to the assigned phone and power meter
- serial-based discovery selects the assigned meter
- inaccessible host-wide discovery entries cannot be opened
- all eight jobs can claim the meter's bulk interface and receive samples
- no job reports `EBUSY`, `LIBUSB_ERROR_BUSY`, or `Resource busy`
- meter replug updates the private device node without a container restart
- repeated job and container restarts remain reliable

## Task Evidence

- Isolation and sampling pass:
  <https://firefox-ci-tc.services.mozilla.com/tasks/rk7gYSuvRkW0xc_A5LPScw/runs/0/logs/public/logs/live.log>
- Serial selection followed by `EBUSY`:
  <https://firefox-ci-tc.services.mozilla.com/tasks/vp9_sf51Qzurr1UnXKBJFA/runs/0/logs/public/logs/live.log>
- Inaccessible discovery entry (`Errno 19`):
  <https://firefox-ci-tc.services.mozilla.com/tasks/C2BVRnX3SHa0zQvyE0kALw/runs/0/logs/public/logs/live.log>
