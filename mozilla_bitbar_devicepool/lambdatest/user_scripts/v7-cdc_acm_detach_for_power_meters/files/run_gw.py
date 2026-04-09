#!/usr/bin/env python3

import json
import logging
import os
import socket
import subprocess
import sys

script_name = sys.argv[0]

try:
    try:
        import google.cloud.logging

        # setup stackdriver
        stackdriver_client = google.cloud.logging.Client()
        stackdriver_client.setup_logging()
    except google.auth.exceptions.DefaultCredentialsError:
        print("%s/WARNING: Stackdriver credentials missing. Stackdriver is not functional." % script_name)
except (NameError, ImportError):
    print("%s/WARNING: Could not import google.cloud.logging! Stackdriver is not functional." % script_name)

# run g-w in a shell with an almost-empty environ
# - print to stdout & stderr
# - log to papertrail


def log_to_pt(message, print_to_screen=False):
    logging.info("%s: %s" % (hostname, message))
    if print_to_screen:
        print(message)


scriptvars_json_file = "/home/ltuser/taskcluster/scriptvars.json"
tc_worker_runner_config_file = "/home/ltuser/taskcluster/worker-runner-config.yml"
hostname = socket.gethostname()

cmd_str = "start-worker %s" % tc_worker_runner_config_file
cmd_arr = cmd_str.split(" ")
# testing mode
# cmd_arr = sys.argv[1:]

# load json with env vars if it exists
scriptvars_json = None
if os.path.exists(scriptvars_json_file):
    with open(scriptvars_json_file) as json_file:
        scriptvars_json = json.load(json_file)
else:
    print("%s/INFO: '%s' does not exist." % (script_name, scriptvars_json_file))

# continue until we run a non-superseded task
while True:
    superseded = False
    rc = None

    # see https://bugzilla.mozilla.org/show_bug.cgi?id=1375514
    # prevents g-w from never reaching termination condition when we do our supersede reruns and device issues occur
    # https://github.com/taskcluster/generic-worker/blob/d3dda694d0031e8f1cd085f06c3b0f810321dac2/main.go#L485
    gw_resolved_count_file = "tasks-resolved-count.txt"
    if os.path.exists(gw_resolved_count_file):
        print("%s/INFO: removed gw_resolved_count_file at '%s'" % (script_name, gw_resolved_count_file))
        os.remove(gw_resolved_count_file)

    print("%s/INFO: command to run is: '%s'" % (script_name, " ".join(cmd_arr)))
    # run command
    proc = subprocess.Popen(
        cmd_arr,
        env=scriptvars_json,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    while rc is None:
        line = proc.stdout.readline().decode("UTF-8")
        stripped_line = line.rstrip()
        log_to_pt(stripped_line)
        if "has been superseded" in stripped_line.lower():
            superseded = True
        rc = proc.poll()
    sys.stdout.flush()
    # exit if the rc is non-zero (even if superseded) or if we've processed a real job
    # otherwise consume another task.
    if rc != 0 or not superseded:
        break
    log_to_pt(
        "%s/INFO: task was superseded, running again..." % script_name,
        print_to_screen=True,
    )

sys.exit(rc)
