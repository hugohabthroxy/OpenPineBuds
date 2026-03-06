"""
Longevity test: verify BLE connection stability over extended operation.

Runs continuous cueing cycles for a configurable duration, monitoring for:
- BLE disconnections and reconnections
- Latency degradation over time
- Audio playback failures (status timeouts)

Usage:
    python experiment_longevity.py --duration 4h [--name "PineBuds Pro"]
                                   [--interval 10] [--csv longevity.csv]
"""

import asyncio
import argparse
import csv
import logging
import re
import statistics
import time
from datetime import datetime, timedelta

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from cueing_uuids import (
    CUE_CMD_CHAR_UUID,
    CUE_STATUS_CHAR_UUID,
    CUE_CMD_START,
    CUE_CMD_STOP,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def parse_duration(s: str) -> float:
    """Parse human-readable duration like '4h', '30m', '2h30m'."""
    total_seconds = 0.0
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*([hms]?)", s.lower()):
        value = float(match.group(1))
        unit = match.group(2) or "s"
        if unit == "h":
            total_seconds += value * 3600
        elif unit == "m":
            total_seconds += value * 60
        else:
            total_seconds += value
    if total_seconds == 0:
        total_seconds = float(s)
    return total_seconds


latency_event = asyncio.Event()
last_notify_time = 0.0


def notification_handler(sender, data: bytearray):
    global last_notify_time
    last_notify_time = time.perf_counter()
    latency_event.set()


async def run_longevity_test(device_name: str, duration_s: float,
                             cycle_interval_s: float, csv_path: str | None):
    results = []
    disconnects = 0
    timeouts = 0
    cycle_num = 0
    start_time = time.monotonic()
    end_time = start_time + duration_s

    logger.info("Starting longevity test: %.1f hours, cycle every %.0fs",
                duration_s / 3600, cycle_interval_s)

    device = await BleakScanner.find_device_by_name(device_name, timeout=15.0)
    if device is None:
        logger.error("Device '%s' not found", device_name)
        return

    client = BleakClient(device)

    async def connect():
        nonlocal disconnects
        for attempt in range(5):
            try:
                await client.connect()
                await client.start_notify(
                    CUE_STATUS_CHAR_UUID, notification_handler)
                logger.info("Connected (attempt %d)", attempt + 1)
                return True
            except BleakError as e:
                logger.warning("Connect attempt %d failed: %s", attempt + 1, e)
                await asyncio.sleep(2.0 * (attempt + 1))
        return False

    if not await connect():
        logger.error("Could not connect. Aborting.")
        return

    try:
        while time.monotonic() < end_time:
            cycle_num += 1
            elapsed_h = (time.monotonic() - start_time) / 3600

            if not client.is_connected:
                logger.warning("Disconnected at cycle %d (%.2fh), reconnecting...",
                               cycle_num, elapsed_h)
                disconnects += 1
                if not await connect():
                    logger.error("Reconnect failed at cycle %d", cycle_num)
                    break

            # START cycle
            latency_event.clear()
            t0 = time.perf_counter()
            wall = time.time()

            try:
                await client.write_gatt_char(
                    CUE_CMD_CHAR_UUID, bytes([CUE_CMD_START, 0, 80]),
                    response=False)
            except BleakError:
                disconnects += 1
                results.append({
                    "cycle": cycle_num,
                    "elapsed_h": round(elapsed_h, 4),
                    "wall_time": wall,
                    "start_latency_ms": None,
                    "stop_latency_ms": None,
                    "error": "write_failed",
                })
                await asyncio.sleep(cycle_interval_s)
                continue

            start_lat = None
            try:
                await asyncio.wait_for(latency_event.wait(), timeout=2.0)
                start_lat = (last_notify_time - t0) * 1000
            except asyncio.TimeoutError:
                timeouts += 1

            await asyncio.sleep(0.5)

            # STOP cycle
            latency_event.clear()
            t1 = time.perf_counter()

            try:
                await client.write_gatt_char(
                    CUE_CMD_CHAR_UUID, bytes([CUE_CMD_STOP]),
                    response=False)
            except BleakError:
                disconnects += 1
                results.append({
                    "cycle": cycle_num,
                    "elapsed_h": round(elapsed_h, 4),
                    "wall_time": wall,
                    "start_latency_ms": start_lat,
                    "stop_latency_ms": None,
                    "error": "write_failed",
                })
                await asyncio.sleep(cycle_interval_s)
                continue

            stop_lat = None
            try:
                await asyncio.wait_for(latency_event.wait(), timeout=2.0)
                stop_lat = (last_notify_time - t1) * 1000
            except asyncio.TimeoutError:
                timeouts += 1

            results.append({
                "cycle": cycle_num,
                "elapsed_h": round(elapsed_h, 4),
                "wall_time": wall,
                "start_latency_ms": round(start_lat, 3) if start_lat else None,
                "stop_latency_ms": round(stop_lat, 3) if stop_lat else None,
                "error": None,
            })

            if cycle_num % 50 == 0:
                valid_start = [r["start_latency_ms"] for r in results[-50:]
                               if r["start_latency_ms"] is not None]
                avg = statistics.mean(valid_start) if valid_start else 0
                logger.info(
                    "Cycle %d (%.2fh): avg_start_lat=%.1fms disconnects=%d timeouts=%d",
                    cycle_num, elapsed_h, avg, disconnects, timeouts)

            remaining = cycle_interval_s - 0.5
            if remaining > 0:
                await asyncio.sleep(remaining)

    finally:
        if client.is_connected:
            try:
                await client.stop_notify(CUE_STATUS_CHAR_UUID)
            except BleakError:
                pass
            await client.disconnect()

    # --- Report ---
    total_hours = (time.monotonic() - start_time) / 3600
    start_lats = [r["start_latency_ms"] for r in results
                  if r["start_latency_ms"] is not None]
    stop_lats = [r["stop_latency_ms"] for r in results
                 if r["stop_latency_ms"] is not None]

    print("\n" + "=" * 60)
    print("LONGEVITY TEST REPORT")
    print("=" * 60)
    print(f"Duration:      {total_hours:.2f} hours")
    print(f"Total cycles:  {cycle_num}")
    print(f"Disconnects:   {disconnects}")
    print(f"Timeouts:      {timeouts}/{cycle_num * 2}")
    if start_lats:
        print(f"START latency: mean={statistics.mean(start_lats):.1f}ms "
              f"p95={sorted(start_lats)[int(len(start_lats) * 0.95)]:.1f}ms")
    if stop_lats:
        print(f"STOP latency:  mean={statistics.mean(stop_lats):.1f}ms "
              f"p95={sorted(stop_lats)[int(len(stop_lats) * 0.95)]:.1f}ms")

    if csv_path:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "cycle", "elapsed_h", "wall_time",
                "start_latency_ms", "stop_latency_ms", "error",
            ])
            writer.writeheader()
            writer.writerows(results)
        print(f"\nRaw data saved to: {csv_path}")


def main():
    parser = argparse.ArgumentParser(description="BLE cueing longevity test")
    parser.add_argument("--name", default="PineBuds Pro",
                        help="BLE device name")
    parser.add_argument("--duration", default="4h",
                        help="Test duration (e.g., 4h, 30m, 1h30m)")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="Seconds between cueing cycles")
    parser.add_argument("--csv", default=None,
                        help="CSV output path for raw data")
    args = parser.parse_args()

    duration_s = parse_duration(args.duration)
    asyncio.run(run_longevity_test(args.name, duration_s,
                                   args.interval, args.csv))


if __name__ == "__main__":
    main()
