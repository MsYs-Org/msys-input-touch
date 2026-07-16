#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
binary=${BINARY:-"$root/build/msys-input-touch-lvgl"}
for command in Xvfb xprop xwininfo; do
    command -v "$command" >/dev/null 2>&1 || exit 77
done
test -x "$binary"

fail_case() {
    reason=$1
    directory=$2
    echo "xvfb smoke: $reason" >&2
    for log in "$directory"/*.log; do
        if test -f "$log"; then
            echo "--- $(basename "$log") ---" >&2
            tail -n 120 "$log" >&2 || true
        fi
    done
    rm -rf "$directory"
    exit 1
}

run_case() {
    display=$1
    screen=$2
    x=$3
    y=$4
    width=$5
    height=$6
    tmp=$(mktemp -d)
    Xvfb "$display" -screen 0 "$screen" -nolisten tcp >"$tmp/xvfb.log" 2>&1 &
    xvfb_pid=$!
    sleep 0.25
    kill -0 "$xvfb_pid" 2>/dev/null || fail_case "$display Xvfb failed" "$tmp"
    DISPLAY="$display" "$binary" --display "$display" --output spi --visible \
        --ui "$root/ui/keyboard.xml" \
        --x "$x" --y "$y" --width "$width" --height "$height" \
        --run-ms 2100 </dev/null >"$tmp/app.log" 2>&1 &
    app_pid=$!
    window=
    attempt=0
    while test "$attempt" -lt 30; do
        window=$(DISPLAY="$display" xwininfo -root -tree 2>/dev/null |
            sed -n 's/^[[:space:]]*\(0x[0-9a-fA-F]*\).*"MSYS Touch Input LVGL".*/\1/p' |
            head -n 1)
        test -n "$window" && break
        sleep 0.05
        attempt=$((attempt + 1))
    done
    test -n "$window" || fail_case "$display window missing" "$tmp"
    identity=$(DISPLAY="$display" xprop -id "$window" _MSYS_APP_ID _MSYS_COMPONENT_ID _MSYS_WINDOW_ROLE)
    printf '%s\n' "$identity" | grep -q 'org.msys.input.touch' ||
        fail_case "$display app identity missing" "$tmp"
    printf '%s\n' "$identity" | grep -q 'keyboard-lvgl' ||
        fail_case "$display component identity missing" "$tmp"
    printf '%s\n' "$identity" | grep -q 'input-method' ||
        fail_case "$display role identity missing" "$tmp"
    geometry=$(DISPLAY="$display" xwininfo -id "$window")
    printf '%s\n' "$geometry" | grep -q "Width: $width" ||
        fail_case "$display width mismatch" "$tmp"
    printf '%s\n' "$geometry" | grep -q "Height: $height" ||
        fail_case "$display height mismatch" "$tmp"
    # Mapping can generate a late Expose.  Treat the surface as idle only after
    # the flush marker has settled, then verify it stays unchanged.
    stable=0
    previous=
    attempt=0
    while test "$attempt" -lt 30; do
        current=$(DISPLAY="$display" xprop -id "$window" _MSYS_LVGL_LAST_FLUSH)
        if test -n "$previous" && test "$current" = "$previous"; then
            stable=$((stable + 1))
            test "$stable" -ge 3 && break
        else
            stable=0
        fi
        previous=$current
        sleep 0.1
        attempt=$((attempt + 1))
    done
    test "$stable" -ge 3 || fail_case "$display flush marker did not settle" "$tmp"
    sleep 1.1
    current=$(DISPLAY="$display" xprop -id "$window" _MSYS_LVGL_LAST_FLUSH)
    test "$previous" = "$current" || fail_case "$display idle flush changed" "$tmp"
    wait "$app_pid" || fail_case "$display frontend failed" "$tmp"
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    rm -rf "$tmp"
}

trap 'jobs -p | xargs -r kill 2>/dev/null || true' EXIT HUP INT TERM
# Fixed display numbers make two otherwise independent probes interfere.  A
# process-derived high range remains isolated from the real :24 session and
# from concurrently running package checks.
display_base=$((1000 + ($$ % 20000)))
portrait_display=:$display_base
landscape_display=:$((display_base + 1))
bridge_display=:$((display_base + 2))
run_case "$portrait_display" 320x480x24 4 234 312 202
run_case "$landscape_display" 480x320x24 4 94 472 180

python=${PYTHON:-}
if test -z "$python"; then
    if command -v python3 >/dev/null 2>&1; then
        python=python3
    else
        python=/opt/msys/current/.runtime/python/bin/python3
    fi
fi
test -x "$python" || command -v "$python" >/dev/null 2>&1
sdk_root=${MSYS_SDK_ROOT:-"$root/../msys-sdk"}
if ! test -d "$sdk_root/msys_sdk" && test -d /opt/msys-dev/msys-sdk/msys_sdk; then
    sdk_root=/opt/msys-dev/msys-sdk
fi
test -d "$sdk_root/msys_sdk" || {
    echo "xvfb smoke: msys-sdk Python package missing: $sdk_root" >&2
    exit 1
}
tmp=$(mktemp -d)
Xvfb "$bridge_display" -screen 0 320x480x24 -nolisten tcp >"$tmp/xvfb.log" 2>&1 &
xvfb_pid=$!
sleep 0.25
kill -0 "$xvfb_pid" 2>/dev/null || fail_case "$bridge_display Xvfb failed" "$tmp"
DISPLAY="$bridge_display" MSYS_INPUT_LVGL_BINARY="$binary" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/files/app:$sdk_root" \
    "$python" -B "$root/files/app/lvgl_main.py" --standalone --visible \
    --mode zh --run-ms 2200 >"$tmp/bridge.log" 2>&1 &
bridge_pid=$!
bridge_window=
attempt=0
while test "$attempt" -lt 160; do
    bridge_window=$(DISPLAY="$bridge_display" xwininfo -root -tree 2>/dev/null |
        sed -n 's/^[[:space:]]*\(0x[0-9a-fA-F]*\).*"MSYS Touch Input LVGL".*/\1/p' |
        head -n 1)
    test -n "$bridge_window" && break
    sleep 0.05
    attempt=$((attempt + 1))
done
test -n "$bridge_window" || fail_case "$bridge_display bridge window missing" "$tmp"
wait "$bridge_pid" || fail_case "$bridge_display bridge failed" "$tmp"
kill "$xvfb_pid" 2>/dev/null || true
wait "$xvfb_pid" 2>/dev/null || true
rm -rf "$tmp"
trap - EXIT HUP INT TERM
echo "xvfb smoke: C bridge, portrait/landscape and idle dirty path ok"
