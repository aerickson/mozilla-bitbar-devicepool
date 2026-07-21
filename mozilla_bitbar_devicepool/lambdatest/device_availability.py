# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

"""Check whether LambdaTest private-cloud devices are available."""

import argparse
import os
import time

from mozilla_bitbar_devicepool.lambdatest.api import get_devices

AVAILABLE_STATUS = "active"


def get_requested_devices(identifiers, lt_username, lt_api_key):
    """Return devices matching each requested UDID or exact model name.

    A model name can match multiple physical devices; all matches are returned.
    """
    response = get_devices(lt_username, lt_api_key)
    if not response:
        raise RuntimeError("Unable to fetch devices from the LambdaTest API.")

    devices = response.get("data", {}).get("private_cloud_devices", [])
    requested_devices = []
    missing_identifiers = []
    seen_udids = set()
    for identifier in identifiers:
        matches = [device for device in devices if identifier in (device.get("udid"), device.get("name"))]
        if not matches:
            missing_identifiers.append(identifier)
            continue
        for device in matches:
            if device["udid"] not in seen_udids:
                requested_devices.append(device)
                seen_udids.add(device["udid"])

    if missing_identifiers:
        raise ValueError(f"Device(s) not found: {', '.join(missing_identifiers)}")
    return requested_devices


def print_device_statuses(devices):
    """Print one concise status line per device and return whether all are active."""
    for device in devices:
        print(f"{device['udid']}\t{device.get('name', 'unknown')}\t{device.get('status', 'unknown')}")
    return all(device.get("status") == AVAILABLE_STATUS for device in devices)


def parse_args(args=None):
    parser = argparse.ArgumentParser(description="Check LambdaTest private-cloud device availability.")
    parser.add_argument("devices", nargs="+", help="A device UDID or exact LambdaTest phone model name.")
    parser.add_argument("--wait", action="store_true", help="Poll until every requested device is active.")
    parser.add_argument(
        "--interval",
        type=float,
        default=10,
        metavar="SECONDS",
        help="Seconds between checks in --wait mode (default: 10).",
    )
    parsed_args = parser.parse_args(args)
    if parsed_args.interval <= 0:
        parser.error("--interval must be greater than zero")
    return parsed_args


def main(args=None):
    """Run the availability checker and return a shell-compatible exit status."""
    parsed_args = parse_args(args)
    try:
        while True:
            devices = get_requested_devices(
                parsed_args.devices,
                os.environ["LT_USERNAME"],
                os.environ["LT_ACCESS_KEY"],
            )
            all_available = print_device_statuses(devices)
            if not parsed_args.wait or all_available:
                return 0
            time.sleep(parsed_args.interval)
    except KeyError as error:
        print(f"Missing required environment variable: {error.args[0]}")
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
