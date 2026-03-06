# PineBuds Pro — Reset and recovery (detailed)

Your earbuds are not turning on after flashing. Use this guide to try to recover them.

---

## Clarifications (models and LEDs)

- **Your unit:** You said the earbuds have no visible buttons and that open/closed lid doesn’t matter. That may be a different hardware revision; the official manual describes units with touch/button areas on the earbuds.
- **Purple LED:** In the official user manual, the **purple LED is on the earbuds** (after the “reset the earbuds” button sequence), not necessarily on the case. So if you only press a **case** button, you may never see purple — that’s normal.
- **Case reset button:** Some PineBuds Pro cases have a small **physical reset button** on the case (between the two bud seats). It resets the **case** (e.g. from “safety off” mode). It may not produce any LED; the case might just reset.

---

## Part A — Case reset button (if your case has one)

**Where to look**

- Open the lid.
- Look at the **base** (the part that holds the two earbuds), in the **middle** between the two depressions where the buds sit.
- The button is a small, recessed hole or bump — easy to miss. You may need a bright light.
- If there’s nothing there, your case may not have this button; skip to Part B.

**How to press**

- Use a **SIM-eject tool**, **paperclip**, or **toothpick** (not your finger, it’s too big).
- **Earbuds:** Try **with both earbuds in the case** first (lid open).
- **Press:** Short, firm press for about **2–3 seconds**, then release.
- **If nothing happens:** Try again with earbuds **out** of the case, same 2–3 second press.

**What to expect**

- You might see **no LED** — the case may just reset internally.
- If anything on the case (e.g. white charging LEDs) blinks or changes, note it.
- Then try taking the earbuds out and see if they power on (LED or sound).

---

## Part B — Earbud “buttons” (if your buds have them)

The manual describes **touch/button areas** on each earbud (often near the logo), not always obvious.

**If the earbuds are completely dead (no LED at all)**  
This procedure won’t work until they at least power on. Rely on Part A and Part C.

**If one or both earbuds sometimes show an LED** (e.g. red when in case):

1. Take **one** earbud out of the case.
2. Find the touch area (often the flat part with the logo).
3. **Press and hold** for **5 seconds** — manual says LED goes red then it shuts down.
4. Do the same for the **other** earbud.
5. Then **press and hold on both earbuds** until the LED flashes **red and blue**.
6. **Tap** the button **5 times** — manual says LED should flash **purple** then turn off.
7. Put **both** earbuds in the case for **30 seconds**, then take them out and test.

---

## Part C — Reflash with bestool (after any reset)

Goal: get the chip to reboot so bestool can sync.

1. **USB:** Case connected to PC; in PowerShell (Admin) attach the two USB devices to WSL so Docker sees them (`usbipd bind` / `attach`).
2. **Docker:** In the container run:
   ```bash
   bestool write-image out/open_source/open_source.bin --port /dev/ttyACM0
   ```
   Leave this **running** (it will wait at “Syncing into bootloader”).
3. **Trigger reboot:**  
   **Right earbud:** take it **out** of the case → wait **3 seconds** → put it **back in**.  
   Do this **while** bestool is already waiting. If sync works, it will flash that bud.
4. Repeat for the **left** earbud with `/dev/ttyACM1`.

If you did a case reset (Part A), do the “trigger reboot” step **right after** the reset to maximize the chance bestool catches the boot.

---

## Part D — Official Pine64 Windows programmer (if bestool never syncs)

1. **Download on Windows:**
   - Programmer: https://files.pine64.org/os/PineBudsPro/PineBuds%20Pro%20programmer%20v1.48.zip  
   - Factory firmware: https://files.pine64.org/os/PineBudsPro/AC08_20221102.bin  
   - Manual: https://files.pine64.org/os/PineBudsPro/PineBuds%20Pro%20programmer%20user%20manual.pdf  
2. **Unzip** the programmer and **detach** the USB devices from WSL so Windows sees the COM ports.
3. Open the programmer, load `AC08_20221102.bin`, and follow its manual to flash **both** earbuds (one COM port per bud).

---

## Summary

| Step | What you do | If it works / doesn’t |
|------|-------------|------------------------|
| A    | Find and press case reset button (2–3 s), earbuds in then out | No purple is OK; try taking buds out to see if they power on. Then try Part C. |
| B    | Only if buds ever show LED: earbud reset (5 s hold, then both, then 5 taps) | Purple on **earbuds** = reset done. Then Part C. |
| C    | bestool already running, then remove → 3 s → reinsert each bud | Sync and flash; buds should boot with BLE=0 firmware. |
| D    | Official Windows programmer + factory .bin | Restores stock firmware; then we can reflash our BLE=0 build. |

You were right to ask for more detail: the manual’s purple LED is on the **earbuds**, and the case button (if present) may not show any LED. Use Part A and C first; if the case has no button or bestool never syncs, use Part D.
