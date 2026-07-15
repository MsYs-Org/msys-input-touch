# MSYS Touch Input

Current source version: `0.1.12`.

This repository is an independent, replaceable `input-method` role for MSYS.
It is a normal supervised component, not PID 1 and not a desktop input bus. It
uses Python's standard library, Tk, the MSYS SDK, X11, and an XTest library
already present on normal Xorg systems. It does not use systemd, D-Bus, IBus,
Fcitx, pip packages, or a target package manager.

The provider is `on-demand`: it consumes no resident Python/Tk process until a
caller addresses `role:input-method`. It intentionally has no RPC-based idle
timeout because touch/key activity is not an mIPC call; reclaiming on that
timer could terminate a keyboard while the user is still typing. Once hidden,
the provider completes its short animation and exits normally, so the next
`show` starts a fresh on-demand generation instead of retaining Tk/Python
memory. Its on-demand restart policy is deliberately `never`: an expected
hide requests Core's planned component-stop path, so it is not reclassified as
a failed control channel or respawned;
the next role call starts a new generation.

An operator-only `start` does not imply `show`. A hidden generation, or a
`show` request without a generation-checked editable target, is released after
750 ms. A valid show cancels that timer; every later hide (including Home and
focus loss) arms it again.

## Design boundary

- `role:input-method` owns show/hide/toggle/mode control.
- The floating overlay starts hidden, fits a 320x480 display, avoids the
  navigation inset, can be dragged by its header, and never takes a global Tk
  grab.
- Before mapping, the provider remembers the focused top-level X11 window and
  resolves it to the window manager's generation-checked stable ID. Every key
  restores that target through typed `focus_window` before injection when
  needed. A stale/destroyed target fails visibly instead of focusing a reused
  raw XID.
- While visible, it passively samples X11 focus and root pointer state; a new
  primary touch outside the panel hides immediately, while focus-only migration
  must remain stable for three samples so transient chrome cannot flash-close
  the keyboard. Persistent loss of the target also hides without restoring stale
  focus. It subscribes
  to Core's terminal lifecycle transition for that exact component/identity,
  so application close/Back cannot leave a stranded keyboard overlay.
- Key injection dynamically loads `libX11`/`libXtst`. If XTest is unavailable,
  an already-installed `xdotool` can be used through a fixed argv with no
  shell. There is no automatic download or installation.
- English, numbers, and common symbols are direct key events. Chinese input is
  a deliberately small bounded Pinyin composer. Selecting a candidate owns the
  X11 clipboard briefly and injects Ctrl+V, which works across Tk, Qt, GTK, and
  Electron more consistently than toolkit-specific preedit APIs.
- The package-local `msys.pinyin-dictionary.v1` JSON is replaceable through
  `MSYS_INPUT_DICTIONARY`. It is capped at 2,048 entries, 16 candidates per
  entry, and short strings; this is an extensibility point, not a claim of a
  full desktop IME dictionary.
- Drag updates are clamped to the current screen and coalesced to one geometry
  update per 16 ms. Show/hide uses a short slide without alpha-redrawing the
  entire keyboard, which keeps feedback while reducing SPI damage traffic.

## Application integration

An application should show the selected provider when one of its editable
fields receives focus, and hide it on a terminal submit or when leaving the
editing view:

```python
from msys_sdk import MsysClient

MsysClient.public_call(
    "role:input-method",
    "show",
    {"mode": "zh"},
    timeout=3,
)

MsysClient.public_call("role:input-method", "hide", {}, timeout=3)
```

X11 has no safe cross-toolkit signal that distinguishes a text widget from a
non-text widget inside the same foreign application window. A pointer press
outside the floating panel is therefore treated as leaving edit mode. Apps
that support switching directly between text fields should issue `show` again
from their own field-focus callback; this keeps the role equally usable from
Tk, Qt, Electron, and native X11 without a framework-specific input bus.

Declare `mipc.call:role:input-method` in the calling component. Do not address
`org.msys.input.touch:keyboard` directly: role selection is what keeps the IME
replaceable. See `docs/input-method-v1.md` for the complete bounded API.

## Development

Run the tests without a display:

```sh
PYTHONPATH=files/app:../msys-sdk python3 -m unittest discover -s tests -v
```

For an X11-only UI preview outside supervision:

```sh
DISPLAY=:24 PYTHONPATH=files/app:../msys-sdk \
  python3 files/app/main.py --standalone --visible --mode zh
```

Standalone preview can draw and compose without Core. Injection remains
disabled until a generation-checked target can be resolved through a running
`role:window-manager`.

Build it with the normal package flow and SDK overlay; no target-side package
manager is involved:

```sh
PYTHONPATH=../msys-tools python3 -m msys_tools.dev package build \
  . --root .. --output ../dist \
  --overlay msys-sdk/msys_sdk=files/app/msys_sdk
```

The keyboard imports the same `msys_sdk.ui_fonts` policy as the shell and
applications. The overlay keeps the archive runnable in isolation without a
daemon, `pip`, or target package manager.
