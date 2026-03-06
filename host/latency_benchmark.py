"""
Latency benchmark for BLE cueing write-to-notification round-trip.

Measures the time between writing a command (START/STOP) and receiving
the corresponding status notification. Reports statistics and optionally
exports raw data to CSV for thesis analysis.

Usage:
    python latency_benchmark.py [--name "PineBuds Pro"] [--iterations 100]
                                [--csv results.csv] [--warmup 5]
"""

import asyncio
import argparse
import csv
import json
import os
import statistics
import time
from datetime import datetime

from bleak import BleakClient, BleakScanner

from cueing_uuids import (
    CUE_CMD_CHAR_UUID,
    CUE_STATUS_CHAR_UUID,
    CUE_CMD_START,
    CUE_CMD_STOP,
    CUE_CMD_CONFIGURE,
)

latency_event = asyncio.Event()
last_notify_time = 0.0
last_notify_status = 0


def notification_handler(sender, data: bytearray):
    global last_notify_time, last_notify_status
    last_notify_time = time.perf_counter()
    last_notify_status = data[0] if len(data) > 0 else -1
    latency_event.set()


def compute_percentile(data: list, p: float) -> float:
    """Compute the p-th percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def print_stats(label: str, latencies: list):
    """Pretty-print latency statistics."""
    if not latencies:
        print(f"\n{label}: No successful measurements")
        return

    print(f"\n{label} ({len(latencies)} samples):")
    print(f"  Mean:       {statistics.mean(latencies):8.2f} ms")
    print(f"  Median:     {statistics.median(latencies):8.2f} ms")
    if len(latencies) > 1:
        print(f"  Stdev:      {statistics.stdev(latencies):8.2f} ms")
    print(f"  Min:        {min(latencies):8.2f} ms")
    print(f"  Max:        {max(latencies):8.2f} ms")
    print(f"  P5:         {compute_percentile(latencies, 5):8.2f} ms")
    print(f"  P25:        {compute_percentile(latencies, 25):8.2f} ms")
    print(f"  P75:        {compute_percentile(latencies, 75):8.2f} ms")
    print(f"  P95:        {compute_percentile(latencies, 95):8.2f} ms")
    print(f"  P99:        {compute_percentile(latencies, 99):8.2f} ms")


async def measure_latency(device_name: str, iterations: int,
                          warmup: int, csv_path: str | None,
                          use_write_no_response: bool):
    print(f"Scanning for '{device_name}'...")
    device = await BleakScanner.find_device_by_name(device_name, timeout=10.0)
    if device is None:
        print(f"Device '{device_name}' not found.")
        return

    print(f"Connecting to {device.name} [{device.address}]...")

    async with BleakClient(device) as client:
        print(f"Connected. MTU: {client.mtu_size}")

        await client.start_notify(CUE_STATUS_CHAR_UUID, notification_handler)
        await asyncio.sleep(0.5)

        all_results = []

        total = warmup + iterations
        for i in range(total):
            is_warmup = i < warmup
            phase = "warmup" if is_warmup else "measure"

            # --- START latency ---
            latency_event.clear()
            t_write_start = time.perf_counter()
            wall_start = time.time()

            await client.write_gatt_char(
                CUE_CMD_CHAR_UUID, bytes([CUE_CMD_START, 0, 80]),
                response=not use_write_no_response,
            )

            start_lat = None
            try:
                await asyncio.wait_for(latency_event.wait(), timeout=2.0)
                start_lat = (last_notify_time - t_write_start) * 1000
            except asyncio.TimeoutError:
                if not is_warmup:
                    print(f"  Iteration {i - warmup + 1}: START timeout")

            await asyncio.sleep(0.15)

            # --- STOP latency ---
            latency_event.clear()
            t_write_stop = time.perf_counter()
            wall_stop = time.time()

            await client.write_gatt_char(
                CUE_CMD_CHAR_UUID, bytes([CUE_CMD_STOP]),
                response=not use_write_no_response,
            )

            stop_lat = None
            try:
                await asyncio.wait_for(latency_event.wait(), timeout=2.0)
                stop_lat = (last_notify_time - t_write_stop) * 1000
            except asyncio.TimeoutError:
                if not is_warmup:
                    print(f"  Iteration {i - warmup + 1}: STOP timeout")

            await asyncio.sleep(0.15)

            if not is_warmup:
                iteration_num = i - warmup + 1
                all_results.append({
                    "iteration": iteration_num,
                    "wall_time_start": wall_start,
                    "wall_time_stop": wall_stop,
                    "start_latency_ms": start_lat,
                    "stop_latency_ms": stop_lat,
                    "write_mode": "no_response" if use_write_no_response
                                  else "with_response",
                })

                if iteration_num % 25 == 0:
                    print(f"  Completed {iteration_num}/{iterations}")

        await client.stop_notify(CUE_STATUS_CHAR_UUID)

        # --- Analysis ---
        start_latencies = [r["start_latency_ms"] for r in all_results
                           if r["start_latency_ms"] is not None]
        stop_latencies = [r["stop_latency_ms"] for r in all_results
                          if r["stop_latency_ms"] is not None]

        print("\n" + "=" * 60)
        print("LATENCY BENCHMARK RESULTS")
        print("=" * 60)
        print(f"Device:     {device.name} [{device.address}]")
        print(f"MTU:        {client.mtu_size}")
        print(f"Iterations: {iterations} (+ {warmup} warmup)")
        print(f"Write mode: {'No Response' if use_write_no_response else 'With Response'}")
        print(f"Timestamp:  {datetime.now().isoformat()}")

        print_stats("START command -> notification", start_latencies)
        print_stats("STOP command -> notification", stop_latencies)

        all_latencies = start_latencies + stop_latencies
        if all_latencies:
            print_stats("Combined (START + STOP)", all_latencies)

            timeouts = sum(1 for r in all_results
                           if r["start_latency_ms"] is None
                           or r["stop_latency_ms"] is None)
            print(f"\nTimeouts: {timeouts}/{iterations * 2} "
                  f"({100 * timeouts / (iterations * 2):.1f}%)")

        # --- CSV export ---
        if csv_path:
            with open(csv_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "iteration", "wall_time_start", "wall_time_stop",
                    "start_latency_ms", "stop_latency_ms", "write_mode",
                ])
                writer.writeheader()
                writer.writerows(all_results)
            print(f"\nRaw data exported to: {csv_path}")

        # --- JSON summary ---
        summary = {
            "device": device.name,
            "address": device.address,
            "mtu": client.mtu_size,
            "iterations": iterations,
            "write_mode": "no_response" if use_write_no_response
                          else "with_response",
            "timestamp": datetime.now().isoformat(),
            "start_mean_ms": round(statistics.mean(start_latencies), 3)
                             if start_latencies else None,
            "start_median_ms": round(statistics.median(start_latencies), 3)
                               if start_latencies else None,
            "start_p95_ms": round(compute_percentile(start_latencies, 95), 3)
                            if start_latencies else None,
            "stop_mean_ms": round(statistics.mean(stop_latencies), 3)
                            if stop_latencies else None,
            "stop_median_ms": round(statistics.median(stop_latencies), 3)
                              if stop_latencies else None,
            "stop_p95_ms": round(compute_percentile(stop_latencies, 95), 3)
                           if stop_latencies else None,
        }
        json_path = (csv_path.replace(".csv", "_summary.json")
                     if csv_path else None)
        if json_path:
            with open(json_path, "w") as f:
                json.dump(summary, f, indent=2)
            print(f"Summary exported to: {json_path}")

        return summary


def main():
    parser = argparse.ArgumentParser(
        description="BLE cueing latency benchmark")
    parser.add_argument("--name", default="PineBuds Pro",
                        help="BLE device name")
    parser.add_argument("--iterations", type=int, default=100,
                        help="Number of START/STOP measurement cycles")
    parser.add_argument("--warmup", type=int, default=5,
                        help="Number of warmup cycles (not measured)")
    parser.add_argument("--csv", default=None,
                        help="Path to export raw results as CSV")
    parser.add_argument("--no-response", action="store_true",
                        help="Use Write Without Response for commands")
    args = parser.parse_args()

    asyncio.run(measure_latency(
        args.name, args.iterations, args.warmup, args.csv,
        args.no_response))


if __name__ == "__main__":
    main()
