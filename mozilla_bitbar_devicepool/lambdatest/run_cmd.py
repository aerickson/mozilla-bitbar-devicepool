# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import json
import logging
import os
import shlex
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from glob import glob

from tqdm import tqdm


def validate_artifact_path(path):
    """Return a safe relative artifact path or glob for the HE workspace."""
    if not path or os.path.isabs(path):
        raise ValueError("artifact paths must be non-empty relative paths")
    parts = path.replace("\\", "/").split("/")
    if any(part in ("", "..") for part in parts):
        raise ValueError(f"unsafe artifact path: {path!r}")
    return "/".join(parts)


def artifact_directory(artifacts_root, udid):
    """Return the persistent artifact directory for a device serial."""
    if not udid or udid in (".", "..") or any(char not in "-_." and not char.isalnum() for char in udid):
        raise ValueError(f"unsafe device serial for artifact directory: {udid!r}")
    return os.path.join(artifacts_root, udid)


def missing_required_artifacts(artifacts_dir, required_artifact_globs):
    return [
        artifact_glob
        for artifact_glob in required_artifact_globs or []
        # HyperExecute nests each downloaded payload below its artifact name and
        # attempt number (for example, extra-artifact-1/1/<payload>). Search
        # beneath the device directory rather than assuming a flat download.
        if not glob(os.path.join(artifacts_dir, "**", artifact_glob), recursive=True)
    ]


def generate_config(udid, command, queue_timeout=900, artifact_paths=None):
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
"""
    for index, artifact_path in enumerate(artifact_paths or [], start=1):
        config += f"""  - name: extra-artifact-{index}
    path:
      - {json.dumps(artifact_path)}
"""
    config += f"""

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


def run_on_device(
    udid,
    command,
    project_root_dir,
    user_script_dir,
    timeout=1800,
    queue_timeout=900,
    script_path=None,
    labels=None,
    artifacts_root=None,
    artifact_paths=None,
    required_artifact_globs=None,
):
    timestamp = time.time_ns()
    temp_dir = f"/tmp/mozilla-lt-run-cmd.{udid}.{timestamp}"
    artifacts_dir = artifact_directory(artifacts_root, udid) if artifacts_root else os.path.join(temp_dir, "artifacts")
    config_path = os.path.join(temp_dir, "hyperexecute.yaml")

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
        os.makedirs(temp_dir, exist_ok=True)
        os.makedirs(artifacts_dir, exist_ok=True)
        if artifacts_root:
            logging.warning(f"run_on_device [{udid}]: preserving artifacts at {artifacts_dir}")

        shutil.copytree(user_script_dir, os.path.join(temp_dir, "user_script"))

        if script_path:
            dest = os.path.join(temp_dir, "user_script", "run_script.sh")
            shutil.copy2(script_path, dest)
            os.chmod(dest, 0o755)

        config = generate_config(udid, command, queue_timeout=queue_timeout, artifact_paths=artifact_paths)
        with open(config_path, "w") as f:
            f.write(config)

        hyperexecute_path = os.path.join(project_root_dir, "hyperexecute")
        labels_csv = ",".join(["run-cmd", udid, *(labels or [])])
        cmd = (
            f"{hyperexecute_path}"
            f" --labels {shlex.quote(labels_csv)}"
            f" --exclude-external-binaries"
            f" --download-artifacts"
            f" --download-artifacts-path {shlex.quote(artifacts_dir)}"
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

        if result.returncode == 0:
            status = "ok"
        elif _is_queue_timeout(result.stdout + result.stderr):
            status = "queue_timeout"
        else:
            status = "failed"
        missing_globs = missing_required_artifacts(artifacts_dir, required_artifact_globs)
        if missing_globs:
            status = "failed"
            logging.error(
                f"run_on_device [{udid}]: missing required artifact(s) in {artifacts_dir}: {', '.join(missing_globs)}"
            )
        return (udid, output_text, status)

    except subprocess.TimeoutExpired:
        logging.error(f"run_on_device [{udid}]: timed out after {timeout}s")
        return (udid, None, "queue_timeout")
    except Exception as e:
        logging.error(f"run_on_device [{udid}]: exception: {e}")
        return (udid, None, "failed")
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


_QUEUE_TIMEOUT_PATTERNS = [
    "queuetimeout",
    "queue timeout",
    "no device available",
    "no devices available",
    "device not available",
    "waiting for device",
]


def _is_queue_timeout(text):
    lower = text.lower()
    return any(p in lower for p in _QUEUE_TIMEOUT_PATTERNS)


def _run_batch(
    udids,
    command,
    project_root_dir,
    user_script_dir,
    max_parallel,
    timeout,
    queue_timeout,
    script_path,
    labels,
    artifacts_root,
    artifact_paths,
    required_artifact_globs,
    label="",
    start_delay=5,
    on_update=None,
):
    results = {}
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        futures = {}
        for i, udid in enumerate(udids):
            if i > 0 and start_delay > 0:
                time.sleep(start_delay)
            future = executor.submit(
                run_on_device,
                udid,
                command,
                project_root_dir,
                user_script_dir,
                timeout,
                queue_timeout,
                script_path,
                labels,
                artifacts_root,
                artifact_paths,
                required_artifact_globs,
            )
            futures[future] = udid
        succeeded = 0
        with tqdm(total=len(futures), desc=label or "devices", unit="device", dynamic_ncols=True) as bar:
            for future in as_completed(futures):
                udid, output, status = future.result()
                results[udid] = (output, status)
                if status == "ok":
                    succeeded += 1
                bar_status = {"ok": "OK", "failed": "FAIL", "queue_timeout": "TIMEOUT"}.get(status, status)
                bar.set_postfix_str(f"{succeeded}/{len(futures)} completed (latest: {udid} [{bar_status}])")
                bar.update(1)
                if on_update:
                    on_update(results)
    return results


def run_on_all_devices(
    udids,
    command,
    project_root_dir,
    user_script_dir,
    max_parallel=100,
    timeout=1800,
    queue_timeout=900,
    script_path=None,
    max_retries=5,
    retry_wait=10,
    start_delay=1,
    labels=None,
    artifacts_root=None,
    artifact_paths=None,
    required_artifact_globs=None,
    on_update=None,
):
    results = _run_batch(
        udids,
        command,
        project_root_dir,
        user_script_dir,
        max_parallel,
        timeout,
        queue_timeout,
        script_path,
        labels,
        artifacts_root,
        artifact_paths,
        required_artifact_globs,
        label=f"attempt 1/{max_retries + 1}",
        start_delay=start_delay,
        on_update=on_update,
    )

    for attempt in range(1, max_retries + 1):
        failed = [udid for udid, (_, status) in results.items() if status == "queue_timeout"]
        if not failed:
            break
        logging.info(
            f"attempt {attempt + 1}/{max_retries + 1}: {len(failed)} device(s) failed, waiting {retry_wait}s..."
        )
        time.sleep(retry_wait)
        retry_results = _run_batch(
            failed,
            command,
            project_root_dir,
            user_script_dir,
            max_parallel,
            timeout,
            queue_timeout,
            script_path,
            labels,
            artifacts_root,
            artifact_paths,
            required_artifact_globs,
            label=f"attempt {attempt + 1}/{max_retries + 1}",
            start_delay=start_delay,
            on_update=lambda partial: on_update({**results, **partial}) if on_update else None,
        )
        results.update(retry_results)

    return results


def format_results(results, output_format="text"):
    if output_format == "json":
        import json

        out = {}
        for udid, (output, status) in sorted(results.items()):
            out[udid] = {"output": output, "status": status}
        return json.dumps(out, indent=2)

    if output_format == "csv":
        import csv
        import io

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["udid", "status", "output"])
        for udid, (output, status) in sorted(results.items()):
            writer.writerow([udid, status, output or ""])
        return buf.getvalue()

    # text (default)
    _status_label = {"ok": "OK", "failed": "FAILED", "queue_timeout": "TIMEOUT"}
    lines = []
    for udid, (output, status) in sorted(results.items()):
        label = _status_label.get(status, status.upper())
        lines.append(f"=== {udid} [{label}] ===")
        if output:
            lines.append(output)
        else:
            lines.append("(no output)")
        lines.append("")
    return "\n".join(lines)
