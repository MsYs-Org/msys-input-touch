#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
machine=$(${CC:-cc} -dumpmachine 2>/dev/null || uname -m)
case "$machine" in
    aarch64*|arm64*) ;;
    *) echo "build requires an AArch64 target compiler, got: $machine" >&2; exit 2 ;;
esac
make -j1 clean
make -j1 all
make -j1 stage
test -x files/bin/msys-input-touch-lvgl
files/bin/msys-input-touch-lvgl --describe
