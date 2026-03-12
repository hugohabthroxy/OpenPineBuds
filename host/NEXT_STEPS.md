# Next Steps -- BLE Cueing Service Confirmed Working

This document explains, step by step, what you need to do **right now** and what comes after. Every step says which terminal to use.

---

## Where You Are Right Now

The custom BLE Audio Cueing Service is **confirmed working**. You connected to earbud address `12:34:56:C2:A2:30` and the full GATT service tree appeared:

```
Service: ac000001-cafe-b0ba-f001-deadbeef0000  [Audio Cueing]
  Characteristic: ac000002  [write-without-response, write]   ← Cue Command
  Characteristic: ac000003  [notify, read]                    ← Cue Status
  Characteristic: ac000004  [read, write]                     ← Cue Config
```

**Important:** The earbuds advertise as **"D&D TECH"** (the factory-flashed BLE name), not "PineBuds Pro" (which is the Classic Bluetooth name). All Python scripts have been updated to default to `"D&D TECH"` and also support a `--address` flag for direct MAC connection.

### Overall flow

```
Mac (Cursor)  -->  GitHub  -->  Windows (Docker + Pine64 programmer)  -->  Earbuds
    code              sync           build + flash                          tested ✓
```

---

## IMMEDIATE: Push Latest Script Updates and Run Tests

The Python host scripts were just updated (default name → `"D&D TECH"`, `--address` flag added). You need to push from Mac and pull on Windows.

### STEP 1: Push from Mac

**Terminal: Mac (Cursor terminal or macOS Terminal)**

```bash
cd /Users/throxy/OpenPineBuds
git add -A
git commit -m "Update host scripts: default BLE name D&D TECH, add --address flag"
git push
```

### STEP 2: Pull on Windows

**Terminal: Windows PowerShell** (outside Docker)

```bash
cd "C:\Users\Hugo Alonso\FINAL MASTER THESIS\OpenPineBuds"
git pull
```

### STEP 3: Run the end-to-end cueing test

**Terminal: Windows PowerShell** (outside Docker, earbuds OUT of case)

```bash
cd host
pip install -r requirements.txt    # only needed once

# Option A: Connect by address (most reliable)
python test_cueing.py --address "12:34:56:C2:A2:30"

# Option B: Connect by name (now defaults to "D&D TECH")
python test_cueing.py
```

You should see:
```
Connecting directly to 12:34:56:C2:A2:30...
Connected. MTU: 512
Subscribing to Cue Status notifications...
Current status: 00 (IDLE)
Sending START command: 010050
  Write completed in X.Xms
Cueing active. Waiting 3.0s...
Sending STOP command: 02
Final status: 00
Test complete.
```

If you hear a sound from the earbuds, the entire chain is working end-to-end.

**If no sound is heard** but the GATT writes succeed: the firmware's cueing handler calls `trigger_media_play()` which requires the audio subsystem to be initialized. The GATT service layer is confirmed working; audio playback depends on the earbud being in the right boot state (out of case, not in charging mode).

### STEP 4: Run the latency benchmark

**Terminal: Windows PowerShell** (outside Docker)

```bash
python latency_benchmark.py --address "12:34:56:C2:A2:30" --iterations 100 --csv results.csv
```

This runs 100 START/STOP cycles and measures round-trip latency. Output includes mean, median, P95, P99 statistics, and exports raw data to `results.csv` + `results_summary.json`.

### STEP 5: Verify the scan works by name

**Terminal: Windows PowerShell** (outside Docker)

```bash
python scan_and_discover.py
```

This should now find the earbuds by name "D&D TECH" without needing `--address`.

---

## IF YOU NEED TO REBUILD FIRMWARE

Only needed if you make firmware (C code) changes. The Python scripts run on Windows directly and don't need a rebuild.

### Step A: Push from Mac

**Terminal: Mac (Cursor terminal)**

```bash
cd /Users/throxy/OpenPineBuds
git add -A
git commit -m "description of firmware changes"
git push
```

### Step B: Pull and build on Windows

**Terminal: Windows PowerShell** (outside Docker)

```bash
cd "C:\Users\Hugo Alonso\FINAL MASTER THESIS\OpenPineBuds"
git pull
docker compose run --rm builder
```

**Terminal: Docker container** (you are now inside)

```bash
./clear.sh
./build.sh
```

Wait for the build to finish (1-5 minutes). If successful, the binary is at `out/open_source/open_source.bin`.

### Step C: Copy the binary out of Docker

**Terminal: Windows PowerShell** (new window, outside Docker)

```bash
docker cp openpinebuds-builder-1:/usr/src/out/open_source/open_source.bin "C:\Users\Hugo Alonso\FINAL MASTER THESIS\open_source.bin"
```

### Step D: Flash with Pine64 programmer

**On Windows** (Docker NOT needed, USB cable connected to charging case):

1. Open `dld_main.exe` (Pine64 Windows Programmer)
2. Select the correct COM port (COM5 typically)
3. Tick the **APP** checkbox
4. Browse to `C:\Users\Hugo Alonso\FINAL MASTER THESIS\open_source.bin`
5. Take both earbuds OUT of the case
6. Click **All Start**
7. Put ONE earbud in the case
8. Wait for 100% green progress bar
9. Remove that earbud, put the OTHER one in
10. Wait for 100% green again
11. Remove the earbud, take both out of the case
12. Wait 5-10 seconds for them to boot

### Step E: Verify

**Terminal: Windows PowerShell** (outside Docker)

```bash
cd host
python scan_and_discover.py --address "12:34:56:C2:A2:30"
```

---

## WHAT COMES AFTER

### A. Latency Characterization (for thesis)

```bash
# Standard benchmark
python latency_benchmark.py --address "12:34:56:C2:A2:30" --iterations 100 --csv results.csv

# Write-without-response mode (lower latency)
python latency_benchmark.py --address "12:34:56:C2:A2:30" --iterations 100 --csv results_wnr.csv --no-response
```

### B. Longevity Test

```bash
python experiment_longevity.py --address "12:34:56:C2:A2:30" --duration 1h --csv longevity.csv
```

### C. Integration into aidfog repo

Port the Python code into the HERMES structure at [kuleuven-emedia/aidfog](https://github.com/kuleuven-emedia/aidfog):

| This repo (host/) | aidfog repo |
|---|---|
| `cueing_consumer.py` | `hermes/aidfog/controller/buds_handler.py` |
| `cueing_fsm.py` | `hermes/aidfog/pipeline.py` |
| `cueing_uuids.py` | `hermes/aidfog/utils/types.py` |
| (new) | `hermes/aidfog/controller/buds_backend.py` (API facade) |

### D. Custom Cueing Tones

Replace default alert sounds with proper metronome clicks:
- Find or create `.mp3` or `.opus` files
- Place in `config/_default_cfg_src_/res/en/` with the same name as the sound being replaced
- Rebuild firmware

### E. Strategy Comparison Experiment

```bash
python experiment_compare_strategies.py --trace fog_dataset.csv --csv comparison.csv
```

### F. Thesis Writing

Using latency data, longevity results, and strategy comparison.

---

## Quick Reference

| Task | Where | Command |
|------|-------|---------|
| Push code | Mac terminal | `git add -A && git commit -m "msg" && git push` |
| Pull code | Windows PowerShell | `cd "C:\Users\Hugo Alonso\FINAL MASTER THESIS\OpenPineBuds" && git pull` |
| Build firmware | Docker container | `./clear.sh && ./build.sh` |
| Copy binary out | Windows PowerShell | `docker cp openpinebuds-builder-1:/usr/src/out/open_source/open_source.bin .` |
| Flash earbuds | Windows (dld_main.exe) | Pine64 programmer GUI, COM5, APP checked |
| Scan BLE | Windows PowerShell | `python scan_and_discover.py` |
| Test cueing | Windows PowerShell | `python test_cueing.py --address "12:34:56:C2:A2:30"` |
| Benchmark | Windows PowerShell | `python latency_benchmark.py --address "12:34:56:C2:A2:30" --iterations 100 --csv results.csv` |
| UART debug | Windows (PuTTY) | Serial, COM5, 2000000 baud |

## Earbud BLE Addresses

| Earbud | MAC Address |
|--------|-------------|
| Right | `12:34:56:C2:A2:30` |
| Left | `12:34:56:C2:A2:31` |

Both advertise as **"D&D TECH"** over BLE. Classic Bluetooth name is **"PineBuds Pro"**.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Docker won't start | Install Docker Desktop, enable WSL2 on Windows |
| Build errors | Run `./clear.sh` then `./build.sh` again |
| Flashing fails (bestool) | Use Pine64 programmer (`dld_main.exe`) instead |
| "Device not found" in scan | Ensure earbuds are OUT of case; use `--address "12:34:56:C2:A2:30"` |
| Scan finds device but wrong name | Earbuds advertise as "D&D TECH", not "PineBuds Pro" |
| Cueing service not visible | Firmware not built with BLE=1, or not flashed properly |
| No sound on START command | Check volume (`--volume 100`), ensure earbud is out of case |
| Python import error | Run `pip install -r requirements.txt` |
| Connection drops | Ensure earbuds within 2m of laptop |
| PuTTY no output | Output only appears when earbud state changes (e.g., remove from / put in case) |
