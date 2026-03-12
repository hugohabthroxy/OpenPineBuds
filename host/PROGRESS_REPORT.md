# Progress Report -- PineBuds Pro Audio Cueing System

**Date:** March 12, 2026
**Author:** Hugo Alonso

---

## What is the goal?

Build a system that helps Parkinson's patients during "freezing of gait" episodes by playing rhythmic sounds through wireless earbuds. When body sensors detect the patient is about to freeze, the system wirelessly tells the earbuds to play a sound that helps the patient resume walking.

---

## What has been done?

### 1. Custom wireless control of the earbuds -- DONE

The PineBuds Pro earbuds normally only play music. They have no way for a computer to say "play this sound now." I added a new wireless interface (a custom BLE service) to the earbuds' firmware so a laptop can:

- **Start** a sound
- **Stop** a sound
- **Configure** the sound (which tone, how loud, how long, repeating patterns)
- **Get notified** when the earbud starts or stops playing

This required writing ~1,500 lines of new C code inside the earbuds' firmware, plus modifying 14 existing firmware files.

### 2. Memory and boot fixes -- DONE

Enabling the wireless control system on the earbuds' tiny chip (992 KB of RAM) required disabling features we don't need (noise cancellation, a high-quality audio codec) to free up memory. Two bugs also had to be fixed: one that crashed the earbuds when they booted inside the charging case, and another that prevented the wireless signal from being broadcast.

### 3. Host-side Python scripts -- DONE

Nine Python scripts that run on the laptop to communicate with the earbuds:

- Scan and discover the earbuds wirelessly
- Send start/stop/configure commands
- Measure response time (latency)
- Run long-duration stability tests
- Compare different cueing strategies (simple threshold vs. state machine)
- A HERMES-compatible module ready for integration into the research framework

### 4. Verified working end-to-end -- DONE (today)

The full chain has been tested and confirmed working:

```
Laptop (Python) --BLE--> Earbuds (custom firmware) --> Sound plays
         <--notification--
```

**Latency benchmark results (100 iterations, 0 failures):**

| Metric | Value |
|--------|-------|
| Mean round-trip | 28 ms |
| Median round-trip | 25 ms |
| Worst case (P99) | 53 ms |
| Reliability | 100% (0 timeouts) |

A 25 ms median response time is well within the requirements for real-time cueing (typical threshold is 100-500 ms).

---

## What remains?

| Task | Status |
|------|--------|
| Custom firmware with BLE cueing service | Done |
| Laptop can wirelessly control earbuds | Done |
| Latency measured and exported to CSV | Done |
| Integration into HERMES / aidfog repo | Not started |
| Custom metronome tones (replace default beeps) | Not started |
| Multi-hour stability test | Not started |
| Strategy comparison on recorded FoG data | Not started |
| Thesis writing | Not started |

---

## Summary

The core technical work -- making the earbuds controllable over wireless from a laptop -- is complete and verified. The next phase is integrating this into the HERMES research framework, running the experiments needed for the thesis, and writing up the results.
