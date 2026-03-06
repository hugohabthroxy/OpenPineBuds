# Next Steps -- Getting Your First Cue to Play

This document explains, step by step, what you need to do **right now** to go from "code on the Mac" to "hearing a sound from the earbuds triggered by your Windows laptop." We will go slowly and verify each step before moving to the next.

---

## Where You Are Right Now

You have been writing code on your **MacBook** using Cursor. The firmware C code and the Python host scripts are all sitting locally in `/Users/throxy/OpenPineBuds/`. Nothing has been compiled yet, and nothing has been flashed onto the earbuds.

The earbuds still have whatever firmware was on them before. To hear a cue, you need to:

1. Get the code to your Windows laptop
2. Compile it into a binary file (using Docker)
3. Flash that binary onto the earbuds (using a USB-C cable)
4. Run a Python script on the Windows laptop to connect over BLE and send a "play sound" command

Here is the overall flow:

```
Mac (Cursor)  -->  GitHub  -->  Windows (Docker + bestool)  -->  Earbuds
    code              sync           build + flash                  play
```

---

## Step-by-Step Instructions

### STEP 1: Push the code from your Mac to GitHub

On your Mac, open a terminal in the project folder (`/Users/throxy/OpenPineBuds/`) and run:

```bash
git add -A
git commit -m "Add cueing service: volume, burst, duration, latency, FSM"
git push
```

If you haven't set up a remote yet, you'll need to create a repository on GitHub first and add it:

```bash
git remote add origin https://github.com/YOUR_USERNAME/OpenPineBuds.git
git push -u origin main
```

**How to verify:** Go to your GitHub repo in a browser. You should see all the new files under `services/ble_app/app_cueing/`, `services/ble_profiles/cueing/`, and `host/`.

---

### STEP 2: Pull the code on your Windows laptop

On the Windows laptop, open a terminal (PowerShell or Git Bash) and clone or pull:

```bash
# If you haven't cloned yet:
git clone https://github.com/YOUR_USERNAME/OpenPineBuds.git
cd OpenPineBuds

# If you already cloned before:
cd OpenPineBuds
git pull
```

**How to verify:** Run `dir host\` (or `ls host/`). You should see `cueing_uuids.py`, `test_cueing.py`, `scan_and_discover.py`, etc.

---

### STEP 3: Build the firmware using Docker

The firmware is written in C for an ARM chip (BES2300YP). You cannot compile it with a normal compiler -- you need a special ARM cross-compiler. The project's Docker setup handles this for you.

Make sure Docker Desktop is installed and running on Windows. Then:

```bash
# Start the Docker development container
./start_dev.sh

# You are now inside the container. Your prompt looks like:
# root@abc123:/usr/src#

# Clean any old build artifacts (recommended for first build)
./clear.sh

# Build the firmware
./build.sh
```

This takes 1-5 minutes. When it finishes, the output binary is at:
```
out/open_source/open_source.bin
```

**How to verify:** The last lines of the build should say something like "DONE" or show the output file path without errors. If you see errors, run `./clear.sh` first and try again.

**If Docker is not working:** Make sure Docker Desktop is running. On Windows, you may need WSL2 enabled. Check the Docker docs for setup.

---

### STEP 4: Backup the current firmware (optional but recommended)

Before flashing new firmware, back up what's currently on the earbuds. Connect the charging case to the Windows laptop via USB-C. Put the earbuds in the case.

```bash
./backup.sh
```

This saves the current firmware to a file so you can restore it if needed.

---

### STEP 5: Flash the new firmware

With the earbuds in the charging case and the case connected via USB-C:

1. Take both earbuds OUT of the case
2. Wait 3 seconds
3. Put them back IN the case (this triggers a reboot that the programmer can catch)
4. Quickly run:

```bash
# Inside the Docker container:
./download.sh

# Or manually, if you know which ports:
bestool write-image out/open_source/open_source.bin --port /dev/ttyACM0
bestool write-image out/open_source/open_source.bin --port /dev/ttyACM1
```

You need to flash **both** earbuds (each has its own serial port). The ports are usually `/dev/ttyACM0` and `/dev/ttyACM1` on Linux/Docker, or `COM3`/`COM4` on Windows directly.

**How to verify:** The flashing tool should report success for each earbud. If it times out, try the "remove, wait, reinsert" sequence again.

---

### STEP 6: Let the earbuds boot with the new firmware

1. Take the earbuds out of the case
2. Wait for them to power on (you may hear a power-on sound)
3. They should appear as "PineBuds Pro" in your Bluetooth settings

Do NOT pair them through Windows Bluetooth settings yet -- we will connect via BLE from Python, which is a different connection type.

---

### STEP 7: Install Python dependencies on Windows

Open a new terminal on Windows (outside Docker). Navigate to the project:

```bash
cd OpenPineBuds/host
pip install -r requirements.txt
```

This installs `bleak`, the Python BLE library that talks to the earbuds.

**How to verify:** Run `python -c "import bleak; print(bleak.__version__)"`. It should print a version number like `0.21.1`.

---

### STEP 8: Scan for the earbuds (first real test)

This is the moment of truth. With the earbuds out of the case and powered on:

```bash
cd host
python scan_and_discover.py
```

You should see output like:
```
Scanning for BLE device 'PineBuds Pro' for 10.0s...
Found device: PineBuds Pro [XX:XX:XX:XX:XX:XX]
Connecting...
Connected: True
MTU: 23

Service: ac000001-cafe-b0ba-f001-deadbeef0000
  >>> AUDIO CUEING SERVICE FOUND <<<
  Characteristic: ac000002-cafe-b0ba-f001-deadbeef0000  [write-without-response, write]
  Characteristic: ac000003-cafe-b0ba-f001-deadbeef0000  [read, notify]
  Characteristic: ac000004-cafe-b0ba-f001-deadbeef0000  [read, write]

SUCCESS: Audio Cueing Service is registered and visible.
```

**If it says "Device not found":**
- Make sure the earbuds are out of the case and powered on
- Try `python scan_and_discover.py --name "OpenPineBuds"` (the name might differ)
- Check that Bluetooth is enabled on the Windows laptop
- Make sure no other device (like your phone) is already connected to the buds

**If it connects but the cueing service is NOT found:**
- The firmware was not built correctly or not flashed. Go back to Step 3.

---

### STEP 9: Play your first cue (the goal!)

```bash
python test_cueing.py
```

You should hear a short alert sound from the earbuds! The script will:
1. Connect to the buds
2. Subscribe to status notifications
3. Send a START command (you hear the sound)
4. Wait 3 seconds
5. Send a STOP command
6. Print latency measurements

You can customize it:
```bash
# Different tone, louder, longer
python test_cueing.py --tone 1 --volume 100 --duration 5.0

# With burst pattern (3 beeps with 200ms gaps)
python test_cueing.py --burst-count 3 --burst-gap 200 --tone-duration 300
```

**Congratulations** -- if you hear the sound, the entire chain works: your custom firmware is running on the earbuds, the BLE service is advertising, and your Python script can control it.

---

## What Comes After This

Once you have confirmed the basic connection works, the remaining steps are:

### A. Run the latency benchmark

Measure how fast the system responds:

```bash
python latency_benchmark.py --iterations 100 --csv results.csv
```

This data goes into the thesis to characterize system performance.

### B. Integrate into your supervisor's HERMES repo (aidfog)

Your supervisor (Maxim) has set up a boilerplate repository at [kuleuven-emedia/aidfog](https://github.com/kuleuven-emedia/aidfog) with the structure for your project. The cueing-specific structure is:

```
hermes/aidfog/
  controller/
    buds_handler.py     ← Maps to our cueing_consumer.py
    buds_backend.py     ← Facade / API layer (currently empty)
  utils/
    types.py            ← Convenience datatypes (currently empty)
    utilities.py        ← Shared logic (currently empty)
  pipeline.py           ← Maps to our cueing_fsm.py (currently empty)
  stream.py             ← HERMES data structure (currently empty)

buds_firmware/          ← Where our firmware changes go
```

**What you need to do:**

1. Clone the aidfog repo:
   ```bash
   git clone https://github.com/kuleuven-emedia/aidfog.git
   ```

2. Copy the firmware changes into `buds_firmware/`. You can either:
   - Copy the entire OpenPineBuds folder into it, or
   - Just copy the changed/new files (see the file list at the bottom of this doc)

3. Port the Python code into the HERMES structure:
   - `cueing_consumer.py` -> `hermes/aidfog/controller/buds_handler.py`
   - `cueing_fsm.py` -> `hermes/aidfog/pipeline.py`
   - `cueing_uuids.py` -> `hermes/aidfog/utils/types.py`
   - Create a `buds_backend.py` facade that wraps `buds_handler.py` with simple API methods

4. The `stream.py` should define the data structure that flows between pipeline components (FoG probability in, cueing commands out).

**Note:** The files in the aidfog repo are currently empty boilerplate. Your supervisor set up the structure; you fill in the implementation. The code from `host/` in this repo is your implementation -- you just need to reorganize it into the HERMES folder structure.

### C. Run the longevity test

On the Raspberry Pi (or your Windows laptop) to verify stability over hours:

```bash
python experiment_longevity.py --duration 4h --csv longevity.csv
```

### D. Prepare cueing audio files

Replace the default alert tones with proper metronome clicks:
- Find or create `.mp3` or `.opus` files of the sounds you want
- Place them in `config/_default_cfg_src_/res/en/` with the same name as the sound you're replacing (e.g., `SOUND_POWER_ON.mp3`)
- Rebuild the firmware

### E. Write the thesis

Using the latency data and strategy comparison results.

---

## Troubleshooting Quick Reference

| Problem | Solution |
|---------|----------|
| Docker won't start | Install Docker Desktop, enable WSL2 on Windows |
| Build errors | Run `./clear.sh` then `./build.sh` again |
| Flashing fails / times out | Remove buds from case, wait 3s, reinsert, flash immediately |
| "Device not found" in scan | Ensure buds are out of case, BT enabled, no other device paired |
| Cueing service not visible | Firmware not flashed properly -- rebuild and reflash |
| No sound on START command | Check volume level (try `--volume 100`), check the buds are not muted |
| Python import error | Run `pip install -r requirements.txt` |
| Connection drops frequently | Ensure buds are within 2m of the laptop, no obstructions |
