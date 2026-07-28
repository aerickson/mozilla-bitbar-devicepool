# mld: mozilla-lambdatest-devicepool

## Check private-cloud device availability

Use `lt_device_availability` with one or more LambdaTest device UDIDs or exact
phone model names. By default it opens an interactive dashboard with one row
per device, the update interval, next API check, elapsed wait time, and active
device count. Press `q` to quit. Add `--wait` to exit automatically once every
matched device reports `active`.

```shell
poetry run lt_device_availability RZCXC19G1DM
poetry run lt_device_availability RZCXC19G1DM RZCXC19G1DN --wait --interval 15
poetry run lt_device_availability RZCXC19G1DM --no-tui
```

When a phone model name is supplied, every matching physical device must be
active before `--wait` exits. `--no-tui` (and non-interactive terminals) emits
one compact status line for each API refresh instead.

## Pass environment variables to `lt_run_cmd` scripts

Use repeatable `--env NAME=VALUE` arguments to make values available to a
local script passed with `lt_run_cmd --script`. The script can read them as
ordinary environment variables alongside `DEVICE_SERIAL`.

```shell
poetry run lt_run_cmd --script ./collect.sh --device RZCXC19G1DM \
  --env RUN_LABEL=nightly --env RETRIES=3
```

Variable names must be shell-style names and cannot be repeated. Avoid placing
secrets directly on the command line, where they may be retained in shell
history or process listings.

Detects pending Taskcluster jobs and starts tasks at Lambdatest to handle them.

Lambdatest job launching is done via their Hyperexecute CLI tool (that handles the API requests).

## Configuration

Configuring `mld` requires creating environment variables and a yaml configuration file for Bitbar. See `config/lambdatest.yml`.

## Usage

```bash
mld --help

# run locally in debug mode (no LT API jobs started)
. ./lt_env.sh
mld --debug
```

## Deployment

### Environment Variables

We need to set the following variables. For the Mozilla deployment, this env var file is stored in 1Password.

```bash
# to be able to find the hyperexecute bin in `.`
export PATH=".:$PATH"

# do not use your email, use the short username
#   - known LT issue
export LT_USERNAME=
export LT_ACCESS_KEY=

# taskcluster client credentials
export gecko_t_lambda_alpha_a55=
export gecko_t_lambda_perf_a55=

# sentry creds
export SENTRY_DSN=
```

### getting the hyperexecute binary

See https://www.lambdatest.com/support/docs/hyperexecute-cli-run-tests-on-hyperexecute-grid/.


### Systemd Unit Installation

```bash
sudo cp service/lambdatest.service /etc/systemd/system/lambdatest.service
sudo systemctl daemon-reload
```

### Service Logs

To follow the log output of the lambdatest service, run:

`sudo journalctl _SYSTEMD_UNIT=lambdatest.service --follow`

## Job Tracing

Linking Taskcluster jobs to Lambdatest jobs bidrectionally.

### LT->TC

Go to the 'Post Steps' tab of the selected job in the LambdaTest Hyperexecute UI (https://hyperexecute.lambdatest.com/hyperexecute/jobs). Reveal the 'Post' step's output. You should see text similar to:

generic-worker-metadata.json contents:

```json
{
  "lastTaskUrl": "https://firefox-ci-tc.services.mozilla.com/tasks/Ym_uHmb0TmC_f45Wv8uw3w/runs/0"
}
```

### TC->LT

Search for `lambdatest` in the Taskcluster job's log. You should find content similar to:

```
[task 2025-06-02T22:27:14.576Z] LambdaTest Job Number: 21724
[task 2025-06-02T22:27:14.576Z] LambdaTest Job URL: https://hyperexecute.lambdatest.com/hyperexecute/task?jobId=0e05dbf5-7cec-44a2-a63c-1d8c01525009&link=&logType=&order=&scenario_search_text=&taskId=HYPL-1611945-1748903159145866048AYB&taskStatus=
```

## Development Notes

### Differences between MBD and MLD

#### Device Pools: Server-side vs Client-side

MBD submits Bitbar tasks to several Bitbar projects. The projects map to our Taskcluster worker pools.

At Lambdatest, we can't easily create arbitary groups of devices so MLD must manage them.

### Execution Loop Overview

```bash
# overview:
#   1. do configuration / load config data
#   2. in loop:
#     a. update tc queue counts
#     b. update lt job status (how many running per group)
#     c. update lt device status (how many devices in each state per group)
#     d. calculate number of jobs to start
#     e. start jobs for the appropriate tc queue with selected devices
```

### Execution Loop Implementation Details

Ordered by complexity and date implemented.

1. starts a single job, foreground, targets device_type-os_version
  - replica of jmaher's PoC
2. starts multiple jobs, --no-track, foreground, targets device_type-os_version
  - works, current default
  - known issues
    - slow start problem: if 60 jobs come in, will take awhile to have 100% utilization (takes awhile to start jobs)
3. starts a single job with hyperexecute yaml concurrency, --no-track, foreground, targets device_type-os_version
  - didn't work (theoretically should, check with LT about my understanding of field), needs more investigation.
4. (CURRENTLY IMPLEMENTED) starts multiple jobs, --no-track, background, targets single device (device_type-os_version and udid)
  - need to track specific free devices in app
  - enables creation of multiple device pools per device type
