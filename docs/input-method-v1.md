# `input-method` role v1

The provider is addressed as `role:input-method`. Calls use ordinary mIPC
objects and return `msys.input-method-state.v1` payloads.

## Methods

```text
show({mode?})
hide({})
toggle({mode?})
set_mode({mode})
status({})
```

`mode` is one of `en`, `zh`, `numeric`, or `symbols`. Every successful reply
contains:

```json
{
  "ok": true,
  "schema": "msys.input-method-state.v1",
  "visible": true,
  "mode": "zh",
  "layout": "letters",
  "locale": "zh-CN",
  "shift": false,
  "composition": "nihao",
  "backend": {"name": "xtest", "available": true},
  "has_focus_target": true
}
```

Unknown methods and invalid modes return an mIPC error; they do not change the
current state. This role deliberately does not expose an RPC that injects
arbitrary text. Applications request visibility and mode, while actual input
still requires a local touch on the keyboard.

An explicit mode supplied to `show`, `toggle`, or `set_mode`, and a local mode
key, becomes the default for the next on-demand generation. The stock LVGL and
Tk providers share `MSYS_APP_STATE_DIR/input-mode.conf`; this persistence is
an implementation detail and does not add fields or methods to the v1 RPC.
When that file is absent or invalid, a Chinese `MSYS_LOCALE` selects `zh` and
all other locales select `en`.

## Automatic dismissal

The stock touch implementation also hides locally, without sending a focus
restore, when one of these observable conditions occurs:

- a new primary pointer press lands outside its panel (including the Home or
  Back navigation region);
- X11 focus remains on another non-keyboard surface for three samples, or
  remains unavailable for three samples (single transient focus changes are
  ignored);
- a matching `msys.lifecycle.transition` announces `closing`, `closed`, or
  `failed` for the target component/identity.

The default provider is `org.msys.input.touch:keyboard-lvgl`; the Tk provider
is retained as a lower-priority fallback. The component has no Core RPC idle
timeout because the user can type for a
long time without another RPC. Instead it exits normally shortly after a hide
animation, preserving true `on-demand` memory behavior. X11 cannot expose a
portable semantic "this is a text control" signal for arbitrary Tk/Qt/Electron
apps, so an application that moves between text fields should call `show`
again from its own focus callback. Its manifest uses `restart: never`: Core
must treat the next role call as the wake-up path, rather than respawning an
intentionally hidden keyboard after its control socket closes.

An explicit component `start` does not map a keyboard. The stock provider
releases that initial hidden generation after the configured bounded warm
grace unless a valid `show` request arrives. A `show` without a
generation-checked focus target is rejected
back into the same hidden-release path, and every Home/focus-loss hide re-arms
that release timer.

The contract is toolkit-neutral. Tk SDK focus bindings and Qt/Electron field
focus callbacks all call the same role. X11 child focus is normalized to the
catalogued top-level window before injection, and a live portrait/landscape
screen-size change reconfigures only the LVGL surface. A future Qt, C/C++,
Electron, Wayland, or hardware-keyboard implementation can replace this
provider without changing application calls.
