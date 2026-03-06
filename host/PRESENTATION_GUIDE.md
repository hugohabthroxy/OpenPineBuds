# Firmware Changes Presentation Guide

Everything that was changed and implemented from the original [OpenPineBuds firmware](https://github.com/pine64/OpenPineBuds), explained so you can present it clearly.

---

## PART 1: The Summary (For Your Presentation Slides)

### What are the PineBuds Pro?

The PineBuds Pro are open-source wireless earbuds made by Pine64. They run on a BES2300YP chip (a dual-core ARM processor). They normally work like any other Bluetooth earbuds: playing music, making calls, pairing with your phone. The firmware (the software inside the earbuds) is written in C and can be modified and recompiled.

### What was the problem?

Out of the box, the earbuds only understand standard audio protocols. There is **no way for a computer program to send them custom commands** like "play a specific sound now" or "stop playing." For our FoG cueing system, we need exactly that -- a way to wirelessly tell the earbuds: "play a metronome click right now because the patient is freezing."

### What did we build?

We added a **custom Bluetooth Low Energy (BLE) service** to the firmware. Think of it as adding a new "feature module" to the earbuds. This service has three channels (called "characteristics"):

1. **Command Channel** -- the computer writes "START" or "STOP" here to control the sound
2. **Status Channel** -- the earbuds report their current state (idle or cueing) back to the computer
3. **Config Channel** -- the computer writes settings here (which tone, volume, duration, burst pattern)

On the computer side (a laptop running Python), we wrote scripts that use a BLE library called `bleak` to talk to these channels.

### Key features we implemented

| Feature | What it does |
|---------|--------------|
| **Custom BLE Service** | New wireless interface so a computer can control the earbuds |
| **Volume Control** | Set volume from 0-100%, mapped to 16 hardware levels |
| **Timed Playback** | Sound auto-stops after a configurable duration |
| **Burst Patterns** | Play N beeps with gaps between them (like a metronome) |
| **Low-Latency BLE** | Reduced wireless delay from ~30ms to ~10ms round-trip |
| **Status Notifications** | Earbuds report state changes back to the computer instantly |
| **Auto-Reconnect** | Python side automatically reconnects if Bluetooth drops |

### How many files were changed?

- **6 new firmware files** (C code for the new service)
- **9 existing firmware files modified** (registration and glue)
- **9 new Python scripts** (host-side BLE communication and testing)
- **Total: ~1500 lines of new C code, ~800 lines of Python**

### The big picture in one diagram

```
┌─────────────────────────────┐         ┌──────────────────────────────────┐
│     Laptop (Python)         │   BLE   │     PineBuds Pro (C firmware)    │
│                             │◄───────►│                                  │
│  CueingConsumer             │ 7.5ms   │   Custom GATT Service            │
│   ├─ start_cue()  ──────────┼──write──┼──► Command Handler              │
│   ├─ stop_cue()   ──────────┼──write──┼──► Stop Audio                   │
│   ├─ configure()  ──────────┼──write──┼──► Update Config                │
│   └─ status callback ◄──────┼──notify─┼──── Status Reporter             │
│                             │         │                                  │
│  CueingFSM                  │         │   Audio Engine                   │
│   ├─ threshold strategy     │         │   ├─ Volume set                  │
│   └─ FSM strategy           │         │   ├─ Tone select                 │
│      (IDLE→CUEING→COOLDOWN) │         │   ├─ Duration timer              │
│                             │         │   └─ Burst timer chain           │
└─────────────────────────────┘         └──────────────────────────────────┘
```

---

## PART 2: In-Depth Technical Explanation

This section explains every change in detail. It's organized by the layers of the firmware, from bottom to top.

---

### 2.1 Understanding the Original Firmware Architecture

The OpenPineBuds firmware uses a layered architecture typical of BLE embedded systems:

```
┌────────────────────────────────────────────┐
│              Application Layer             │  ← Decides "what to do"
│  (services/ble_app/)                       │    e.g., "play a sound"
├────────────────────────────────────────────┤
│              Profile Layer                 │  ← Describes "what exists"
│  (services/ble_profiles/)                  │    e.g., "this characteristic
│                                            │    is readable and writable"
├────────────────────────────────────────────┤
│              BLE Stack                     │  ← Handles "how to talk"
│  (services/ble_stack/)                     │    raw Bluetooth packets,
│                                            │    connection management
├────────────────────────────────────────────┤
│              Hardware / RTOS               │  ← Physical radio, timers,
│  (platform/, rtos/)                        │    memory, audio hardware
└────────────────────────────────────────────┘
```

The firmware already has several BLE services (for OTA updates, data transfer, etc.). We added a new one following the exact same pattern as the existing `DATAPATHPS` (data path profile server), which was the closest in structure to what we needed.

---

### 2.2 The Profile Layer (4 new files)

The profile layer is the "menu" that tells Bluetooth what our service offers. When a phone or laptop scans the earbuds, this is what they see.

#### File: `cueingps.c` -- The GATT Database

This file contains a table (an array of structs) that defines every attribute in our service:

```
Service Declaration (UUID: ac000001-...)
├── Cue Command Characteristic
│   ├── Declaration (says "this is writable")
│   ├── Value (UUID: ac000002-..., permissions: Write + Write No Response)
│   └── User Description ("Cue Command")
├── Cue Status Characteristic
│   ├── Declaration (says "this is readable and can notify")
│   ├── Value (UUID: ac000003-..., permissions: Read + Notify)
│   ├── Client Config Descriptor (CCCD -- the on/off switch for notifications)
│   └── User Description ("Cue Status")
└── Cue Config Characteristic
    ├── Declaration (says "this is readable and writable")
    ├── Value (UUID: ac000004-..., permissions: Read + Write)
    └── User Description ("Cue Config")
```

**Total: 13 attributes** in the GATT table (indexed by the `CUEINGPS_IDX_*` enum).

The file also contains lifecycle functions:
- `cueingps_init()` -- creates the database when the service starts up
- `cueingps_destroy()` -- frees memory when the service shuts down
- `cueingps_create()` -- called when a BLE connection is established
- `cueingps_cleanup()` -- called when a connection is dropped

These are bundled into a function pointer table (`cueingps_itf`) that the BLE stack calls through.

#### File: `cueingps_task.c` -- BLE Event Handlers

This is the "traffic controller" for low-level Bluetooth events. The BLE stack sends messages here when something happens.

**Write handler** (`gattc_write_req_ind_handler`):
- Checks which attribute was written by comparing the handle
- If it's the **CCCD** (notification config): enables or disables notifications and tells the app layer
- If it's the **Command value**: wraps the raw bytes in a kernel message and sends it up to the app layer
- If it's the **Config value**: prepends a `0x03` (CONFIGURE command byte) and sends it up -- this way the app layer always processes configs through the same `cueing_handle_command()` function

**Read handler** (`gattc_read_req_ind_handler`):
- Returns the actual current status (`app_cueing_server_env.currentStatus`) when the Status characteristic is read
- Returns the actual current config struct when the Config characteristic is read
- Returns human-readable description strings for the user description attributes

**Notification sender** (`send_status_notification`):
- Takes raw bytes and sends them as a BLE notification to the connected client

#### File: `cueingps.h` -- Internal Definitions

Defines:
- The attribute index enum (`CUEINGPS_IDX_SVC`, `CUEINGPS_IDX_CMD_CHAR`, etc.)
- The environment struct (`cueingps_env_tag`) that holds per-connection state
- The two task states: `CUEINGPS_IDLE` and `CUEINGPS_BUSY`

#### File: `cueingps_task.h` -- Message Definitions

Defines:
- Message IDs for kernel communication (`CUEINGPS_CUE_CMD_RECEIVED`, `CUEINGPS_STATUS_NTF_CFG_CHANGED`, etc.)
- Timer message IDs (`CUEINGPS_DURATION_TIMER`, `CUEINGPS_BURST_TIMER`)
- Data structures for passing data between layers (`ble_cueing_cmd_ind_t`, `ble_cueing_send_status_req_t`, etc.)

---

### 2.3 The Application Layer (2 new files)

This is where the "brain" lives -- the code that decides what to do when a command arrives.

#### File: `app_cueing_server.h` -- Public Interface

Defines the command protocol:
```c
#define CUE_CMD_START     0x01  // "start playing a sound"
#define CUE_CMD_STOP      0x02  // "stop playing"
#define CUE_CMD_CONFIGURE 0x03  // "update settings"

#define CUE_STATUS_IDLE   0x00  // "not playing anything"
#define CUE_STATUS_CUEING 0x01  // "sound is playing"
#define CUE_STATUS_ERROR  0xFF  // "something went wrong"
```

Defines the configuration structure (7 bytes, packed):
```c
typedef struct {
  uint8_t tone_id;       // Which sound to play (0=beep, 1-4=numbered tones)
  uint8_t volume;        // 0-100 percent
  uint16_t duration_ms;  // How long before auto-stop (0 = forever)
  uint8_t burst_count;   // How many beeps in a burst (1 = single beep)
  uint16_t burst_gap_ms; // Silence gap between beeps in a burst
} cueing_config_t;
```

Defines the application environment (the persistent state):
```c
struct app_cueing_server_env_tag {
  uint8_t connectionIndex;       // Which BLE connection we're on
  uint8_t isNotificationEnabled; // Has the client turned on notifications?
  uint8_t currentStatus;         // IDLE, CUEING, or ERROR
  cueing_config_t config;        // Current configuration
  uint8_t bursts_remaining;      // How many more beeps to play in this burst
  bool tone_playing;             // Is a tone currently sounding?
};
```

#### File: `app_cueing_server.c` -- Core Logic

This is the largest and most important new file. Here's what each function does:

**`cueing_send_status(status_byte)`** -- Updates the internal status and sends a BLE notification to the connected client. This is how the Python side knows the earbuds responded to a command.

**`cueing_map_volume(vol_pct)`** -- Converts a 0-100 percentage into the hardware's 16 discrete volume levels (0 = mute, 15 = max). Uses integer math to avoid floating point on the microcontroller.

**`cueing_resolve_tone(tone_id)`** -- Maps our tone IDs (0-4) to the firmware's built-in audio IDs (`AUD_ID_BT_WARNING`, `AUD_ID_NUM_1`, etc.). These are short alert sounds already stored in the earbud's flash memory.

**`cueing_cancel_timers()`** -- Clears any running duration or burst timers. Called before starting a new cue to avoid conflicts with any previous cue.

**`cueing_play_single_tone()`** -- Sets the volume and triggers audio playback. Uses `app_bt_stream_volumeset()` for volume and `trigger_media_play()` to start the sound.

**`cueing_stop_single_tone()`** -- Stops audio using `app_audio_manager_sendrequest(APP_BT_STREAM_MANAGER_STOP, ...)`. We use this instead of `trigger_media_stop()` because the latter only works for one specific audio ID.

**`cueing_start_audio()`** -- The main "start cueing" function. It:
1. Cancels any existing timers
2. Plays the first tone
3. Sends a CUEING status notification
4. If burst_count > 1: starts a burst timer chain (explained below)
5. If duration_ms > 0 and single burst: starts a duration timer

**`cueing_stop_audio()`** -- Cancels all timers, resets burst state, stops the tone, sends IDLE status.

**`cueing_handle_command(data, length)`** -- The command parser. Reads the first byte to determine the command type and dispatches to the appropriate handler. For START, optionally extracts inline tone_id and volume overrides.

**Timer handlers:**
- `app_cueing_duration_timer_handler()` -- called when the duration timer fires. Simply calls `cueing_stop_audio()`.
- `app_cueing_burst_timer_handler()` -- called when a burst timer fires. Stops the current tone, decrements `bursts_remaining`, plays the next tone (if any), and schedules the next timer.

**How burst patterns work:**

Imagine you configure: burst_count=3, duration_ms=200, burst_gap_ms=100

```
Time 0ms:     ┌──TONE──┐
             200ms:    └────────┐ (gap 100ms)
             300ms:             ┌──TONE──┐
             500ms:             └────────┐ (gap 100ms)
             600ms:                      ┌──TONE──┐
             800ms:                      └────────┘ → STOP, send IDLE
```

The firmware handles this by:
1. Playing tone 1 and setting burst_timer to fire at 200+100=300ms
2. When burst_timer fires: stop tone, play tone 2, set burst_timer for another 300ms
3. When burst_timer fires: stop tone, play tone 3, set duration_timer for 200ms (last burst)
4. When duration_timer fires: stop audio, send IDLE

**`cueing_request_low_latency_params(conidx)`** -- Requests the BLE central (laptop) to update the connection interval to 7.5-10ms with 0 slave latency. Default BLE connections use 30-50ms intervals, which adds significant delay. By reducing this, the round-trip time for a command-to-notification cycle drops substantially.

---

### 2.4 Registration Glue (9 existing files modified)

The firmware doesn't auto-discover new code. Every new BLE service must be manually registered in several places. Each change follows the exact pattern of the existing `DATAPATHPS` service.

#### `rwip_task.h` -- Task ID Assignment

Added: `TASK_ID_CUEINGPS = 78`

Every BLE service in the system has a unique task ID number. The existing services use IDs like 74 (DATAPATHPS), 75 (AI), etc. We added ours as 78.

Why it matters: The kernel uses these IDs to route messages between tasks. Without a unique ID, the system can't deliver messages to our service.

#### `rwapp_config.h` -- Build Flags

Added:
```c
#define CFG_APP_CUEING_SERVER    // Enables compilation
#define BLE_APP_CUEING_SERVER 1  // Used in #if guards throughout the code
```

Why it matters: These act as on/off switches. Every file we wrote wraps its code in `#if (BLE_APP_CUEING_SERVER)` / `#endif`. If you remove these defines, the entire cueing service disappears from the build.

#### `rwprf_config.h` -- Profile Registration

Added: `#define BLE_CUEING_SERVER 1`

Why it matters: This flag is at the profile level (one layer below the app). It tells the BLE stack's profile manager that a cueing profile exists and may need initialization.

#### `rwble_hl_config.h` -- Profile Count (Bug Fix)

Modified: Added `+ BLE_APP_CUEING_SERVER` to the `CFG_NB_PRF` macro.

This was a **critical bug** in the original code. `CFG_NB_PRF` tells the BLE stack how many profiles to allocate memory for. If a profile is registered but not counted here, the stack runs out of slots and the service silently fails to register.

#### `prf.c` -- Profile Interface Registry

Added a case in the big switch statement:
```c
case TASK_ID_CUEINGPS:
    return cueingps_prf_itf_get();
```

Why it matters: When the BLE stack initializes profiles, it calls this function to get the function pointer table (init, destroy, create, cleanup) for each profile. Without this case, the stack has no way to initialize our profile.

#### `app.c` -- Application Service List

Three changes:
1. Added `APPM_SVC_CUEING_SERVER` to the service enum
2. Added `app_cueing_add_cueingps` to the function pointer array that registers services
3. Added `app_cueing_server_init()` to the boot sequence

Why it matters: At startup, the firmware iterates through this array and calls each registration function. Our function sends a `GAPM_PROFILE_TASK_ADD_CMD` message to the BLE stack, which triggers profile initialization.

#### `app_task.c` -- Message Router

Three changes:
1. Added a case routing messages from `TASK_ID_CUEINGPS` to `app_cueing_server_table_handler`
2. Added disconnect handler calls to `app_cueing_server_disconnected_evt_handler`
3. Modified slave preferred connection parameters to 7.5-10ms interval, 0 latency

Why it matters: When the profile layer sends a message (e.g., "command received"), the app task router needs to know which handler to call. Without this routing, messages are silently dropped.

#### `Makefile` changes (2 files)

Both `services/ble_app/Makefile` and `services/ble_profiles/Makefile` were updated to:
- Add the new `.c` source files to the compilation list
- Add the new header directories to the include path

Without these changes, the compiler simply doesn't know the new code exists.

---

### 2.5 What We Did NOT Change

Important to note: we did **not** modify any of the following:
- The core BLE stack implementation
- The audio codec or DSP pipeline
- The TWS (True Wireless Stereo) pairing logic
- The ANC (Active Noise Cancellation) code
- The touch sensor or button handling
- The power management or charging logic
- The OTA (Over-The-Air) update mechanism

Our changes are entirely **additive** -- they sit alongside the existing functionality without disturbing it. The earbuds continue to work normally for music and calls; the cueing service is an extra feature accessible only via BLE.

---

### 2.6 The Python Host Side

While not part of the firmware itself, the host-side Python code is essential to the system.

#### UUID Definitions (`cueing_uuids.py`)

A single-source-of-truth for all UUIDs and command constants. Both the firmware and Python side must agree on these values, and keeping them in one Python file makes it easy to audit consistency.

#### BLE Scanner (`scan_and_discover.py`)

The first diagnostic tool. It scans the air, connects to the earbuds, and enumerates every GATT service. You use this to verify the cueing service actually shows up after flashing.

#### End-to-End Test (`test_cueing.py`)

Connects, subscribes to notifications, sends START, waits, sends STOP. Prints everything. This is the "does it work at all?" test. Also supports configuring burst parameters from the command line.

#### Latency Benchmark (`latency_benchmark.py`)

Runs hundreds of START/STOP cycles and measures the time between sending a command and receiving the status notification. Reports mean, median, percentiles (P5, P25, P75, P95, P99), and exports raw data to CSV and summary to JSON.

#### HERMES Consumer (`cueing_consumer.py`)

The production-quality wrapper. Implements the HERMES framework's Consumer interface:
- `setup()` -- connect to earbuds at pipeline start
- `process(data)` -- handle incoming commands from the AI pipeline
- `teardown()` -- disconnect at pipeline stop

Includes auto-reconnection with exponential backoff (up to 5 attempts), disconnect callbacks, and structured operation logging for post-hoc analysis.

#### Cueing FSM (`cueing_fsm.py`)

The control logic that decides **when** to cue. Two strategies:
1. **Threshold**: Simple high/low hysteresis on FoG probability
2. **FSM**: Full state machine with IDLE -> CUEING -> COOLDOWN -> IDLE transitions, configurable durations, and minimum cooldown between cues

Designed as a HERMES Pipeline component that sits between the AI detector and the CueingConsumer.

#### Experiment Scripts

- `experiment_longevity.py` -- runs for hours, counting disconnects and tracking latency drift
- `experiment_compare_strategies.py` -- replays recorded FoG traces through both strategies and compares sensitivity, precision, false positives, and detection latency

---

### 2.7 Summary Table: Every Changed File

| # | File | Change Type | What Was Changed |
|---|------|-------------|-----------------|
| 1 | `cueingps_task.h` | New | Message IDs, timer IDs, data structs |
| 2 | `cueingps.h` | New | Attribute enum, env struct |
| 3 | `cueingps.c` | New | GATT database (13 attributes), profile lifecycle |
| 4 | `cueingps_task.c` | New | BLE read/write/notify handlers |
| 5 | `app_cueing_server.h` | New | Command/status defines, config struct |
| 6 | `app_cueing_server.c` | New | Command parser, audio control, timers, volume, burst logic |
| 7 | `rwip_task.h` | Modified | Added TASK_ID_CUEINGPS = 78 |
| 8 | `rwapp_config.h` | Modified | Added build flags |
| 9 | `rwprf_config.h` | Modified | Added profile flag |
| 10 | `rwble_hl_config.h` | Modified | Fixed profile count (CFG_NB_PRF) |
| 11 | `prf.c` | Modified | Registered profile in switch |
| 12 | `app.c` | Modified | Added to service list, init, registration |
| 13 | `app_task.c` | Modified | Message routing, conn params |
| 14 | `ble_app/Makefile` | Modified | Added source + include paths |
| 15 | `ble_profiles/Makefile` | Modified | Added source + include paths |
| 16 | `cueing_uuids.py` | New | UUID definitions |
| 17 | `scan_and_discover.py` | New | BLE scanner |
| 18 | `test_cueing.py` | New | End-to-end test |
| 19 | `latency_benchmark.py` | New | Latency measurement + export |
| 20 | `cueing_consumer.py` | New | HERMES consumer + auto-reconnect |
| 21 | `cueing_fsm.py` | New | Cueing control FSM |
| 22 | `experiment_longevity.py` | New | Multi-hour stability test |
| 23 | `experiment_compare_strategies.py` | New | Strategy comparison |
| 24 | `requirements.txt` | New | Python deps |
