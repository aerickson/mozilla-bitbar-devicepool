#!/bin/bash
# Diagnostic script for AVHzy CT-3 USB power meter (B098TQLYYN)
#
# Runs on the LT HOST machine via run_cmd_lt --script.
# Does NOT require a connected Android device.
#
# Usage:
#   run_cmd_lt --script scripts/check_power_meter.sh --group a55-perf
#   run_cmd_lt --script scripts/check_power_meter.sh --device <UDID>
#
# The AVHzy CT-3 appears as a CDC serial device (/dev/ttyUSB* or /dev/ttyACM*).
# It streams data continuously in packets: [0xa5][LEN_LE4][DATA...][0x5a]
# at 115200 baud.

set -o pipefail

echo "=== AVHzy CT-3 Power Meter Diagnostic ==="
echo "Date: $(date)"
echo "Host: $(hostname)"
echo "User: $(id)"
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

echo "=== USB Serial by-id ==="
if [ -d /dev/serial/by-id ]; then
    ls -la /dev/serial/by-id/
else
    echo "(no /dev/serial/by-id/)"
fi
echo ""

# --- Serial port detection ---
echo "=== Serial Ports ==="
FOUND_PORTS=()
for port in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyUSB2 /dev/ttyUSB3 \
            /dev/ttyACM0 /dev/ttyACM1 /dev/ttyACM2 /dev/ttyACM3; do
    if [ -c "$port" ]; then
        echo "  FOUND: $(ls -la $port)"
        FOUND_PORTS+=("$port")
    fi
done
if [ ${#FOUND_PORTS[@]} -eq 0 ]; then
    echo "  NONE: no ttyUSB or ttyACM devices found"
fi
echo ""

# --- Read data from the serial port ---
if [ ${#FOUND_PORTS[@]} -eq 0 ]; then
    echo "=== RESULT: FAIL - no serial port found ==="
    echo "Power meter not detected.  Check USB cable and host USB port."
    exit 1
fi

PORT="${FOUND_PORTS[0]}"
echo "=== Reading from $PORT ==="

# Check group membership for dialout/tty access
OWNER_GROUP=$(stat -c '%G' "$PORT" 2>/dev/null || stat -f '%Sg' "$PORT" 2>/dev/null)
echo "Port group: $OWNER_GROUP"
if ! groups | grep -qw "$OWNER_GROUP"; then
    echo "WARNING: current user is not in group '$OWNER_GROUP' - may get permission denied"
    echo "  Fix: sudo usermod -aG $OWNER_GROUP \$USER  (then re-login)"
fi
echo ""

# Try pyserial; install it if missing
echo "=== Python / pyserial ==="
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "ERROR: python3 not found"
    exit 1
fi
echo "Python: $PYTHON ($($PYTHON --version))"

$PYTHON -c "import serial" 2>/dev/null || {
    echo "pyserial not installed, installing..."
    pip3 install --quiet pyserial 2>&1 | tail -2
}
echo ""

echo "=== Serial Read Test ==="
$PYTHON - "$PORT" <<'PYEOF'
import sys
import time

port_path = sys.argv[1]
BAUD = 115200
READ_BYTES = 256
READ_TIMEOUT = 3.0

try:
    import serial
except ImportError:
    print("FAIL: pyserial not available - cannot run read test")
    sys.exit(1)

print(f"Opening {port_path} at {BAUD} baud (timeout={READ_TIMEOUT}s)...")
try:
    ser = serial.Serial(port_path, baudrate=BAUD, timeout=READ_TIMEOUT)
except serial.SerialException as e:
    print(f"FAIL: cannot open port: {e}")
    sys.exit(1)

print(f"Port opened OK")
print(f"Waiting up to {READ_TIMEOUT}s for {READ_BYTES} bytes...")

data = ser.read(READ_BYTES)
ser.close()

if not data:
    print("FAIL: no data received within timeout")
    print("  The device may be off, unpowered, or not transmitting.")
    sys.exit(1)

hex_str = " ".join(f"{b:02x}" for b in data)
print(f"Read {len(data)} bytes:")
print(f"  hex: {hex_str}")

# Check for AVHzy CT-3 packet framing: 0xa5 start, 0x5a end
if 0xa5 in data:
    idx = data.index(0xa5)
    print(f"  PASS: found 0xa5 packet-start marker at offset {idx}")
    # Try to find matching 0x5a end marker
    end_idx = data.find(0x5a, idx + 1)
    if end_idx != -1:
        pkt_len = end_idx - idx + 1
        pkt = data[idx:end_idx + 1]
        pkt_hex = " ".join(f"{b:02x}" for b in pkt)
        print(f"  PASS: found 0x5a packet-end marker at offset {end_idx} "
              f"(packet length {pkt_len})")
        print(f"  Packet: {pkt_hex}")
    else:
        print("  INFO: 0x5a end marker not yet seen in this window (normal if buffer is mid-packet)")
    print("")
    print("RESULT: PASS - power meter is connected and streaming data")
else:
    print("  WARN: no 0xa5 start marker in received data")
    print("  Received data does not match expected AVHzy CT-3 format.")
    print("  Possible causes: wrong baud rate, wrong device, device not in measurement mode.")
    print("")
    print("RESULT: UNCERTAIN - data received but not AVHzy CT-3 format")
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
