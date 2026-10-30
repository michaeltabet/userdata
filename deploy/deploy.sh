#!/usr/bin/env bash
# shellcheck disable=SC2029  # Remote commands are built locally on purpose.
# Copyright 2026 Michael Tabet
# SPDX-License-Identifier: MIT
#
# Builds the USERDATA image on testing, loads it on vm1, and starts it.
# Usage: deploy/deploy.sh image | up | all
set -euo pipefail

readonly BUILD_HOST="testing"
readonly RUN_HOST="vm1"
readonly RUN_DIR="/srv/stack/userdata"
version="$(git -C "$(dirname "$0")/.." rev-parse --short HEAD)"
readonly version

build_image() {
  local build_dir="/tmp/userdata-build-${version}"
  git -C "$(dirname "$0")/.." archive --format=tar HEAD \
    | ssh "${BUILD_HOST}" "rm -rf ${build_dir} && mkdir -p ${build_dir} && tar -x -C ${build_dir}"
  ssh "${BUILD_HOST}" "docker build -q -f ${build_dir}/deploy/Dockerfile -t userdata:${version} ${build_dir} && rm -rf ${build_dir}"
  ssh "${BUILD_HOST}" "docker save userdata:${version}" | ssh "${RUN_HOST}" "docker load -q"
}

start() {
  ssh "${RUN_HOST}" "mkdir -p ${RUN_DIR} /srv/stack/funnel/userdata /srv/data/userdata && chown 10001:10001 /srv/data/userdata && chmod 700 /srv/data/userdata"
  scp -q "$(dirname "$0")/compose.yml" "$(dirname "$0")/funnel-userdata.json" "${RUN_HOST}:${RUN_DIR}/"
  # The funnel key is read on vm1 from the stack's secrets file and passed
  # to compose through the environment only; it never leaves vm1.
  ssh "${RUN_HOST}" "cd ${RUN_DIR} && TS_FUNNEL_AUTHKEY=\$(sed -n 's/^TS_FUNNEL_AUTHKEY=//p' /srv/basci/secrets.env) USERDATA_VERSION=${version} docker compose up -d"
}

main() {
  case "${1:-all}" in
    image) build_image ;;
    up) start ;;
    all)
      build_image
      start
      ;;
    *)
      echo "usage: $0 image|up|all" >&2
      exit 2
      ;;
  esac
}

main "$@"
