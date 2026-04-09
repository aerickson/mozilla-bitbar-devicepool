#!/bin/bash
# Diagnostic script for AVHzy CT-3 USB power meter (B098TQLYYN)
#
# Runs on the LT HOST machine via run_cmd_lt --script.
# Does NOT require a connected Android device.
#
# USB_POWER_METER_SERIAL_NUMBER must match the USB serial number descriptor
# of the power meter (set from PowerMeterSerial -> USB_POWER_METER_SERIAL_NUMBER
# in entrypoint.py, consumed by usb-power-profiling via dev.serialNumber).
#
# The AVHzy CT-3 (Shizuku) communicates via USB BULK ENDPOINTS (libusb),
# NOT /dev/ttyUSB*. VID:PID is 0483:fffe/ffff/374b (STMicro).
#
# Usage:
#   run_cmd_lt --script scripts/check_power_meter.sh --group a55-perf
#   run_cmd_lt --script scripts/check_power_meter.sh --device <UDID>

set -o pipefail

# Bare HyperExecute jobs don't run entrypoint.py, so USB_POWER_METER_SERIAL_NUMBER
# is never set. Use PowerMeterSerial directly (same value, different env var name).
SERIAL="${PowerMeterSerial:-${USB_POWER_METER_SERIAL_NUMBER:-}}"

echo "=== AVHzy CT-3 Power Meter Diagnostic ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "User: $(id)"
echo "PowerMeterSerial: ${PowerMeterSerial:-(not set)}"
echo "USB_POWER_METER_SERIAL_NUMBER: ${USB_POWER_METER_SERIAL_NUMBER:-(not set)}"
echo "Using serial: ${SERIAL:-(none - will match by VID:PID only)}"
echo ""

# --- USB device enumeration ---
echo "=== USB Devices (lsusb) ==="
if command -v lsusb &>/dev/null; then
    lsusb
else
    echo "(lsusb not installed, trying apt...)"
    sudo apt-get install -y -q usbutils 2>&1 | tail -2
    lsusb 2>&1 || echo "lsusb failed"
fi
echo ""

echo "=== lsusb: AVHzy VID 0483 ==="
lsusb -d 0483: 2>/dev/null || echo "(none found with VID 0483)"
echo ""

echo "=== USB bus devices ==="
ls -la /dev/bus/usb/ 2>/dev/null || echo "(no /dev/bus/usb/)"
echo ""

# --- Python / pyusb setup ---
echo "=== Python / pyusb ==="
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found"
    exit 1
fi
echo "Python: $PYTHON ($($PYTHON --version))"

if ! $PYTHON -c "import usb.core" 2>/dev/null; then
    echo "pyusb not installed, installing dependencies..."
    # libusb-1.0-0 is required by pyusb at runtime
    sudo apt-get install -y -q libusb-1.0-0 2>&1 | tail -3
    pip3 install pyusb
fi

# Verify import actually works (pip may have failed)
if ! $PYTHON -c "import usb.core" 2>&1; then
    echo "ERROR: pyusb still not importable after install attempt - cannot continue"
    exit 1
fi
echo "pyusb: OK"
echo ""

# --- Main USB diagnostic ---
echo "=== USB Device Enumeration and Test ==="
$PYTHON -u - "${SERIAL}" 2>&1 <<'PYEOF'
import glob
import os
import shutil
import signal
import struct
import subprocess
import sys
import time

target_serial = sys.argv[1]

try:
    import usb.core
    import usb.util
except ImportError:
    print("FAIL: pyusb not available")
    sys.exit(1)

# AVHzy CT-3 (Shizuku) VID:PIDs - same as usb-power-profiling
VENDOR_ID = 0x0483
PRODUCT_IDS = [0xFFFE, 0xFFFF, 0x374B]

# Find all matching devices
all_avhzy = []
try:
    for pid in PRODUCT_IDS:
        found = usb.core.find(find_all=True, idVendor=VENDOR_ID, idProduct=pid)
        if found:
            all_avhzy.extend(found)
except usb.core.NoBackendError:
    print("FAIL: pyusb NoBackendError - libusb could not be loaded")
    print("  libusb-1.0-0 may be installed but not findable via ctypes")
    sys.exit(1)

print(f"Found {len(all_avhzy)} AVHzy/Shizuku device(s) (VID 0x0483):")
if not all_avhzy:
    print("  NONE")
    print()
    print("FAIL: no AVHzy power meter visible on USB bus")
    print("  Check: is the USB device bind-mounted into this container?")
    print("  Check: does /dev/bus/usb/ contain the device?")
    sys.exit(1)

for dev in all_avhzy:
    try:
        serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
    except Exception as e:
        serial = f"(error reading serial: {e})"
    print(f"  Bus {dev.bus:03d} Device {dev.address:03d}: "
          f"VID:PID {dev.idVendor:04x}:{dev.idProduct:04x}  serial={serial!r}")
print()

# Match by serial number
if target_serial:
    matched = []
    for dev in all_avhzy:
        try:
            serial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
        except Exception:
            serial = None
        if serial == target_serial:
            matched.append((dev, serial))

    if not matched:
        print(f"FAIL: no device found with serial number {target_serial!r}")
        serials = []
        for dev in all_avhzy:
            try:
                s = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
                serials.append(s)
            except Exception:
                serials.append("(unreadable)")
        print(f"  Available serial numbers: {serials}")
        sys.exit(1)

    if len(matched) > 1:
        print(f"WARNING: {len(matched)} devices match serial {target_serial!r}, using first")

    target_dev, target_dev_serial = matched[0]
    print(f"Matched device by serial number {target_serial!r}: "
          f"Bus {target_dev.bus:03d} Device {target_dev.address:03d}")
else:
    print(f"WARNING: USB_POWER_METER_SERIAL_NUMBER not set")
    if len(all_avhzy) > 1:
        print(f"WARNING: {len(all_avhzy)} AVHzy devices found - cannot identify correct one")
        print("  Set USB_POWER_METER_SERIAL_NUMBER to disambiguate")
        sys.exit(1)
    target_dev = all_avhzy[0]
    print(f"Using only available AVHzy device: "
          f"Bus {target_dev.bus:03d} Device {target_dev.address:03d}")
print()

def dump_interfaces(dev):
    EP_TYPES = {0: "control", 1: "isochronous", 2: "bulk", 3: "interrupt"}
    EP_DIRS  = {usb.util.ENDPOINT_IN: "IN", usb.util.ENDPOINT_OUT: "OUT"}
    try:
        cfg = dev.get_active_configuration()
        for intf in cfg:
            print(f"  Interface {intf.bInterfaceNumber} alt={intf.bAlternateSetting} "
                  f"class=0x{intf.bInterfaceClass:02x}")
            for ep in intf:
                ep_type = EP_TYPES.get(usb.util.endpoint_type(ep.bmAttributes), "?")
                ep_dir  = EP_DIRS.get(usb.util.endpoint_direction(ep.bEndpointAddress), "?")
                print(f"    ep 0x{ep.bEndpointAddress:02x} {ep_dir} {ep_type} "
                      f"maxPacket={ep.wMaxPacketSize}")
    except Exception as ex:
        print(f"  (could not dump interfaces: {ex})")

def find_bulk_endpoints(dev):
    cfg = dev.get_active_configuration()
    for intf in cfg:
        ep_in = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
            )
        )
        ep_out = usb.util.find_descriptor(
            intf,
            custom_match=lambda e: (
                usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT
                and usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
            )
        )
        if ep_in and ep_out:
            return ep_in, ep_out, intf.bInterfaceNumber
    return None, None, None

def kill_device_holders(dev):
    """Kill any userspace processes holding the device file open. Returns killed PIDs."""
    dev_path = f"/dev/bus/usb/{dev.bus:03d}/{dev.address:03d}"
    print(f"  Checking who has {dev_path} open (lsof):")
    if not shutil.which("lsof"):
        print("    (lsof not available - cannot check)")
        return []
    r = subprocess.run(["lsof", "-t", dev_path], capture_output=True, text=True)
    my_pid = os.getpid()
    pids = [int(p) for p in r.stdout.split() if p.strip().isdigit() and int(p) != my_pid]
    if not pids:
        print("    (no userspace processes found)")
        return []

    # Ignore SIGHUP before killing: if PID is in our session and dies, we'd get
    # SIGHUP and terminate silently without any further output.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    killed = []
    for pid in pids:
        try:
            name_r = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                                    capture_output=True, text=True)
            name = name_r.stdout.strip() or "?"
            print(f"    killing PID {pid} ({name})...")
            os.kill(pid, signal.SIGKILL)
            print(f"    killed PID {pid}")
            killed.append(pid)
        except ProcessLookupError:
            print(f"    PID {pid} already gone")
        except PermissionError:
            print(f"    cannot kill PID {pid} (permission denied)")
        except Exception as e:
            print(f"    error killing PID {pid}: {e}")
    return killed

def show_tty_devices():
    ttys = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if ttys:
        for tty in ttys:
            print(f"    {tty}  {oct(os.stat(tty).st_mode)}")
    else:
        print("    (none)")

def show_kernel_driver_status(dev):
    try:
        cfg = dev.get_active_configuration()
        for intf in cfg:
            n = intf.bInterfaceNumber
            try:
                active = dev.is_kernel_driver_active(n)
                print(f"    interface {n}: kernel driver {'ATTACHED' if active else 'not attached'}")
            except usb.core.USBError as ke:
                print(f"    interface {n}: cannot check ({ke})")
    except Exception as ce:
        print(f"    (could not read configuration: {ce})")

# Try to open and claim the device (same first step as usb-power-profiling)
print("=== USB Access Test ===")
ep_in = ep_out = None

for attempt in range(1, 3):
    print(f"Attempt {attempt}: opening device and finding bulk endpoints...")
    try:
        target_dev.set_configuration()
        cfg = target_dev.get_active_configuration()
        dump_interfaces(target_dev)
        print()
        ep_in, ep_out, intf_num = find_bulk_endpoints(target_dev)
        if ep_in and ep_out:
            print(f"Found bulk endpoints on interface {intf_num}")
            break
        else:
            print("FAIL: no interface has both bulk IN and OUT endpoints")
            sys.exit(1)
    except usb.core.USBError as e:
        print(f"USB error: {e}")
        print()
        print("  Kernel driver status:")
        show_kernel_driver_status(target_dev)
        print()
        print("  Serial ports (cdc_acm indicator):")
        show_tty_devices()
        print()
        killed = kill_device_holders(target_dev)

        # Detach cdc_acm (or any other kernel driver) from all interfaces
        print("  Detaching kernel drivers...")
        try:
            cfg = target_dev.get_active_configuration()
            for intf in cfg:
                n = intf.bInterfaceNumber
                try:
                    if target_dev.is_kernel_driver_active(n):
                        target_dev.detach_kernel_driver(n)
                        print(f"    detached kernel driver from interface {n}")
                    else:
                        print(f"    interface {n}: no kernel driver to detach")
                except usb.core.USBError as ke:
                    print(f"    interface {n}: detach failed: {ke}")
        except Exception as ex:
            print(f"    (could not detach: {ex})")

        if not killed and attempt == 2:
            print()
            print("FAIL: device still busy after detaching kernel drivers")
            sys.exit(1)

        print(f"  Waiting 2s for device to settle...")
        time.sleep(2)
        print()

if ep_in is None:
    print("FAIL: could not open device after 2 attempts")
    sys.exit(1)

print(f"PASS: bulk endpoint IN  = 0x{ep_in.bEndpointAddress:02x}")
print(f"PASS: bulk endpoint OUT = 0x{ep_out.bEndpointAddress:02x}")
print()

# Send CMD_STOP then CMD_START_SAMPLING and read one data packet
# Frame format: [0xa5][len_le32][payload][xor_checksum][0x5a]

BEGIN = 0xa5
END   = 0x5a
CMD_STOP            = 0x07
CMD_START_SAMPLING  = 0x09

def make_frame(cmd, args=(), request_id=0):
    payload = bytes([0x01, cmd, request_id, 0x00] + list(args))
    checksum = 0
    for b in payload:
        checksum ^= b
    frame = bytes([BEGIN]) + struct.pack("<I", len(payload)) + payload + bytes([checksum, END])
    return frame

def read_frame(ep_in, timeout_ms=3000):
    """Read and return one complete frame from the device. Note: XOR checksum is not validated."""
    buf = bytearray()
    while True:
        try:
            chunk = ep_in.read(512, timeout=timeout_ms)
            buf.extend(chunk)
        except usb.core.USBTimeoutError:
            return None
        # Look for a complete frame
        if BEGIN in buf:
            start = buf.index(BEGIN)
            buf = buf[start:]  # discard bytes before BEGIN
            if len(buf) >= 6:  # BEGIN + 4-byte len + at least 1 byte
                pkt_len = struct.unpack_from("<I", buf, 1)[0]
                frame_len = 1 + 4 + pkt_len + 1 + 1  # BEGIN+len+payload+checksum+END
                if len(buf) >= frame_len:
                    return bytes(buf[:frame_len])

print("=== Communication Test ===")
print("Sending CMD_STOP...")
try:
    ep_out.write(make_frame(CMD_STOP, request_id=0), timeout=2000)
except usb.core.USBError as e:
    print(f"FAIL: write error: {e}")
    sys.exit(1)

# Read the reply to CMD_STOP
frame = read_frame(ep_in, timeout_ms=2000)
if frame:
    hex_str = " ".join(f"{b:02x}" for b in frame)
    print(f"  Reply: {hex_str}")
else:
    print("  (no reply to CMD_STOP - may be ok)")

print("Sending CMD_START_SAMPLING (1ms interval)...")
sampling_request_id = 1
interval_bytes = struct.pack("<I", 1)  # 1ms
try:
    ep_out.write(make_frame(CMD_START_SAMPLING, args=interval_bytes, request_id=sampling_request_id), timeout=2000)
except usb.core.USBError as e:
    print(f"FAIL: write error: {e}")
    sys.exit(1)

print("Waiting for sampling data (up to 30s, 10 attempts × 3s timeout each)...")
got_sample = False
for _ in range(10):
    frame = read_frame(ep_in, timeout_ms=3000)
    if frame is None:
        break
    hex_str = " ".join(f"{b:02x}" for b in frame)
    print(f"  Frame ({len(frame)} bytes): {hex_str}")

    # Try to parse a sample: payload starts at offset 5
    # payload[0]=0x04, payload[1]=0, payload[2]=sampling_request_id, payload[3]=0
    # then float32 voltage, float32 current, uint64 timestamp
    if len(frame) >= 6:
        pkt_len = struct.unpack_from("<I", frame, 1)[0]
        payload = frame[5:5 + pkt_len]
        if (len(payload) >= 20 and payload[0] == 0x04 and payload[1] == 0x00
                and payload[2] == sampling_request_id and payload[3] == 0x00):
            voltage = struct.unpack_from("<f", payload, 4)[0]
            current = abs(struct.unpack_from("<f", payload, 8)[0])  # device may report negative current (discharge/backfeed)
            power   = voltage * current
            print(f"  PASS: sample decoded: {voltage:.4f}V  {current:.4f}A  {power:.4f}W")
            got_sample = True
            break

# Send CMD_STOP to clean up
try:
    ep_out.write(make_frame(CMD_STOP, request_id=2), timeout=2000)
except Exception:
    pass
usb.util.release_interface(target_dev, intf_num)

print()
if got_sample:
    print("RESULT: PASS - power meter connected, accessible, and returning samples")
else:
    print("RESULT: UNCERTAIN - device found and opened, but no parseable sample received")
    print("  The device may need something in USB pass-through to start sampling.")
    sys.exit(1)
PYEOF

EXIT=$?
echo ""
if [ $EXIT -eq 0 ]; then
    echo "=== OVERALL RESULT: PASS ==="
else
    echo "=== OVERALL RESULT: FAIL ==="
fi
exit $EXIT
