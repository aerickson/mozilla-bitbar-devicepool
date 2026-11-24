# Why Power Meter Failures Are Less Common at Other Vendors

## Context

We use AVHzy CT-3 USB power meters (VID:PID `0483:fffe`) at multiple mobile
device testing vendors, both of which run tests inside Docker containers. The
`cdc_acm` kernel driver conflict (see `power-meter-cdc-acm-issue.md`) causes
frequent failures at LambdaTest but is rarely seen at other vendors. Below are
the likely reasons.

## Likely Explanations

### 1. Different kernel / module configuration on the host

LambdaTest host machines have `cdc_acm` loaded (proven by 11 `/dev/ttyACM*`
entries appearing on every job). Other vendors' host machines may have
`cdc_acm` blacklisted or not compiled into the kernel at all, meaning the
module never loads and never claims the power meter interfaces.

### 2. udev rules preventing the bind

Other vendors may have a host-level udev rule that prevents `cdc_acm` from
binding to this specific VID:PID, e.g.:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="fffe", \
  ENV{ID_MM_DEVICE_IGNORE}="1"
```

LambdaTest hosts have no such rule, so `cdc_acm` claims the interfaces on
every device plug-in or container start.

### 3. Fewer power meters per host / less contention

At LambdaTest we observe 8 power meters per physical host, with multiple
Docker containers sharing the same USB bus. This creates contention: stale
`python3` processes from concurrent or previous jobs accumulate and hold device
files open. At other vendors the ratio may be closer to 1 meter per host or
per container, so contention and stale-process buildup don't occur.

### 4. Docker USB passthrough method

How the USB device is passed into the container affects whether the host's
`cdc_acm` claim is visible inside:

- **Bind-mount of `/dev/bus/usb`**: the container sees the host's USB bus
  directly, including all kernel driver bindings. This is what LambdaTest
  appears to do.
- **Specific device node via `--device`**: similar effect — host `cdc_acm`
  claim still applies.
- **USB/IP or pre-unbind on the host**: if the other vendor explicitly unbinds
  `cdc_acm` on the host before passing the device to the container, the
  container receives a clean device with no kernel driver attached.

### 5. Persistent containers vs. fresh-per-job containers

LambdaTest spins up a **fresh Docker container for every HyperExecute job**.
This means:

- `cdc_acm` re-claims the interfaces at container start (before
  `usb-power-profiling` runs)
- Any handle `usb-power-profiling` held in the previous container is gone, but
  the kernel driver binding on the host persists

At other vendors, containers may be **longer-lived**, with `usb-power-profiling`
starting once and holding the device handle continuously. `cdc_acm` never gets
a chance to reclaim the interfaces between jobs.

## Summary Table

| Factor | LambdaTest | Other Vendor |
|--------|-----------|--------------|
| `cdc_acm` loaded on host | Yes (11 ttyACM devices seen) | Likely no, or blacklisted |
| udev rule for `0483:fffe` | No | Possibly yes |
| Power meters per host | ~8, shared across containers | Fewer, less contention |
| USB passthrough method | Bind-mount (host driver applies) | Possibly pre-unbound |
| Container lifetime | Fresh per job | Possibly persistent |

## Recommended Fix for LambdaTest

The most robust fix is a **udev rule on the LambdaTest host** that prevents
`cdc_acm` from binding to AVHzy CT-3 devices:

```
# /etc/udev/rules.d/99-avhzy-power-meter.rules
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="fffe", \
  ENV{ID_MM_DEVICE_IGNORE}="1", ENV{MTP_NO_PROBE}="1"
```

Or explicitly unbinding `cdc_acm` for this VID:PID:

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0483", ATTRS{idProduct}=="fffe", \
  RUN+="/bin/sh -c 'echo -n %k > /sys/bus/usb/drivers/cdc_acm/unbind'"
```

This would need to be applied by LambdaTest to their host images.
