#!/bin/bash

set -e

echo "run_cmd_on_device.sh: starting"

# detect device serial
DEVICE_SERIAL=$(adb devices -l | grep 'device usb' | head -1 | cut -f1 -d' ')
if [ -z "$DEVICE_SERIAL" ]; then
    # fallback: any connected device
    DEVICE_SERIAL=$(adb devices | grep -v "List of devices" | grep "device$" | head -1 | cut -f1 -d'	')
fi

echo "DEVICE_SERIAL=$DEVICE_SERIAL"

if [ -z "$DEVICE_SERIAL" ]; then
    echo "ERROR: no ADB device found"
    echo "" > output.txt
    exit 1
fi

if [ -z "$CMD_TO_RUN" ]; then
    echo "ERROR: CMD_TO_RUN env var not set"
    echo "" > output.txt
    exit 1
fi

echo "CMD_TO_RUN=$CMD_TO_RUN"
echo "CMD_OUTPUT_START"
adb -s "$DEVICE_SERIAL" shell "$CMD_TO_RUN" | tee output.txt
CMD_EXIT_CODE=${PIPESTATUS[0]}
echo "CMD_OUTPUT_END"
echo "CMD_EXIT_CODE=$CMD_EXIT_CODE"

exit $CMD_EXIT_CODE
