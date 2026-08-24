#!/usr/bin/env bash

until nr-gnb -c /corefuzzer_deps/ueransim/config/open5gs-gnb.yaml; do
    echo "nr-gnb crashed with exit code $?.  Respawning.." >&2
    sleep 1
done
