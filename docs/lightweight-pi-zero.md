# Running Klipper on a Raspberry Pi Zero W (KIAUH) — Lightweight Guide

Target: **Raspberry Pi Zero W** (not the Zero 2 W). Single-core BCM2835
(ARM1176JZF-S, `armv6l`), ~1 GHz, **512 MB RAM**, 32-bit only.

This document explains what KIAUH installs by default, which parts are heavy
on a Zero W, and what lighter alternatives exist — including the
`nginx → lighttpd` and `systemd → runit` ideas, with an honest verdict on each.

---

## 1. What KIAUH is and how it installs things

KIAUH ("Klipper Installation And Update Helper") is a Python TUI (plus a
headless CLI) that installs and manages the Klipper firmware-ecosystem stack.
`kiauh.sh` bootstraps Python 3.8+ and calls `kiauh/main.py`, which drives the
menus. KIAUH itself **never runs as root** — it shells out to `sudo`
(~98 call sites) for `apt-get`, `systemctl`, nginx config writes, `usermod`,
and `tee`.

The consistent install pattern for every component is:

```
git clone  →  python virtualenv  →  systemd unit  →  Moonraker update-manager section
```

Component configuration (ports, repos, toggles) lives in `kiauh.cfg`, which is
auto-created from `default.kiauh.cfg` on first run
(`kiauh/core/settings/kiauh_settings.py`).

Two pieces of infrastructure are **hard-wired** and shared by nearly every
component:

| Infra | How KIAUH depends on it | Ref count |
|---|---|---|
| **systemd** | Writes units to `/etc/systemd/system`, drives them via `systemctl` (`cmd_sysctl_service` / `cmd_sysctl_manage`), and **discovers instances by scanning `/etc/systemd/system`**. Moonraker additionally gets a polkit rule + `moonraker-admin` supplementary group so it can restart Klipper *through* systemd. | 73 |
| **nginx** | The only web server (0 hits for lighttpd/apache/caddy/thttpd in the code). Configs in `/etc/nginx/sites-available|enabled` plus `conf.d/{upstreams,common_vars}.conf`; `nginx` is restarted after UI installs. | 149 |

---

## 2. Services KIAUH installs (the default stack)

| # | Component | Role | Install dir | systemd unit | Weight on a Zero W |
|---|---|---|---|---|---|
| 1 | **Klipper** | Firmware host (MCU controller) | `~/klipper` + venv `~/klippy-env` | `klipper.service` (`klipper-<suffix>.service` for multi) | **Low** — one Python process |
| 2 | **Moonraker** | HTTP/WebSocket API (Tornado) | `~/moonraker` + venv `~/moonraker-env` | `moonraker.service` (port 7125) | **Medium** — heaviest Python service |
| 3 | **Mainsail** | Web UI (static files) | `~/mainsail` | none (served by **nginx**, port 80) | Low, but gzip costs CPU |
| 4 | **Fluidd** | Web UI (static, lighter than Mainsail) | `~/fluidd` | none (nginx) | Low |
| 5 | **Mainsail/Fluidd-Config** | Klipper cfg repos, symlinked into `printer.cfg` | `~/printer_data/config` | none | ~nil |
| 6 | **KlipperScreen** | Touchscreen GUI (PyQt + X11) | `~/KlipperScreen` + venv `~/.KlipperScreen-env` | `KlipperScreen.service` | **Heavy — skip on Zero W** |
| 7 | **Crowsnest** | Webcam streaming (uStreamer) | `~/crowsnest` | `crowsnest.service` + logrotate | **CPU-heavy** (video encode) |
| 8 | **Extensions** (16, optional) | Various | varies | varies | see §4.4 |

**Global dependencies** installed on first use (`core/constants.py`):
`git wget curl unzip dfu-util python3-virtualenv`.

**Dependency sources** (all pulled at install time, not vendored):
- Klipper: `klipper/scripts/install-ubuntu-22.04.sh` (`PKGLIST=`) + `pkg-config`.
- Moonraker: `moonraker/scripts/system-dependencies.json` (parsed by
  `components/moonraker/utils/sysdeps_parser.py`), **plus** `moonraker-speedups.txt`
  (numpy) when `optional_speedups: True` — **this is the default**.
- Crowsnest: its own `system-dependencies.json` (v5) / install script (v4).

---

## 3. What is actually heavy on a Pi Zero W

The bottleneck is **CPU, not RAM**, and it's a single-core ARMv6.

1. **Moonraker** — the async API server is the constant CPU consumer, made
   worse by the default `optional_speedups: True` pulling in numpy.
2. **nginx gzip** — the shipped template even says
   `# disable this section on smaller hardware like a pi zero`. Compressing on
   the single core costs more than it saves on a LAN.
3. **Crowsnest** — encoding a camera stream on one ARMv6 core is the single
   biggest CPU spike.
4. **KlipperScreen** — Qt + an X server will not be pleasant on 512 MB.
5. **Every extra venv** — Klipper, Moonraker, KlipperScreen, Crowsnest each get
   their own Python virtualenv, duplicating site-packages on disk and in RAM.

systemd and nginx, by contrast, are **not** the pain points (see §4.2 / §4.1).

---

## 4. Lightweight alternatives

### 4.1 `nginx → lighttpd` — ✅ worth doing

The nginx config does four jobs that lighttpd can do natively:

| nginx | lighttpd equivalent |
|---|---|
| static files + `try_files` + gzip | `server.document-root` + `mod_compress` |
| `/websocket` upgrade | `mod_wstunnel` (lighttpd ≥ 1.4.46) |
| `/printer|/api|/access|/machine|/server` → Moonraker | `mod_proxy` |
| `/webcamN/` → mjpgstreamer | `mod_proxy` |

A minimal translation of KIAUH's `assets/nginx_cfg`:

```lighttpd
server.modules += ( "mod_compress", "mod_proxy", "mod_wstunnel" )
server.document-root = "/home/USER/mainsail"
server.port = 80
compress.cache-dir = "/var/cache/lighttpd/compress"
compress.filetype = (
  "text/plain","text/css","text/xml","text/javascript",
  "application/javascript","application/json","application/xml"
)

# static UI
url.rewrite-if-not-file = ( "^/(.*)$" => "/index.html" )

# websocket to Moonraker
$HTTP["url"] =~ "^/websocket" {
  wstunnel.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 7125 ) ) )
  wstunnel.frame-type = "text"
}

# API to Moonraker
$HTTP["url"] =~ "^(/printer|/api|/access|/machine|/server)" {
  proxy.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 7125 ) ) )
}

# webcam to crowsnest/ustreamer
$HTTP["url"] =~ "^/webcam" {
  proxy.server = ( "" => ( ( "host" => "127.0.0.1", "port" => 8080 ) ) )
}
```

**Caveat:** KIAUH hardcodes nginx, so there are two paths:
1. **Hand-roll** — let KIAUH install Mainsail/Fluidd (the static files), then
   ignore/remove its nginx config and drop in the lighttpd config above.
2. **Patch KIAUH** — add a `lighttpd` web-server backend. The touch-points are
   contained: `core/constants.py` paths, the `NGINX_*` constants, and the
   `copy_*_nginx_cfg` / `create_nginx_cfg` / `cmd_sysctl_service("nginx")`
   calls in `components/webui_client/client_utils.py` and
   `web_client_setup_service.py`. Reasonable feature, but it's code, not config.

**Idle savings are modest** (lighttpd ~2–3 MB vs nginx ~5–10 MB) — the real win
is dropping gzip, which applies to *either* server.

### 4.2 `systemd → runit/s6` — ❌ not worth it

This one I recommend **against**, and it's the most important finding here.

- systemd is hard-wired into KIAUH: it writes `.service` units, calls
  `systemctl` everywhere, **scans `/etc/systemd/system` to discover Klipper/
  Moonraker instances**, and Moonraker is configured with a polkit rule +
  `moonraker-admin` group to restart services *via* systemd.
- Raspberry Pi OS ships systemd as PID1. Swapping in runit/s6 means a
  nonstandard OS **and** a fork-level rewrite of KIAUH (unit templates → run
  scripts, the systemctl wrappers, the instance-discovery scan, and the polkit
  integration).
- The payoff is a few MB of PID1 memory. On a 512 MB Zero W the *services*
  KIAUH launches — not PID1 — are what matter. This is a high-effort,
  low-return change.

**Do this instead:** keep systemd, but *trim* it — KIAUH already masks
`brltty` / `brltty-udev` / `ModemManager` during Klipper install
(`components/klipper/klipper_utils.py`). Also disable bluetooth and avahi
(`systemctl disable --now bluetooth avahi-daemon`) on a headless printer.

### 4.3 Higher-impact slimming (do these first)

| Change | How | Why |
|---|---|---|
| **Drop Moonraker speedups** | set `optional_speedups: False` in `kiauh.cfg` | avoids numpy — pure CPU/RAM win |
| **One web UI** | install Fluidd only (lighter than Mainsail) | fewer static files, one nginx/lighttpd server block |
| **No KlipperScreen** | don't install it; use a phone/PC browser | Qt + X11 is the biggest avoidable load |
| **Disable gzip** | comment out the `gzip on;` block (nginx) / drop `mod_compress` (lighttpd) | single-core compression costs more than it saves on LAN |
| **Skip input-shaper deps** | don't run Advanced → Input Shaper | pulls numpy + matplotlib + libopenblas |
| **Webcam off-device** | run Crowsnest/ustreamer on a second Pi, or 480p/1 fps | video encode dominates single-core CPU |
| **No Docker extensions** | avoid Spoolman (Docker) | Docker on armv6 is heavy and flaky |
| **Lighter base OS** | Raspberry Pi OS **Lite 32-bit** (the only armv6 option), or **DietPi** | fewer background services |
| **Swap + modest overclock** | `dphys-swapfile`, `config.txt` `arm_freq=1000` | 512 MB is tight during builds |

### 4.4 ARMv6 gotchas (Pi Zero W specifics)

Several "cloud" extensions will not run regardless of KIAUH, because the
Zero W is **ARMv6, 32-bit only** and vendors have dropped armv6 prebuilt
binaries (Go, Node, `cloudflared`, Docker images). Assume these are
unavailable or self-compile: **Moongate** (`cloudflared`), **Spoolman**
(Docker), **Obico / OctoEverywhere** client binaries, **DroidKlipp**. The
text-based extensions (gcode_shell_cmd, KAMP, TMC autotune, klipper-backup,
mainsail-theme) are fine — they're just config files.

---

## 5. Recommended minimal profile

For a headless Klipper host on a Pi Zero W:

- **OS:** Raspberry Pi OS Lite (32-bit) or DietPi; disable bluetooth + avahi.
- **KIAUH install:** Klipper → Moonraker → **Fluidd** (+ Fluidd-Config).
- **`kiauh.cfg`:** `optional_speedups: False`.
- **Web server:** lighttpd (hand-rolled config from §4.1), gzip off.
- **Skip:** KlipperScreen, Crowsnest (use a second Pi for the camera, or
  leave the camera out), input-shaper deps, all Docker/cloud extensions.
- **Tune:** `dphys-swapfile` for the Klipper firmware build; overclock to
  1 GHz if stable.

Resulting long-running processes: `klipper.service`, `moonraker.service`,
`lighttpd` — three processes, well within 512 MB.

---

## 6. Reference: where things live in the repo

| What | File |
|---|---|
| Global deps | `kiauh/core/constants.py` (`GLOBAL_DEPS`, `SYSTEMD`, `NGINX_*`) |
| systemctl wrappers | `kiauh/utils/sys_utils.py` (`cmd_sysctl_service`, `cmd_sysctl_manage`, `create_service_file`, `remove_system_service`) |
| Instance discovery via systemd | `kiauh/utils/instance_utils.py`, `kiauh/core/instance_manager/` |
| nginx config generation | `kiauh/components/webui_client/client_utils.py`, `assets/{nginx_cfg,upstreams.conf,common_vars.conf}` |
| Moonraker deps + speedups | `kiauh/components/moonraker/utils/{utils.py,sysdeps_parser.py}`, `moonraker_setup_service.py` |
| Klipper deps | `kiauh/components/klipper/klipper_utils.py` (`install_klipper_packages`) |
| systemd unit templates | `kiauh/components/{klipper,moonraker}/assets/*.service` |
| Extension registry | `kiauh/extensions/*/metadata.json` |
| Settings | `kiauh/core/settings/kiauh_settings.py`, `default.kiauh.cfg` |
