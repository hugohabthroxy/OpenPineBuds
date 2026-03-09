# AI Agent Context Document -- PineBuds Pro Audio Cueing System

This document provides full context for any AI agent that will continue working on this project. It contains everything needed to understand the codebase, the architecture, what has been done, and what remains.

---

## Project Overview

**Thesis title:** Integration of audio cueing into wearable realtime data acquisition and processing system for countering FOG episodes using hackable open-source earbuds.

**What it does:** A system that helps Parkinson's disease patients during "freezing of gait" (FoG) episodes by playing rhythmic audio cues through wireless earbuds. When body-worn sensors detect (via AI) that the patient is about to freeze, the system sends a BLE command to the earbuds, which play a sound that helps the patient resume walking.

**Team:**
- Hugo: wearable cueing device (earbuds firmware + BLE host scripts + HERMES integration)
- Alex: AI model for real-time FoG detection from IMU data
- Supervisors: Bart Vanrumste, Vayalet Stefanova, Maxim Yudayev (KU Leuven)

**Hardware:** Pine64 PineBuds Pro -- open-source BLE earbuds with BES2300YP dual-core ARM Cortex-M4F SoC (300 MHz, 992 KB SRAM, 448 KB ROM), 4 MB flash, Bluetooth 5.2, 40 mAh battery per earbud, USB-C to dual-UART via CH342 chip.

**Software stack:**
- Firmware: C, based on the [OpenPineBuds SDK](https://github.com/pine64/OpenPineBuds)
- Host/Python: [bleak](https://github.com/hbldh/bleak) BLE library
- Framework: HERMES (KU Leuven in-house Python framework for real-time multimodal sensing)
- Supervisor's boilerplate repo: [kuleuven-emedia/aidfog](https://github.com/kuleuven-emedia/aidfog)

**Development setup:** MacBook Pro (Cursor IDE + AI agents) for code editing, push via GitHub. Windows 11 (Boot Camp on same MacBook, Intel 2019) for Docker-based firmware compilation, USB flashing via `bestool` or Pine64 programmer (`dld_main.exe`), and BLE testing via Python scripts. USB serial passthrough to Docker/WSL2 via `usbipd-win`.

---

## Repository Structure

The codebase lives at `/Users/throxy/OpenPineBuds/` (fork of pine64/OpenPineBuds).

### Build Configuration (Critical)

The open_source target **excludes the entire BLE stack** unless BLE is enabled.

- **[config/open_source/target.mk](config/open_source/target.mk):** `BLE ?= 1` enables the BLE stack and cueing service. **BLE is currently enabled** and the firmware boots successfully after memory optimizations and a crash fix.
- If `BLE ?= 0`, the build skips `services/ble_app/`, `services/ble_profiles/`, and `services/ble_stack/` — the flashed firmware will have no BLE and the earbuds will not be discoverable via bleak (only classic Bluetooth will work).
- BLE device name (for scanning) is defined in **[config/open_source/tgt_hardware.c](config/open_source/tgt_hardware.c):** `BLE_DEFAULT_NAME = "PineBuds Pro BLE"`. The host scripts must scan for `"PineBuds Pro BLE"`, not `"PineBuds Pro"` (the latter is the classic Bluetooth name).

### Memory Optimizations (Required for BLE=1)

The BES2300YP has only 992 KB SRAM. Enabling the full BLE host stack requires disabling non-essential features to free RAM:

| Change | File | Savings |
|--------|------|---------|
| ANC disabled (`ANC_APP=0`, `ANC_FF_ENABLED=0`, `ANC_FB_ENABLED=0`, `APP_ANC_KEY=0`, `ANC_FB_CHECK=0`) | `target.mk` | ~30-50 KB |
| LDAC codec disabled (`A2DP_LDAC_ON=0`) | `target.mk` | ~40 KB |
| Single BLE connection (`IS_USE_BLE_DUAL_CONNECTION=0`) | `target.mk` | Per-connection structures |
| Trace buffer reduced (`TRACE_BUF_SIZE := 4*1024`) | `target.mk` | 12 KB |
| Core dump disabled (`CORE_DUMP=0`) | `target.mk` | Variable |

### Boot Crash Fix

The BLE=1 firmware initially crashed when the earbud booted in the charging case. Root cause: `app_ble_mode_init()` was called too late in `app_init()` (after the battery check). When the earbud detected charging mode, it jumped to a shutdown path, which called `app_deinit()` → `LinkDisconnectDirectly()` → `app_ble_is_any_connection_exist()` — but BLE structures were never initialized. Fix: moved `app_ble_mode_init()` earlier in `apps.cpp`, before the battery check, so BLE data structures are always initialized regardless of boot mode.

### BLE Advertising Fix

After the boot crash was fixed, BLE advertising was still not visible to scanners. Root cause: two gates in the firmware blocked advertising unless TWS (True Wireless Stereo) pairing between the two earbuds had completed:

1. **IBRT_MASTER gate** (`services/ble_app/app_main/app_ble_core.c`): `app_ble_stub_user_data_fill_handler()` only enabled advertising when `current_role == IBRT_MASTER`. After a fresh flash, both earbuds have `nv_role = IBRT_UNKNOW`, so neither advertises. Fix: changed to always set `adv_enable = true`.

2. **BOX switch deadlock** (`services/app_ibrt/src/app_ibrt_search_pair_ui.cpp`): When the earbud boots in the case, the BOX advertising switch is set to "block." When taken out, the PLUGOUT handler should clear it, but it returned early when `nv_role == IBRT_UNKNOW`, creating a deadlock. Fix: removed the early returns in both the battery PLUGOUT handler and the GPIO box detection handler.

### Firmware (C) -- New/Modified Files

```
config/
  open_source/
    target.mk                  # BLE ?= 1, ANC=0, LDAC=0, memory opts
    tgt_hardware.c             # BLE_DEFAULT_NAME, BT_LOCAL_NAME
services/
  ble_profiles/
    cueing/cueingps/
      api/cueingps_task.h          # Message IDs, data structs
      src/cueingps.c               # GATT DB, profile lifecycle
      src/cueingps.h               # Attribute enum, env struct
      src/cueingps_task.c          # BLE event handlers (read/write/notify)
    prf/prf.c                      # Modified: profile registry
    Makefile                       # Modified: added cueing sources
  ble_app/
    app_cueing/
      app_cueing_server.h          # Command/status defines, config struct
      app_cueing_server.c          # Command handler, audio, timers, volume
    app_main/
      app.c                        # Modified: service list + init
      app_task.c                   # Modified: message routing + conn params
      app_ble_core.c               # Modified: bypass IBRT_MASTER adv gate
    Makefile                       # Modified: added cueing sources
  app_ibrt/src/
    app_ibrt_search_pair_ui.cpp    # Modified: allow box events when nv_role unknown
    app_ibrt_keyboard.cpp          # Modified: guard app_anc_key with #ifdef ANC_APP
  ble_stack/ble_ip/
    rwip_task.h                    # Modified: TASK_ID_CUEINGPS = 78
    rwapp_config.h                 # Modified: CFG_APP_CUEING_SERVER
    rwprf_config.h                 # Modified: BLE_CUEING_SERVER
    rwble_hl_config.h              # Modified: CFG_NB_PRF includes cueing
apps/main/
    apps.cpp                       # Modified: moved app_ble_mode_init() before battery check
```

### Host Scripts (Python)

```
host/
  cueing_uuids.py                  # UUID and constant definitions
  scan_and_discover.py             # Step 1: scan BLE, find cueing service
  test_cueing.py                   # Step 2: end-to-end cue test
  latency_benchmark.py             # Step 3: latency statistics + CSV export
  cueing_consumer.py               # HERMES Consumer with auto-reconnect
  cueing_fsm.py                    # FSM cueing controller (threshold + FSM)
  experiment_longevity.py          # Multi-hour stability test
  experiment_compare_strategies.py # Threshold vs FSM comparison
  requirements.txt                 # bleak>=0.21.0
  RESET_AND_RECOVERY.md            # Bricked earbuds: case reset, bestool, official programmer
  NEXT_STEPS.md                    # Full Mac → Windows → flash → test flow
```

### Build System Fixes (scripts / headers)

- **[scripts/clean.mk](scripts/clean.mk):** Directory entries in multi-object deps (e.g. `rtos/rtx/TARGET_CORTEX_M/`) were passed to `rm -f` and caused clean to fail. Fixed by adding directory entries to `subdir-ymn` and replacing them with `built-in.o`/`built-in.a` in `multi-objs-ymn`.
- **[services/ble_app/app_main/app_ble_rx_handler.h](services/ble_app/app_main/app_ble_rx_handler.h):** Added `#include <stdint.h>` so `uint8_t`/`uint16_t` are defined (required when BLE=1).
- **[services/bt_app/app_bt_media_manager.h](services/bt_app/app_bt_media_manager.h):** Added `enum` keyword to `app_audio_manager_ctrl_volume(enum APP_AUDIO_MANAGER_VOLUME_CTRL_T ...)` for C compatibility.

---

## Custom GATT Service Architecture

**Service UUID:** `ac000001-cafe-b0ba-f001-deadbeef0000`

| Characteristic | UUID (last 4 digits) | Permissions | Purpose |
|---|---|---|---|
| Cue Command | `...0002...` | Write, Write No Response | Send commands: START (0x01), STOP (0x02), CONFIGURE (0x03) |
| Cue Status | `...0003...` | Read, Notify | Status: IDLE (0x00), CUEING (0x01), ERROR (0xFF) |
| Cue Config | `...0004...` | Read, Write | Read/write cueing_config_t (7 bytes packed) |

### Command Protocol

**START (0x01):** `[0x01, tone_id, volume]` -- starts audio cue, optional tone/volume override
**STOP (0x02):** `[0x02]` -- stops audio cue immediately
**CONFIGURE (0x03):** `[0x03, tone_id, volume, duration_ms(2), burst_count, burst_gap_ms(2)]` -- updates config

### Config Structure (cueing_config_t, 7 bytes, little-endian packed)

| Field | Type | Range | Description |
|---|---|---|---|
| tone_id | uint8 | 0-4 | 0=warning beep, 1-4=number sounds |
| volume | uint8 | 0-100 | Mapped to 16 hardware levels |
| duration_ms | uint16 | 0-65535 | Auto-stop after this (0=manual stop) |
| burst_count | uint8 | 0-255 | Number of tone pulses (0=continuous) |
| burst_gap_ms | uint16 | 0-65535 | Gap between burst pulses |

---

## Key Implementation Details

### Firmware

- **Volume** is mapped from 0-100 to `TGT_VOLUME_LEVEL_MUTE` through `TGT_VOLUME_LEVEL_15` via `app_bt_stream_volumeset()`
- **Timers** use the BLE kernel timer API (`ke_timer_set` with 10ms resolution). Duration timer auto-stops cueing. Burst timer chains play-gap-play sequences.
- **Audio playback** uses `trigger_media_play(aud_id, device_id, PROMOT_ID_BIT_MASK_CHNLSEl_ALL)` and `app_audio_manager_sendrequest(APP_BT_STREAM_MANAGER_STOP, ...)` for stop
- **Connection parameters** are optimized to 7.5-10ms interval with 0 slave latency when notifications are enabled, for minimal BLE round-trip latency
- **Profile registration** follows the exact pattern of the existing `DATAPATHPS` profile

### Host Python

- **CueingConsumer** (`cueing_consumer.py`): HERMES-compatible consumer with auto-reconnect (exponential backoff, 5 attempts), disconnect callback, Write Without Response for lower latency, operation timestamp logging
- **CueingFSM** (`cueing_fsm.py`): Two strategies -- simple threshold with hysteresis and full FSM (IDLE -> CUEING -> COOLDOWN -> IDLE). Tracks cue events for false positive analysis.
- **Latency benchmark** (`latency_benchmark.py`): Warmup cycles, percentile reporting (P5-P99), CSV + JSON export, supports both Write With Response and Write Without Response

---

## HERMES Integration

The supervisor's boilerplate repo at [kuleuven-emedia/aidfog](https://github.com/kuleuven-emedia/aidfog) defines the expected structure:

```
hermes/aidfog/
  controller/
    buds_handler.py     # Manages BLE connection (maps to cueing_consumer.py)
    buds_backend.py     # API facade
  utils/
    types.py            # Convenience types
    utilities.py        # Shared logic
  pipeline.py           # HERMES Node (empty -- needs implementation)
  stream.py             # HERMES data structure (empty -- needs implementation)
```

The `cueing_consumer.py` in this repo is designed to map directly to `buds_handler.py`. It implements the HERMES Consumer interface (`setup()`, `process()`, `teardown()`).

The `cueing_fsm.py` can be integrated as the pipeline logic that sits between the AI detector and the cueing consumer.

---

## What Has Been Done

1. Custom GATT service with 3 characteristics (Command, Status, Config)
2. Full profile and app layer registration in the BLE stack
3. Volume control via hardware volume API
4. Duration-based auto-stop via kernel timers
5. Burst pattern playback via chained kernel timers
6. Low-latency BLE connection parameter optimization (7.5-10ms)
7. Config/Status read handlers return actual values (not hardcoded 0x00)
8. Profile count bug fix (CFG_NB_PRF)
9. Python host scripts: scan, test, benchmark, HERMES consumer, FSM controller
10. Experiment scripts: longevity test, strategy comparison
11. **Build system fixes** — clean.mk (directory entries in multi-objs), app_ble_rx_handler.h (`#include <stdint.h>`), app_bt_media_manager.h (`enum` keyword for C).
12. **Memory optimizations for BLE=1** — Disabled ANC (all 5 flags), disabled LDAC codec, reduced trace buffer from 16KB to 4KB, disabled core dump, forced single BLE connection (`IS_USE_BLE_DUAL_CONNECTION=0`).
13. **Boot crash fix** — Moved `app_ble_mode_init()` earlier in `apps.cpp` so BLE data structures are initialized before the battery/charging check, preventing a crash in `app_deinit()` when booting in the case.
14. **BLE advertising fix** — Bypassed two gates that blocked BLE advertising: (a) removed IBRT_MASTER role requirement in `app_ble_stub_user_data_fill_handler()`, (b) removed early returns in box event handlers when `nv_role == IBRT_UNKNOW`, allowing FETCH_OUT events to propagate and clear the BOX advertising switch.
15. **ANC compile fix** — Wrapped `app_anc_key()` call in `app_ibrt_keyboard.cpp` with `#ifdef ANC_APP` since ANC was disabled.
16. **Both earbuds flashed** — Left earbud via `bestool`, right earbud via Pine64 Windows programmer (`dld_main.exe`). Both boot and turn on normally.

## What Remains To Be Done

1. **Verify BLE advertising works** — After the advertising fix, rebuild, reflash, and run `python scan_and_discover.py` to confirm the cueing service UUID appears
2. **End-to-end cueing test** — Run `python test_cueing.py` to verify audio playback via BLE command
3. **Integration into aidfog repo** — port cueing_consumer.py and cueing_fsm.py into the HERMES structure at kuleuven-emedia/aidfog
4. **Custom cueing tones** — replace default alert sounds with proper metronome clicks (swap .opus/.mp3 files in `config/_default_cfg_src_/res/en/`)
5. **Latency characterization** — run benchmark on actual hardware, collect data for thesis
6. **Longevity testing** — run multi-hour test on Raspberry Pi 5
7. **Strategy comparison experiment** — run threshold vs FSM on recorded FoG dataset traces
8. **Thesis writing** — document methodology, results, analysis

---

## Build and Flash Instructions

**Prerequisites (Windows):** Git, Docker Desktop (WSL2), usbipd-win (for USB serial passthrough to WSL2/Docker), Python 3 with pip. See [host/NEXT_STEPS.md](NEXT_STEPS.md) for a full step-by-step; a more detailed Windows-only checklist is in the project plan "Windows Steps Guide".

**Current state:** `BLE ?= 1` in target.mk. The firmware builds and boots successfully with the memory optimizations and crash/advertising fixes applied.

```bash
# On Mac: push changes
cd /Users/throxy/OpenPineBuds
git add -A && git commit -m "description" && git push

# On Windows: pull latest, then enter Docker
cd "C:\Users\Hugo Alonso\FINAL MASTER THESIS\OpenPineBuds"
git pull
docker compose run --rm builder

# Inside Docker:
./clear.sh           # Clean old build
./build.sh           # Compile firmware (1–5 min)

# Option A: Flash via bestool (inside Docker, USB attached via usbipd)
bestool write-image out/open_source/open_source.bin --port /dev/ttyACM0  # right earbud
bestool write-image out/open_source/open_source.bin --port /dev/ttyACM1  # left earbud
# For each: start command, then remove earbud from case, wait 3s, reinsert

# Option B: Flash via Pine64 programmer (Windows, outside Docker)
# First detach USB from WSL, then copy binary out:
# (In separate PowerShell): docker cp <container>:/usr/src/out/open_source/open_source.bin .
# Open dld_main.exe, select COM port, tick APP, browse to open_source.bin
# Take earbuds out, click All Start, put earbud in, wait for 100% green

exit

# On Windows, outside Docker (earbuds out of case, powered on):
cd host
pip install -r requirements.txt
python scan_and_discover.py                              # Scans for "PineBuds Pro"
python scan_and_discover.py --name "PineBuds Pro BLE"   # Or scan BLE name specifically
python test_cueing.py                                    # Play first cue
python latency_benchmark.py --iterations 100 --csv results.csv
```

**If earbuds don't turn on at all (no LED):** see [host/RESET_AND_RECOVERY.md](host/RESET_AND_RECOVERY.md) and use the official Pine64 Windows programmer + factory firmware (`AC08_20221102.bin`). Detach USB from WSL first.

**If BLE scan finds no device:** Check that both earbuds are out of the case, powered on (blue LED on power-up), and that the firmware was built with `BLE=1`. UART logging at 2000000 baud can confirm BLE initialization (`CUEING: adding cueing profile service` in the log).

---

## References

- [OpenPineBuds SDK](https://github.com/pine64/OpenPineBuds)
- [PineBuds Pro Wiki](https://wiki.pine64.org/wiki/PineBuds_Pro)
- [PineBuds Pro Software (programmer + factory firmware)](https://wiki.pine64.org/wiki/PineBuds_Pro#Firmware_images) — Windows programmer v1.48, AC08_20221102.bin
- [bleak BLE library](https://github.com/hbldh/bleak)
- [aidfog HERMES repo](https://github.com/kuleuven-emedia/aidfog)
- BES2300YP: Dual-core 300MHz ARM Cortex-M4F, 992KB SRAM, 4MB Flash, BT 5.2
- In-repo: [host/RESET_AND_RECOVERY.md](host/RESET_AND_RECOVERY.md), [host/NEXT_STEPS.md](host/NEXT_STEPS.md)
