#!/bin/bash

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

set -e

source ~/.bashrc

echo "ls -la /"
ls -la /
if [[ -e /test ]]; then
    echo "ls -la /test"
    ls -la /test
fi

CONF_PATH='/home/ltuser/taskcluster'
export ED25519_PRIVKEY="$CONF_PATH/ed25519_private_key"
export GOOGLE_APPLICATION_CREDENTIALS="/etc/bitbar/stackdriver_credentials.json"
# generic-worker docker hack.
# see https://github.com/taskcluster/generic-worker/issues/151
export USER=root

# write a limited set of environment variables to file
entrypoint.py

cd $HOME
generic-worker new-ed25519-keypair --file $ED25519_PRIVKEY
# chown worker $ED25519_PRIVKEY
envsubst < $CONF_PATH/worker-runner-config.yml.template > $CONF_PATH/worker-runner-config.yml

mkdir -p /home/ltuser/taskcluster/.android/
# bitbar mounts this file into root's homedir, but with g-w adb
# is looking for it worker's homedir
ln -sf /root/.android/adbkey /home/ltuser/taskcluster/.android/adbkey || true

# run_gw.py
