#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
binary=${BINARY:-"$root/build/msys-input-touch-lvgl"}
for command in Xvfb xprop xwininfo; do
    command -v "$command" >/dev/null 2>&1 || exit 77
done
test -x "$binary"

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
    test -n "$window"
    identity=$(DISPLAY="$display" xprop -id "$window" _MSYS_APP_ID _MSYS_COMPONENT_ID _MSYS_WINDOW_ROLE)
    printf '%s\n' "$identity" | grep -q 'org.msys.input.touch'
    printf '%s\n' "$identity" | grep -q 'keyboard-lvgl'
    printf '%s\n' "$identity" | grep -q 'input-method'
    geometry=$(DISPLAY="$display" xwininfo -id "$window")
    printf '%s\n' "$geometry" | grep -q "Width: $width"
    printf '%s\n' "$geometry" | grep -q "Height: $height"
    sleep 0.65
    first=$(DISPLAY="$display" xprop -id "$window" _MSYS_LVGL_LAST_FLUSH)
    sleep 0.4
    second=$(DISPLAY="$display" xprop -id "$window" _MSYS_LVGL_LAST_FLUSH)
    test "$first" = "$second"
    wait "$app_pid"
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
    rm -rf "$tmp"
}

trap 'jobs -p | xargs -r kill 2>/dev/null || true' EXIT HUP INT TERM
run_case :96 320x480x24 4 234 312 202
run_case :95 480x320x24 4 94 472 180

python=${PYTHON:-}
if test -z "$python"; then
    if command -v python3 >/dev/null 2>&1; then
        python=python3
    else
        python=/opt/msys/current/.runtime/python/bin/python3
    fi
fi
test -x "$python" || command -v "$python" >/dev/null 2>&1
tmp=$(mktemp -d)
Xvfb :94 -screen 0 320x480x24 -nolisten tcp >"$tmp/xvfb.log" 2>&1 &
xvfb_pid=$!
sleep 0.25
DISPLAY=:94 MSYS_INPUT_LVGL_BINARY="$binary" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$root/files/app:$root/../msys-sdk" \
    "$python" -B "$root/files/app/lvgl_main.py" --standalone --visible \
    --mode zh --run-ms 2200 >"$tmp/bridge.log" 2>&1 &
bridge_pid=$!
bridge_window=
attempt=0
while test "$attempt" -lt 160; do
    bridge_window=$(DISPLAY=:94 xwininfo -root -tree 2>/dev/null |
        sed -n 's/^[[:space:]]*\(0x[0-9a-fA-F]*\).*"MSYS Touch Input LVGL".*/\1/p' |
        head -n 1)
    test -n "$bridge_window" && break
    sleep 0.05
    attempt=$((attempt + 1))
done
test -n "$bridge_window"
wait "$bridge_pid"
kill "$xvfb_pid" 2>/dev/null || true
wait "$xvfb_pid" 2>/dev/null || true
rm -rf "$tmp"
trap - EXIT HUP INT TERM
echo "xvfb smoke: C bridge, portrait/landscape and idle dirty path ok"
