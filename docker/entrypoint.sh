#!/bin/sh
# Make sure the data folder (usually ./data from the host) is writable, then run as the unprivileged user.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p "$RECRUITLY_DATA_DIR"
    if [ "$(stat -c %u "$RECRUITLY_DATA_DIR")" != "1000" ]; then
        chown -R recruitly:recruitly "$RECRUITLY_DATA_DIR"
    fi
    exec setpriv --reuid=recruitly --regid=recruitly --init-groups "$@"
fi
exec "$@"
