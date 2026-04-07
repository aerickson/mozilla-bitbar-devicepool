#!/bin/bash
# Reports Chrome-related package versions on the device.
# Runs on the HyperExecute host; DEVICE_SERIAL is set by run_cmd_on_device.sh.

for pkg in org.chromium.chrome com.android.chrome; do
    v=$(adb -s "$DEVICE_SERIAL" shell dumpsys package "$pkg" 2>/dev/null | grep -m1 versionName | sed 's/.*versionName=//')
    [ -n "$v" ] && echo "$pkg: $v"
done
