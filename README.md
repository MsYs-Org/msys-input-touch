# MSYS Touch Input

Current source version: `0.4.2`.

Version 0.4.2 starts the native frontend's bounded `--run-ms` preview clock
after XML, fonts, and the initial show request are prepared. On a busy target,
the previous test-only clock could expire while the idle probe was observing a
perfectly stable window and misreport its destruction as an idle repaint. This
does not add a runtime timer or change production rendering.

Version 0.4.1 keeps the selected `en`, `zh`, `numeric`, or `symbols` mode in
the package-owned `MSYS_APP_STATE_DIR/input-mode.conf`. Both the default LVGL
provider and Tk fallback load the same tiny state file on every on-demand
generation, and local mode keys plus the existing `show({mode})` and
`set_mode({mode})` calls update it atomically. If no valid saved mode exists,
`MSYS_LOCALE=zh-*` selects Chinese and every other locale selects English.
There is no resident preference service, D-Bus dependency, or polling loop;
an unavailable state volume never prevents typing or focus dismissal.

Version 0.4.0 makes `keyboard-lvgl` the selected `input-method` role provider;
the Tk presenter remains installed at lower priority as an explicit fallback.
The existing generation-checked focus capture and stable focus-loss guard are
shared unchanged, so Tk, Qt and Electron top-level X11 windows use the same
show, outside-touch dismissal and injection path. While visible, a live X11
screen-size change rebuilds only the fixed-size LVGL child surface and keeps
the model, real Pinyin candidates, clipboard owner and focus generation alive.

Version 0.3.0 moves the LVGL panel skeleton to a package-owned dynamic XML
document and makes the shared light palette the default.  C still creates the
variable key rows and candidates and owns input events; XML owns the header,
composition strip, scrollable candidate slot and key slot.  The old compiled
layout remains a fallback when no `--ui` path is supplied.  The dynamic panel
measures about 6.0 MiB PSS on the 320x480 AArch64 target and remains idle with
zero periodic flushes.

Version 0.2.0 added an optional `keyboard-lvgl` provider while retaining the
existing Python/Tk `keyboard` as the then higher-priority default. The
provider uses a small C/LVGL window connected to a Python business bridge:
focus capture, lifecycle dismissal, the bounded Pinyin model, XTest/xdotool
injection and the hidden Tk clipboard owner stay unchanged.  This preserves
the Qt, Tk and Electron Ctrl+V path for Chinese candidates without making the
renderer toolkit-specific.  The LVGL surface uses the replaceable shared font
provider, portrait/landscape geometry at process start, local key/candidate
feedback and bounded show/hide motion.  It has no periodic invalidation while
hidden or idle.

Version 0.1.17 gives navigation dismissal an explicit no-focus-restore
contract, so Back cannot immediately reopen the keyboard through the old
editable target. Version 0.1.16 moved the non-Tk focus probe to the beginning
of a cold generation, before importing Tk, opening the host window, loading
fonts, or parsing the Pinyin dictionary. Those startup costs now overlap the
window manager lookup rather than preceding it.

Version 0.1.15 overlaps the first generation-checked focus lookup with the
component hello/ready handshake and prepares the still-withdrawn stable Tk
panel on the first idle turn after readiness. The provider acknowledges
`show` before either operation completes, coalesces only an immediately
repeated lookup for the same native focus, and logs bounded `startup_ms` and
`show_to_map_ms` probes on the first map. The cache expires after one second,
so the existing 15-second warm grace never turns into stale focus authority.
The component remains on-demand and adds no boot-time resident process.

Version 0.1.14 unmaps the keyboard immediately but keeps an already-used
process warm for a bounded 15-second grace, avoiding repeated Tk cold starts
while moving between fields without adding boot-time RSS.

Version 0.1.13 is packaged with the IPC-first lazy SDK and the profile's
font-doctor-verified CJK family.  A cold on-demand generation therefore avoids
loading unrelated SDK UI modules and does not enumerate the target's full Xft
font catalog before it can become ready.

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
15 seconds by default. The panel is unmapped immediately, while the bounded
warm process avoids another Python/Tk cold start when the user moves to a
nearby field. `MSYS_INPUT_WARM_MS` can tune the grace from 750 ms to 60 seconds
without adding baseline RSS. A valid show cancels that timer; every later hide (including Home and
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
non-text widget inside the same foreign application window. The SDK Tk binding
therefore maps widget FocusIn/FocusOut to role `show`/`hide`; Qt and Electron
applications do the same from their ordinary field-focus callbacks. Once
shown, the provider captures the framework-independent top-level XID and
automatically closes after stable focus loss, target lifecycle termination, or
a pointer press outside the panel. This avoids a framework-specific input bus
and avoids showing a keyboard for every non-editable application window.

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
