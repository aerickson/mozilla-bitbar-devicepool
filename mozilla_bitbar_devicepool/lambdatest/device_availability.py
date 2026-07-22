# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

"""Check whether LambdaTest private-cloud devices are available."""

import argparse
import curses
import datetime
import os
import sys
import time

from mozilla_bitbar_devicepool.lambdatest.api import get_devices

AVAILABLE_STATUS = "active"


class WaitInterrupted(Exception):
    """Raised when a wait is interrupted, retaining its elapsed time."""

    def __init__(self, waiting_seconds):
        self.waiting_seconds = waiting_seconds


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


def format_duration(seconds):
    """Format a duration for the status display."""
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_status_line(devices, checked_at, waiting_seconds, interval):
    """Return the compact, one-line status output used outside the TUI."""
    available_count = sum(device.get("status") == AVAILABLE_STATUS for device in devices)
    statuses = ", ".join(f"{device['udid']}={device.get('status', 'unknown')}" for device in devices)
    next_check = checked_at + datetime.timedelta(seconds=interval)
    return (
        f"{checked_at:%H:%M:%S} | waiting {format_duration(waiting_seconds)} | "
        f"next {next_check:%H:%M:%S} | active {available_count}/{len(devices)} | {statuses}"
    )


def all_devices_available(devices):
    """Return whether every requested device is active."""
    return all(device.get("status") == AVAILABLE_STATUS for device in devices)


def add_line(window, row, text, attributes=0):
    """Write a line without failing on a small terminal window."""
    height, width = window.getmaxyx()
    if row < height:
        try:
            window.addnstr(row, 0, text, max(0, width - 1), attributes)
        except curses.error:
            pass


def setup_colors():
    """Return display attributes, falling back gracefully without color support."""
    colors = {"normal": 0, "header": curses.A_BOLD, "active": 0, "busy": 0, "error": 0}
    if not curses.has_colors():
        return colors

    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    return {
        "normal": 0,
        "header": curses.color_pair(1) | curses.A_BOLD,
        "active": curses.color_pair(2) | curses.A_BOLD,
        "busy": curses.color_pair(3) | curses.A_BOLD,
        "error": curses.color_pair(4) | curses.A_BOLD,
    }


def status_attributes(device, colors):
    """Choose the display color for a LambdaTest device state."""
    status = device.get("status", "").lower()
    if status == AVAILABLE_STATUS:
        return colors["active"]
    if status == "busy":
        return colors["busy"]
    return colors["error"]


def render_tui(window, devices, checked_at, started_at, interval, next_check, wait, colors):
    """Render the device dashboard."""
    available_count = sum(device.get("status") == AVAILABLE_STATUS for device in devices)
    waiting_seconds = time.monotonic() - started_at
    remaining_seconds = max(0, next_check - time.monotonic())
    next_check_time = datetime.datetime.now() + datetime.timedelta(seconds=remaining_seconds)

    window.erase()
    add_line(
        window, 0, "LambdaTest Device Availability                                         q: quit", colors["header"]
    )
    add_line(
        window,
        1,
        f"Last update: {checked_at:%Y-%m-%d %H:%M:%S} | every {interval:g}s | "
        f"next: {next_check_time:%H:%M:%S} ({format_duration(remaining_seconds)})",
    )
    mode = "until all active" if wait else "watching"
    add_line(
        window,
        2,
        f"Waiting: {format_duration(waiting_seconds)} | Active: {available_count}/{len(devices)} | Mode: {mode}",
        colors["active"] if available_count == len(devices) else colors["busy"],
    )
    add_line(window, 4, f"{'UDID':<18} {'MODEL':<28} STATUS", colors["header"])
    for row, device in enumerate(devices, start=5):
        add_line(
            window,
            row,
            f"{device['udid']:<18} {device.get('name', 'unknown'):<28} {device.get('status', 'unknown')}",
            status_attributes(device, colors),
        )
    window.refresh()


def run_non_tui(fetch_devices, interval, wait):
    """Print a single-line status update each time the API is checked."""
    started_at = time.monotonic()
    try:
        while True:
            devices = fetch_devices()
            checked_at = datetime.datetime.now()
            print(format_status_line(devices, checked_at, time.monotonic() - started_at, interval), flush=True)
            if not wait or all_devices_available(devices):
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        if wait:
            raise WaitInterrupted(time.monotonic() - started_at)
        raise


def run_tui(window, fetch_devices, interval, wait):
    """Display an interactive device dashboard, refreshing at ``interval``."""
    window.nodelay(True)
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    colors = setup_colors()
    started_at = time.monotonic()
    next_check = 0
    devices = []
    checked_at = datetime.datetime.now()
    try:
        while True:
            now = time.monotonic()
            if now >= next_check:
                devices = fetch_devices()
                checked_at = datetime.datetime.now()
                next_check = now + interval
                if wait and all_devices_available(devices):
                    render_tui(window, devices, checked_at, started_at, interval, next_check, wait, colors)
                    return 0

            render_tui(window, devices, checked_at, started_at, interval, next_check, wait, colors)
            key = window.getch()
            if key in (ord("q"), ord("Q"), 27):
                return 0
            time.sleep(0.1)
    except KeyboardInterrupt:
        if wait:
            raise WaitInterrupted(time.monotonic() - started_at)
        raise


def parse_args(args=None):
    parser = argparse.ArgumentParser(description="Check LambdaTest private-cloud device availability.")
    parser.add_argument("devices", nargs="+", help="A device UDID or exact LambdaTest phone model name.")
    parser.add_argument("--wait", action="store_true", help="Poll until every requested device is active.")
    parser.add_argument(
        "--no-tui", action="store_true", help="Print compact status lines instead of the interactive dashboard."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=10,
        metavar="SECONDS",
        help="Seconds between API checks (default: 10).",
    )
    parsed_args = parser.parse_args(args)
    if parsed_args.interval <= 0:
        parser.error("--interval must be greater than zero")
    return parsed_args


def main(args=None):
    """Run the availability checker and return a shell-compatible exit status."""
    parsed_args = parse_args(args)

    def fetch_devices():
        return get_requested_devices(
            parsed_args.devices,
            os.environ["LT_USERNAME"],
            os.environ["LT_ACCESS_KEY"],
        )

    try:
        if parsed_args.no_tui or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return run_non_tui(fetch_devices, parsed_args.interval, parsed_args.wait)
        return curses.wrapper(run_tui, fetch_devices, parsed_args.interval, parsed_args.wait)
    except KeyError as error:
        print(f"Missing required environment variable: {error.args[0]}")
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
    except WaitInterrupted as error:
        print(f"\nStopped waiting after {format_duration(error.waiting_seconds)}.")
        return 130
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
