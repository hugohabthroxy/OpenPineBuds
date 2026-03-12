# PineBuds Pro -- Reset and Recovery

Use this guide if the earbuds stop responding after flashing, or if you need to restore factory firmware.

---

## Quick Decision Tree

```
Earbuds not working after flash?
  │
  ├─ LEDs still work (red/blue when taken out of case)?
  │   └─ Reflash with Pine64 programmer (Part B) — PREFERRED
  │
  ├─ No LED at all?
  │   ├─ Try case reset button (Part A)
  │   └─ If no button or no change → drain battery (Part C) → then Part B
  │
  └─ bestool stuck at "Syncing into bootloader"?
      └─ Use Pine64 programmer instead (Part B)
```

---

## Part A -- Case Reset Button

Some PineBuds Pro cases have a small physical reset button between the two earbud seats.

1. Open the lid
2. Look at the base between the two depressions where the buds sit
3. The button is a small, recessed hole -- use a SIM-eject tool or paperclip
4. Press and hold for 2-3 seconds with both earbuds in the case
5. Take the earbuds out and see if they power on (LED or sound)

If your case has no button, skip to Part B.

---

## Part B -- Pine64 Windows Programmer (Preferred Flashing Method)

This is the most reliable way to flash firmware. It works when `bestool` fails.

**Prerequisites:**
- Download the programmer: https://files.pine64.org/os/PineBudsPro/PineBuds%20Pro%20programmer%20v1.48.zip
- Download factory firmware (for recovery): https://files.pine64.org/os/PineBudsPro/AC08_20221102.bin
- USB cable connected from charging case to Windows PC
- **Detach USB from WSL/Docker first** if it was attached (in PowerShell: `usbipd detach --busid <ID>`)

**Steps:**

1. Unzip the programmer and run `dld_main.exe`
2. Select the correct COM port (typically **COM5**)
3. Tick the **APP** checkbox
4. Browse to the firmware file:
   - For custom firmware: `open_source.bin` (copied out of Docker)
   - For factory recovery: `AC08_20221102.bin`
5. Take **both earbuds OUT** of the case
6. Click **All Start**
7. Put **one earbud** into the case
8. Wait for the progress bar to reach 100% (green)
9. Remove that earbud, put the **other earbud** in
10. Wait for 100% green again
11. Remove earbud, close the programmer

**After flashing:** Take both earbuds out of the case, wait 5-10 seconds for them to boot. You should see LEDs and/or hear a power-on tone.

**To copy the custom firmware out of Docker:**

```powershell
docker cp openpinebuds-builder-1:/usr/src/out/open_source/open_source.bin "C:\Users\Hugo Alonso\FINAL MASTER THESIS\open_source.bin"
```

---

## Part C -- Battery Drain (Last Resort)

If the earbud is completely stuck (no LED, no response to case reset, programmer can't connect):

1. Take the earbud out of the case
2. Leave it on a desk for **24-48 hours** until the 40 mAh battery is completely drained
3. Put it back in the case to charge for 5 minutes
4. The ROM bootloader always runs on power-on -- this gives the programmer a window to sync
5. Immediately try Part B

---

## Part D -- bestool (Alternative, Less Reliable)

`bestool` works for the **left earbud** but has intermittent "Bad Checksum" errors with the right earbud. Use the Pine64 programmer (Part B) instead when possible.

If you still want to try bestool (inside Docker container):

```bash
bestool write-image out/open_source/open_source.bin --port /dev/ttyACM1
```

1. Start the command (it waits at "Syncing into bootloader")
2. Take the earbud **out** of the case
3. Wait 3 seconds
4. Put it **back in** the case
5. bestool should detect the reboot and begin flashing

The ports are usually:
- `/dev/ttyACM0` = right earbud
- `/dev/ttyACM1` = left earbud

USB must be attached to WSL/Docker first:

```powershell
usbipd list                    # Find the CH342 device
usbipd bind --busid <ID>      # First time only
usbipd attach --wsl --busid <ID>
```

---

## Earbud Addresses (for reference)

| Earbud | BLE MAC | Classic BT Name |
|--------|---------|-----------------|
| Right | `12:34:56:C2:A2:30` | PineBuds Pro |
| Left | `12:34:56:C2:A2:31` | PineBuds Pro |

BLE advertising name: **"D&D TECH"** (factory-programmed, overrides firmware default).

---

## Summary

| Method | Reliability | When to Use |
|--------|-------------|-------------|
| Pine64 programmer (`dld_main.exe`) | High | Always preferred for flashing |
| Case reset button | Medium | First thing to try if earbuds are unresponsive |
| bestool | Medium | Works for left earbud; use inside Docker |
| Battery drain | Last resort | When nothing else works |
