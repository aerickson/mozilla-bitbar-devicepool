# LambdaTest Power Meter Isolation Proposal

## Summary

LambdaTest proposed changing USB passthrough for Mozilla power-meter hosts from
a full `/dev/bus/usb` bind mount to per-container USB device isolation.

Today each Mozilla container sees the host's entire USB bus. On hosts with
roughly 8 phones and 8 AVHzy CT-3 power meters, each container can see every
meter. `usb-power-profiling` then has to discover its target among all visible
meters, and failures on one container can affect meters assigned to other
containers.

The proposed fix is to give each container a private `/dev/bus/usb` containing
only the two USB device nodes assigned to that job:

- the assigned Android phone
- the assigned AVHzy CT-3 power meter

This should remove cross-container power-meter contention and prevent a job from
touching unassigned meters.

## Vendor Proposal

At container start, LambdaTest creates a per-container directory on the host.
That directory contains character device nodes for only the assigned phone and
assigned power meter, using the current host major/minor values.

The per-container directory is then bind-mounted into the container as
`/dev/bus/usb`, replacing the current wholesale host bind mount:

```text
/dev/bus/usb:/dev/bus/usb
```

When the assigned phone or power meter is replugged and the kernel gives it a
new USB bus/address, a host udev rule updates the corresponding device node in
the container-specific directory. The intent is that the container continues to
see the assigned device without needing a Docker restart.

## Expected Benefit

This should address the multi-device contention problem described in
`power-meter-vendor-comparison.md`:

- each container sees exactly one AVHzy meter instead of all meters on the host
- `usb-power-profiling` auto-discovery should only find the assigned meter
- unassigned meters should be unreachable from the container
- control transfers from one job should not reach other jobs' meters
- stale or misbehaving tooling in one container should have less opportunity to
  disturb other meters

If this works, Mozilla may not need to change `usb-power-profiling` discovery
logic for the multi-meter case.

## Remaining Concern: `cdc_acm`

This proposal is promising, but it does not by itself prove that the original
`cdc_acm` failure mode is fixed.

The root cause documented in `power-meter-cdc-acm-issue.md` is that the Linux
host's `cdc_acm` driver can claim the AVHzy CT-3 USB interfaces before
`usb-power-profiling` opens them. When that happens, libusb can fail with
`EBUSY` / `[Errno 16] Resource busy` during `libusb_set_configuration()` or
`libusb_claim_interface()`.

A private `/dev/bus/usb` directory changes which device nodes are visible in
the container. It does not necessarily change which kernel driver owns the
assigned meter's interfaces on the host. A mknod'd device entry still points at
the same host USB device and the same host kernel binding.

So the vendor POC results are encouraging but incomplete if they only prove:

- the assigned meter is visible
- its USB descriptor can be read
- other meters are not visible
- mknod entries update after replug

Reading a USB descriptor is weaker than the real requirement. The important
operation is whether `usb-power-profiling` can claim the assigned meter's bulk
interface reliably while the host is running with all phones and meters
attached.

## Acceptance Test

Before signing off, LambdaTest should validate this on a realistic host with 8
phones and 8 AVHzy CT-3 power meters attached.

Run 8 concurrent Mozilla-style jobs, one per phone/meter pair, using the
proposed private `/dev/bus/usb` mount.

Pass criteria:

- each container sees exactly one assigned Android phone
- each container sees exactly one AVHzy CT-3 meter (`0483:fffe`, or the
  relevant AVHzy product ID)
- no container can open another job's meter path
- `usb-power-profiling` starts sampling successfully in all 8 jobs
- no job reports `EBUSY`, `[Errno 16] Resource busy`, or
  `LIBUSB_ERROR_BUSY`
- the assigned meter's bulk interface can be claimed, not just enumerated
- replugging an assigned meter updates the private device node and sampling can
  resume without restarting the container
- repeated container restarts do not reintroduce the failure

Useful diagnostics to capture from inside each container before sampling:

```text
lsusb
ls -la /dev/bus/usb
ls -la /dev/ttyACM* /dev/ttyUSB*
libusb_kernel_driver_active() for each interface on the assigned meter
```

Useful diagnostics to capture during sampling:

```text
successful libusb_claim_interface() result
assigned meter bus/address and serial number
usb-power-profiling logs
any EBUSY / LIBUSB_ERROR_BUSY / Resource busy errors
```

## Questions for LambdaTest

- Does the host udev rule only refresh mknod entries, or does it also prevent
  or unbind `cdc_acm` for AVHzy CT-3 devices?
- After a power-meter replug, is `cdc_acm` attached to either interface before
  Mozilla tooling starts sampling?
- Does the POC validate `libusb_claim_interface()` on the assigned meter, or
  only descriptor reads?
- What cleanup prevents stale processes from holding the assigned meter's device
  node after a failed or cancelled job?

## Current Position

The proposal is a good isolation fix and likely addresses the contention storm
caused by exposing all meters to every container.

Mozilla should treat it as accepted only after a realistic 8-phone/8-meter
concurrency test shows that the power-meter failures go away in practice,
including the libusb interface-claim path used by `usb-power-profiling`.
