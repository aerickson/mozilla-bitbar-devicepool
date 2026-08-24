# Power Meter Failure: cdc_acm Kernel Driver Conflict

## Summary

AVHzy CT-3 USB power meters (VID:PID `0483:fffe`) are failing intermittently
because the Linux `cdc_acm` kernel module automatically claims the device's USB
interfaces before `usb-power-profiling` can open them, resulting in `EBUSY`
([Errno 16] Resource busy).

## Background

`usb-power-profiling` communicates with the AVHzy CT-3 ("Shizuku") device via
**USB bulk endpoints** using libusb — it does **not** use the serial port
(`/dev/ttyUSB*` or `/dev/ttyACM*`).

The AVHzy CT-3 presents itself as a USB CDC-ACM device (USB Communications
Device Class). Linux automatically loads the `cdc_acm` kernel module for any
CDC-ACM device, which claims all interfaces and creates `/dev/ttyACM*` entries.
This happens at device plug-in time, before any userspace process runs.

## Observed Symptoms

- TC perf jobs fail to get power data from the meter
- On the host machine: 8 power meters visible via `lsusb`, 11 `/dev/ttyACM*`
  devices present
- `usb-power-profiling` (or its python3 wrapper) gets `[Errno 16] Resource busy`
  when calling `libusb_set_configuration()` or `libusb_claim_interface()`
- Both interface 0 and interface 1 show `kernel driver ATTACHED` via
  `libusb_kernel_driver_active()`
- Sometimes a stale `python3` process from a previous TC job is also holding
  the device file open, compounding the problem

## Root Cause

The `cdc_acm` driver claims the device at boot/plug-in. libusb cannot claim
an interface that a kernel driver already owns without first calling
`libusb_detach_kernel_driver()` (pyusb: `dev.detach_kernel_driver(n)`).

If `usb-power-profiling` is not calling `detachKernelDriver()` (or the
equivalent `usb.detachKernelDriver()` in the `usb` npm package) before
`libusb_claim_interface()`, it will always get `EBUSY` on hosts where
`cdc_acm` has loaded.

## Possible Bug in usb-power-profiling

The `usb` npm package (which `usb-power-profiling` uses) supports kernel driver
detachment via `interface.detachKernelDriverAsync()` or by setting
`useLibUSBKernelDriver: false`. If this is not called before
`claimInterface()`, the result is `LIBUSB_ERROR_BUSY` on Linux hosts where
`cdc_acm` is loaded.

The `usb-power-profiling` `startSampling()` implementation for Shizuku devices
calls `findBulkInOutEndPoints()` and then `endPointIn.startPoll()`. If
`claimInterface()` is not preceded by `detachKernelDriver()`, this will fail
silently or throw on Linux.

**Possible fix in usb-power-profiling:** before `claimInterface()` in the
Shizuku `startSampling()`, add:

```javascript
if (process.platform === 'linux') {
  try {
    interface.detachKernelDriver();
  } catch (e) {
    // already detached or not supported
  }
}
interface.claim();
```

## Contributing Factor: Stale python3 Processes

On some hosts a `python3` process from a previous TC job is also holding the
USB device file open (visible via `lsof /dev/bus/usb/001/NNN`). This process
needs to be killed before `detach_kernel_driver()` will succeed. This suggests
the previous job's `usb-power-profiling` process did not exit cleanly.

## Affected Devices

Hosts running multiple power meters (8 per host observed) with `cdc_acm`
loaded — all a55-perf and p9-perf devices using AVHzy CT-3 meters.

## Why Some Devices Work Despite cdc_acm

If `cdc_acm` always claims the interfaces, why do some TC jobs succeed?

**Race condition via `resetDevice()`:** `usb-power-profiling` calls `resetDevice()`
as the first step in `startSampling()`. A USB reset causes the kernel to unbind
all drivers briefly during re-enumeration. If `usb-power-profiling` claims the
interface before `cdc_acm` re-binds, it wins. Whether it wins depends on system
load and timing — explaining the intermittent nature of failures.

**`cdc_acm` doesn't always claim both interfaces:** Observed data shows `cdc_acm`
holding interface 0 (CDC control) but not always interface 1 (CDC data, where
the bulk endpoints live). If `usb-power-profiling` skips `set_configuration()`
and goes straight to claiming interface 1, it may succeed without detaching
anything. Our diagnostic calls `set_configuration()` which fails if *any*
interface is claimed — `usb-power-profiling` may avoid that call.

**`autoDetachKernelDriver` in the `usb` npm package:** Newer versions of the
`usb` npm package support an `autoDetachKernelDriver` option that transparently
calls `detachKernelDriver()` before `claimInterface()`. If this is set in the
vendored version, some devices would just work automatically.

## Fix Durability

`detach_kernel_driver()` releases the kernel's claim **for the current open
session only**. It does not prevent `cdc_acm` from re-binding. When the
libusb handle is closed (i.e. the job's Python/Node process exits), the kernel
re-attaches `cdc_acm` to the interfaces. The next container starts fresh with
`cdc_acm` owning the device again.

This is confirmed by every run of the diagnostic script showing
`interface 0: kernel driver ATTACHED` at the start, even immediately after a
prior run successfully detached it.

**Detach must therefore run on every job invocation** — it is not a one-time
fix.

### Durable fix options (persist across container restarts)

| Option | Where applied | Notes |
|--------|--------------|-------|
| udev rule preventing `cdc_acm` from binding to `0483:fffe` | LambdaTest host image | Best option; requires LambdaTest to apply |
| Blacklist `cdc_acm` entirely on the host | LambdaTest host image | Breaks any other legitimate CDC-ACM devices |
| Call `detachKernelDriver()` in `usb-power-profiling` before `claimInterface()` | Firefox repo / npm package | No host changes needed; self-heals every job |

Option 3 (fix `usb-power-profiling`) is the most practical path since it
requires no changes to LambdaTest infrastructure and fixes the problem at the
source.

## Workaround

In the TC setup script (`setup_script.sh`), before launching the TC worker,
detach `cdc_acm` from all power meter interfaces:

```bash
for dev in /dev/ttyACM*; do
    # find the sysfs USB device for this ttyACM
    # unbind cdc_acm so libusb can claim the interfaces
done
```

Or via udev rule to prevent `cdc_acm` from binding to VID:PID `0483:fffe`:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="fffe", \
  ENV{ID_USB_DRIVER}="none"
```
