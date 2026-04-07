# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import logging
import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def generate_config(udid, command, queue_timeout=300):
    fixed_ip_line = f'fixedIP: "{udid}"'
    config = f"""version: "0.2"

autosplit: true
runson: android
concurrency: 1

testDiscovery:
  command: echo "run-cmd"
  mode: static
  type: raw

env:
  CMD_TO_RUN: {command!r}

testRunnerCommand: bash ./user_script/run_cmd_on_device.sh

frameworkStatusOnly: true
dynamicAllocation: true
shell: bash

uploadArtifacts:
  - name: run-cmd-output
    path:
      - output.txt

framework:
  name: raw
  args:
    devices:
      - ".*-.*"
    framework:
    {fixed_ip_line}
    video: false
    deviceLogs: false
    privateCloud: true
    queueTimeout: {queue_timeout}
    region: us
    disableReleaseDevice: true
    isRealMobile: true
    reservation: false
    platformName: android
"""
    return config


def run_on_device(udid, command, project_root_dir, user_script_dir, timeout=300, queue_timeout=300):
    timestamp = time.time_ns()
    temp_dir = f"/tmp/mozilla-lt-run-cmd.{udid}.{timestamp}"
    artifacts_dir = os.path.join(temp_dir, "artifacts")
    config_path = os.path.join(temp_dir, "hyperexecute.yaml")

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)

        shutil.copytree(user_script_dir, os.path.join(temp_dir, "user_script"))

        config = generate_config(udid, command, queue_timeout=queue_timeout)
        with open(config_path, "w") as f:
            f.write(config)

        hyperexecute_path = os.path.join(project_root_dir, "hyperexecute")
        labels_csv = f"run-cmd,{udid}"
        cmd = (
            f"{hyperexecute_path}"
            f" --labels '{labels_csv}'"
            f" --exclude-external-binaries"
            f" --download-artifacts"
            f" --download-artifacts-path {artifacts_dir}"
            f" --force-clean-artifacts"
            f" -i {config_path}"
        )

        logging.info(f"run_on_device [{udid}]: launching HyperExecute")
        logging.info(f"run_on_device [{udid}]: cmd: {cmd}")
        logging.info(f"run_on_device [{udid}]: cwd: {temp_dir}")
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        logging.info(f"run_on_device [{udid}]: HE returncode: {result.returncode}")
        logging.info(f"run_on_device [{udid}]: HE stdout:\n{result.stdout}")
        if result.stderr:
            logging.info(f"run_on_device [{udid}]: HE stderr:\n{result.stderr}")

        # log artifacts dir contents
        logging.info(f"run_on_device [{udid}]: artifacts_dir: {artifacts_dir}")
        for root, dirs, files in os.walk(artifacts_dir):
            for fname in files:
                fpath = os.path.join(root, fname)
                logging.info(f"run_on_device [{udid}]: artifact file: {fpath}")

        # try to read artifact output file
        output_text = None
        for root, _dirs, files in os.walk(artifacts_dir):
            for fname in files:
                if fname == "output.txt":
                    with open(os.path.join(root, fname)) as f:
                        output_text = f.read().strip()
                    logging.info(f"run_on_device [{udid}]: found output.txt: {output_text!r}")
                    break
            if output_text is not None:
                break

        if output_text is None:
            logging.warning(
                f"run_on_device [{udid}]: output.txt not found in artifacts, falling back to stdout parsing"
            )
            output_text = _parse_stdout_markers(result.stdout)
            logging.info(f"run_on_device [{udid}]: stdout markers result: {output_text!r}")

        success = result.returncode == 0
        return (udid, output_text, success)

    except subprocess.TimeoutExpired:
        logging.error(f"run_on_device [{udid}]: timed out after {timeout}s")
        return (udid, None, False)
    except Exception as e:
        logging.error(f"run_on_device [{udid}]: exception: {e}")
        return (udid, None, False)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _parse_stdout_markers(stdout):
    lines = stdout.splitlines()
    capturing = False
    captured = []
    for line in lines:
        if line.strip() == "CMD_OUTPUT_START":
            capturing = True
            continue
        if line.strip() == "CMD_OUTPUT_END":
            capturing = False
            continue
        if capturing:
            captured.append(line)
    if captured:
        return "\n".join(captured).strip()
    return None


def run_on_all_devices(
    udids, command, project_root_dir, user_script_dir, max_parallel=10, timeout=300, queue_timeout=300
):
    results = {}
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {
            executor.submit(
                run_on_device, udid, command, project_root_dir, user_script_dir, timeout, queue_timeout
            ): udid
            for udid in udids
        }
        for future in as_completed(futures):
            udid, output, success = future.result()
            results[udid] = (output, success)
            status = "OK" if success else "FAILED"
            logging.info(f"  [{status}] {udid}")
    return results


def format_results(results, output_format="text"):
    if output_format == "json":
        import json

        out = {}
        for udid, (output, success) in sorted(results.items()):
            out[udid] = {"output": output, "success": success}
        return json.dumps(out, indent=2)

    if output_format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["udid", "success", "output"])
        for udid, (output, success) in sorted(results.items()):
            writer.writerow([udid, success, output or ""])
        return buf.getvalue()

    # text (default)
    lines = []
    for udid, (output, success) in sorted(results.items()):
        status = "OK" if success else "FAILED"
        lines.append(f"=== {udid} [{status}] ===")
        if output:
            lines.append(output)
        else:
            lines.append("(no output)")
        lines.append("")
    return "\n".join(lines)
