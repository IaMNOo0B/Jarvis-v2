# system

Small system tools: status, volume, clipboard, brightness, window list.
Pure Python stdlib (ctypes for Windows APIs). No pyautogui / pywin32 / pycaw.

## Honesty notes (what is real, what is not, and why)

- **`system_status`** — REAL. Battery via `GetSystemPowerStatus` (Windows)
  or `/sys/class/power_supply` (Linux); RAM via `GlobalMemoryStatusEx`
  (Windows) or `/proc/meminfo` (Linux); CPU count via `os.cpu_count()`,
  load via `os.getloadavg()` where the OS provides it (null on Windows —
  reported as null, never invented).
- **`volume_set`** — REAL, via **key synthesis** (`VK_VOLUME_UP/DOWN/MUTE`
  through `keybd_event`), the same path the field uses when pycaw is off
  the table (see megascan team2-desktop.md). Consequence, stated plainly:
  there is **no level readback and no undo** — a set is N presses blind.
- **`volume_get`** — **UNAVAILABLE on Windows.** True master-volume level
  requires the CoreAudio COM API (`IAudioEndpointVolume`), which is not
  practical in pure stdlib ctypes; key events cannot read a level. Returns
  `ok=false` with the reason rather than a made-up number. On Linux it
  really works when `amixer` is installed (parsed, not guessed).
- **`clipboard_get` / `clipboard_set`** — REAL. Windows: `user32`
  OpenClipboard / CF_UNICODETEXT via ctypes. Linux: `xclip`/`xsel` when
  present, else honest `ok=false`. `clipboard_get` output is **DCL-scanned
  and redacted** before it leaves the tool; `clipboard_set` refuses
  SECRET-class text (never plant a credential on the clipboard silently).
- **`brightness_get` / `brightness_set`** — **NOT IMPLEMENTED.** Windows
  brightness is WMI (`WmiMonitorBrightness`) — WMI COM is not stdlib, and
  the only stdlib path (PowerShell `-EncodedCommand`) is blocklisted by
  v2's own shell policy for commands. `brightness_set` is tier-2 because it
  *will* be a mutation once implemented. Both return `ok=false` with the
  reason. Guard logic is unit-tested; the body is the stub.
- **`window_list`** — REAL on Windows (top-level visible windows via
  `EnumWindows` / `GetWindowTextW`, ctypes). Honest `ok=false` elsewhere.

## Permissions

- tier-1 (read): `system_status`, `volume_get`, `clipboard_get`,
  `brightness_get`, `window_list`
- tier-2 (mutating): `volume_set`, `clipboard_set`, `brightness_set`

Capabilities (closed vocabulary): `clipboard.read`, `exec`.
Note: the closed capability vocabulary has no `clipboard.write`; the write
tool additionally declares `exec` for its Linux backend.

## Evidence

Every handler logs what it did (ctx.log), including which backend answered
and why a tool returned unavailable — silence is never dressed as success.
