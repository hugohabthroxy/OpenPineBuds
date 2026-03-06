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

**Hardware:** Pine64 PineBuds Pro -- open-source BLE earbuds with BES2300YP dual-core ARM Cortex-M4F SoC, 4MB flash, Bluetooth 5.2.

**Software stack:**
- Firmware: C, based on the [OpenPineBuds SDK](https://github.com/pine64/OpenPineBuds)
- Host/Python: [bleak](https://github.com/hbldh/bleak) BLE library
- Framework: HERMES (KU Leuven in-house Python framework for real-time multimodal sensing)
- Supervisor's boilerplate repo: [kuleuven-emedia/aidfog](https://github.com/kuleuven-emedia/aidfog)

**Development setup:** Dual-laptop workflow. MacBook (Cursor IDE + AI agents) for code editing. Windows laptop for Docker-based firmware compilation, USB flashing via `bestool`, and BLE testing via Python scripts.

---

## Repository Structure

The codebase lives at `/Users/throxy/OpenPineBuds/` (fork of pine64/OpenPineBuds).

### Firmware (C) -- New/Modified Files

```
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
    Makefile                       # Modified: added cueing sources
  ble_stack/ble_ip/
    rwip_task.h                    # Modified: TASK_ID_CUEINGPS = 78
    rwapp_config.h                 # Modified: CFG_APP_CUEING_SERVER
    rwprf_config.h                 # Modified: BLE_CUEING_SERVER
    rwble_hl_config.h              # Modified: CFG_NB_PRF includes cueing
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
```

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

## What Remains To Be Done

1. **Build, flash, and verify** -- the code is written but hasn't been compiled/tested on hardware yet
2. **Integration into aidfog repo** -- port cueing_consumer.py and cueing_fsm.py into the HERMES structure at kuleuven-emedia/aidfog
3. **Custom cueing tones** -- replace default alert sounds with proper metronome clicks (swap .opus/.mp3 files in `config/_default_cfg_src_/res/en/`)
4. **Latency characterization** -- run benchmark on actual hardware, collect data for thesis
5. **Longevity testing** -- run multi-hour test on Raspberry Pi 5
6. **Strategy comparison experiment** -- run threshold vs FSM on recorded FoG dataset traces
7. **Thesis writing** -- document methodology, results, analysis

---

## Build and Flash Instructions

```bash
# On Windows, inside Docker:
./start_dev.sh       # Enter Docker container
./clear.sh           # Clean old build
./build.sh           # Compile firmware
./download.sh        # Flash to earbuds via USB-C

# On Windows, outside Docker:
cd host
pip install -r requirements.txt
python scan_and_discover.py      # Verify service is visible
python test_cueing.py            # Play first cue
python latency_benchmark.py --iterations 100 --csv results.csv
```

---

## References

- [OpenPineBuds SDK](https://github.com/pine64/OpenPineBuds)
- [PineBuds Pro Wiki](https://wiki.pine64.org/wiki/PineBuds_Pro)
- [bleak BLE library](https://github.com/hbldh/bleak)
- [aidfog HERMES repo](https://github.com/kuleuven-emedia/aidfog)
- BES2300YP: Dual-core 300MHz ARM Cortex-M4F, 992KB SRAM, 4MB Flash, BT 5.2
