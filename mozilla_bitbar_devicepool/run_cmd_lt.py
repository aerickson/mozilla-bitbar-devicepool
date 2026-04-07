# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import argparse
import logging
import os
import sys

from tqdm import tqdm

from mozilla_bitbar_devicepool import configuration_lt
from mozilla_bitbar_devicepool.lambdatest import run_cmd


class _TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        try:
            tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


def main():
    parser = argparse.ArgumentParser(
        description="Run an arbitrary ADB shell command on LambdaTest Android devices via HyperExecute"
    )
    parser.add_argument("command", nargs="?", help="ADB shell command to run on devices")
    parser.add_argument(
        "--script", metavar="FILE", help="Local shell script to run on device host (has DEVICE_SERIAL env var)"
    )

    device_group = parser.add_mutually_exclusive_group(required=True)
    device_group.add_argument("--group", "-g", action="append", metavar="GROUP", help="Device group name (repeatable)")
    device_group.add_argument(
        "--device", "-d", action="append", metavar="UDID", help="Specific device UDID (repeatable)"
    )
    device_group.add_argument("--all", action="store_true", help="Run on all devices in all groups")

    parser.add_argument(
        "--parallel", "-p", type=int, default=100, metavar="N", help="Max parallel HyperExecute jobs (default: 100)"
    )
    parser.add_argument(
        "--start-delay",
        type=int,
        default=1,
        metavar="SECS",
        help="Seconds between job submissions to avoid overwhelming the API (default: 1)",
    )
    parser.add_argument(
        "--timeout", type=int, default=1800, metavar="SECS", help="Per-device job timeout in seconds (default: 1800)"
    )
    parser.add_argument(
        "--queue-timeout",
        type=int,
        default=900,
        metavar="SECS",
        help="Device queue timeout in seconds, must be 300-900 (default: 900)",
    )
    parser.add_argument(
        "--retries", type=int, default=5, metavar="N", help="Max retries for failed devices (default: 5)"
    )
    parser.add_argument(
        "--retry-wait", type=int, default=10, metavar="SECS", help="Seconds to wait between retries (default: 10)"
    )
    parser.add_argument(
        "--output-format", choices=["text", "json", "csv"], default="text", help="Output format (default: text)"
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    if not args.command and not args.script:
        parser.error("one of command or --script is required")
    if args.command and args.script:
        parser.error("command and --script are mutually exclusive")
    if args.script and not os.path.isfile(args.script):
        parser.error(f"script file not found: {args.script}")

    log_level = logging.DEBUG if args.verbose else logging.WARNING
    handler = _TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(threadName)s %(levelname)s %(message)s"))
    logging.basicConfig(level=log_level, handlers=[handler])

    config_object = configuration_lt.ConfigurationLt(lightweight=True)
    config_object.configure()

    device_groups = config_object.config.get("device_groups", {})

    # resolve target UDIDs
    if args.all:
        udids = []
        for group_name, devices in device_groups.items():
            if devices:
                udids.extend(devices)
    elif args.group:
        udids = []
        for group_name in args.group:
            if group_name not in device_groups:
                print(f"ERROR: device group '{group_name}' not found in config", file=sys.stderr)
                print(f"Available groups: {', '.join(sorted(device_groups.keys()))}", file=sys.stderr)
                sys.exit(1)
            devices = device_groups[group_name]
            if not devices:
                print(f"WARNING: device group '{group_name}' has no devices", file=sys.stderr)
            else:
                udids.extend(devices)
    else:
        udids = args.device

    if not udids:
        print("ERROR: no devices to target", file=sys.stderr)
        sys.exit(1)

    print(f"Targeting {len(udids)} device(s): {', '.join(udids)}")
    if args.script:
        print(f"Script: {args.script}")
    else:
        print(f"Command: {args.command}")
    print()

    # resolve paths
    this_dir = os.path.dirname(os.path.realpath(__file__))
    project_root_dir = os.path.abspath(os.path.join(this_dir, ".."))
    user_script_dir = os.path.join(this_dir, "lambdatest", "user_scripts", "run_cmd")

    if not os.path.isdir(user_script_dir):
        print(f"ERROR: user_script dir not found: {user_script_dir}", file=sys.stderr)
        sys.exit(1)

    results = run_cmd.run_on_all_devices(
        udids=udids,
        command=args.command,
        project_root_dir=project_root_dir,
        user_script_dir=user_script_dir,
        max_parallel=args.parallel,
        timeout=args.timeout,
        queue_timeout=args.queue_timeout,
        script_path=args.script,
        max_retries=args.retries,
        retry_wait=args.retry_wait,
        start_delay=args.start_delay,
    )

    print(run_cmd.format_results(results, args.output_format))

    failed = [udid for udid, (_, success) in results.items() if not success]
    if failed:
        print(f"FAILED devices ({len(failed)}): {', '.join(sorted(failed))}", file=sys.stderr)
        sys.exit(1)
