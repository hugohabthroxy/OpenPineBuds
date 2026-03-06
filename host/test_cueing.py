"""
End-to-end audio cueing test.

Usage:
    python test_cueing.py [--name "PineBuds Pro"] [--tone 0] [--volume 80]
                          [--duration 3.0] [--burst-count 1] [--burst-gap 0]

This script:
  1. Connects to the PineBuds Pro
  2. Subscribes to Cue Status notifications
  3. Reads and prints current config from the earbud
  4. Optionally sends a CONFIGURE command (if burst params provided)
  5. Sends a START cue command
  6. Waits for and prints the status notification (CUEING)
  7. After a delay, sends a STOP command
  8. Waits for the IDLE status notification
  9. Reports round-trip latencies
"""

import asyncio
import argparse
import struct
import time

from bleak import BleakClient, BleakScanner
from cueing_uuids import (
    CUE_CMD_CHAR_UUID,
    CUE_STATUS_CHAR_UUID,
    CUE_CONFIG_CHAR_UUID,
    CUE_CMD_START,
    CUE_CMD_STOP,
    CUE_CMD_CONFIGURE,
    CUE_STATUS_IDLE,
    CUE_STATUS_CUEING,
    CUE_STATUS_ERROR,
)

STATUS_NAMES = {
    CUE_STATUS_IDLE: "IDLE",
    CUE_STATUS_CUEING: "CUEING",
    CUE_STATUS_ERROR: "ERROR",
}

notification_timestamps = []


def status_callback(sender, data: bytearray):
    ts = time.perf_counter()
    notification_timestamps.append(ts)
    status = data[0] if len(data) > 0 else -1
    name = STATUS_NAMES.get(status, f"UNKNOWN(0x{status:02x})")
    print(f"  [NOTIFY] Cue Status: {name}  (raw: {data.hex()})")


async def test_cueing(device_name: str, tone_id: int, volume: int,
                      cue_duration: float, burst_count: int,
                      burst_gap_ms: int, duration_ms: int):
    print(f"Scanning for '{device_name}'...")
    device = await BleakScanner.find_device_by_name(device_name, timeout=10.0)
    if device is None:
        print(f"Device '{device_name}' not found.")
        return

    print(f"Connecting to {device.name} [{device.address}]...")

    async with BleakClient(device) as client:
        print(f"Connected. MTU: {client.mtu_size}")

        print("Subscribing to Cue Status notifications...")
        await client.start_notify(CUE_STATUS_CHAR_UUID, status_callback)
        await asyncio.sleep(0.5)

        # Read current status and config
        status_data = await client.read_gatt_char(CUE_STATUS_CHAR_UUID)
        print(f"Current status: {status_data.hex()} "
              f"({STATUS_NAMES.get(status_data[0], 'UNKNOWN') if status_data else 'empty'})")

        config_data = await client.read_gatt_char(CUE_CONFIG_CHAR_UUID)
        if len(config_data) >= 7:
            t_id, vol, dur, bc, bg = struct.unpack("<BBHBH", config_data[:7])
            print(f"Current config: tone={t_id} vol={vol} dur={dur}ms "
                  f"burst={bc} gap={bg}ms")
        else:
            print(f"Current config (raw): {config_data.hex()}")

        # Send CONFIGURE if burst params specified
        if burst_count > 1 or duration_ms > 0:
            config_payload = struct.pack(
                "<BBHBH",
                tone_id & 0xFF,
                volume & 0xFF,
                duration_ms & 0xFFFF,
                burst_count & 0xFF,
                burst_gap_ms & 0xFFFF,
            )
            cmd_configure = bytes([CUE_CMD_CONFIGURE]) + config_payload
            print(f"\nSending CONFIGURE: {cmd_configure.hex()}")
            await client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd_configure)
            await asyncio.sleep(0.3)

        # Send START command
        cmd_payload = bytes([CUE_CMD_START, tone_id, volume])
        print(f"\nSending START command: {cmd_payload.hex()}")
        t_start = time.perf_counter()
        await client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd_payload,
                                     response=False)
        write_time = (time.perf_counter() - t_start) * 1000
        print(f"  Write completed in {write_time:.1f}ms")

        await asyncio.sleep(0.5)
        if notification_timestamps:
            latency = (notification_timestamps[-1] - t_start) * 1000
            print(f"  Write-to-notification latency: {latency:.1f}ms")

        # Let the cue play
        print(f"\nCueing active. Waiting {cue_duration}s...")
        await asyncio.sleep(cue_duration)

        # Send STOP command
        cmd_stop = bytes([CUE_CMD_STOP])
        print(f"Sending STOP command: {cmd_stop.hex()}")
        t_stop = time.perf_counter()
        await client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd_stop,
                                     response=False)
        write_time = (time.perf_counter() - t_stop) * 1000
        print(f"  Write completed in {write_time:.1f}ms")

        await asyncio.sleep(0.5)
        if len(notification_timestamps) >= 2:
            latency = (notification_timestamps[-1] - t_stop) * 1000
            print(f"  Stop write-to-notification latency: {latency:.1f}ms")

        await client.stop_notify(CUE_STATUS_CHAR_UUID)

        # Final read
        status_data = await client.read_gatt_char(CUE_STATUS_CHAR_UUID)
        print(f"\nFinal status: {status_data.hex()}")

        config_data = await client.read_gatt_char(CUE_CONFIG_CHAR_UUID)
        if len(config_data) >= 7:
            t_id, vol, dur, bc, bg = struct.unpack("<BBHBH", config_data[:7])
            print(f"Final config: tone={t_id} vol={vol} dur={dur}ms "
                  f"burst={bc} gap={bg}ms")

        print("Test complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Test PineBuds Pro audio cueing")
    parser.add_argument("--name", default="PineBuds Pro",
                        help="BLE device name")
    parser.add_argument("--tone", type=int, default=0,
                        help="Tone ID (0=beep, 1=click, 2=chirp, 3-4=extra)")
    parser.add_argument("--volume", type=int, default=80,
                        help="Volume 0-100")
    parser.add_argument("--duration", type=float, default=3.0,
                        help="How long to let the cue play (seconds)")
    parser.add_argument("--burst-count", type=int, default=1,
                        help="Number of tone bursts (1=single)")
    parser.add_argument("--burst-gap", type=int, default=200,
                        help="Gap between bursts in ms")
    parser.add_argument("--tone-duration", type=int, default=500,
                        help="Duration of each tone burst in ms (0=until stopped)")
    args = parser.parse_args()

    asyncio.run(test_cueing(args.name, args.tone, args.volume, args.duration,
                            args.burst_count, args.burst_gap,
                            args.tone_duration))


if __name__ == "__main__":
    main()
