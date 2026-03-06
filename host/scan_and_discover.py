"""
Step 1: Scan for PineBuds Pro and enumerate GATT services.

Usage:
    python scan_and_discover.py [--name "PineBuds Pro"]

This script scans for BLE devices, connects to the PineBuds Pro,
and prints all discovered GATT services and characteristics.
It verifies that the custom Audio Cueing Service is present.
"""

import asyncio
import argparse
import sys

from bleak import BleakClient, BleakScanner
from cueing_uuids import CUEING_SERVICE_UUID


async def scan_and_connect(device_name: str, scan_timeout: float = 10.0):
    print(f"Scanning for BLE device '{device_name}' for {scan_timeout}s...")

    device = await BleakScanner.find_device_by_name(
        device_name, timeout=scan_timeout
    )

    if device is None:
        print(f"Could not find device '{device_name}'.")
        print("\nAll discovered devices:")
        devices = await BleakScanner.discover(timeout=scan_timeout)
        for d in devices:
            print(f"  {d.address}  {d.name or '(unknown)'}")
        return

    print(f"Found device: {device.name} [{device.address}]")
    print(f"Connecting...")

    async with BleakClient(device) as client:
        print(f"Connected: {client.is_connected}")
        print(f"MTU: {client.mtu_size}")
        print()

        cueing_found = False
        for service in client.services:
            print(f"Service: {service.uuid}  [{service.description}]")
            if service.uuid.lower() == CUEING_SERVICE_UUID.lower():
                cueing_found = True
                print("  >>> AUDIO CUEING SERVICE FOUND <<<")
            for char in service.characteristics:
                props = ", ".join(char.properties)
                print(f"  Characteristic: {char.uuid}  [{props}]")
                for desc in char.descriptors:
                    print(f"    Descriptor: {desc.uuid}")

        print()
        if cueing_found:
            print("SUCCESS: Audio Cueing Service is registered and visible.")
        else:
            print(
                "WARNING: Audio Cueing Service NOT found. "
                "Check firmware build flags and BLE advertising."
            )


def main():
    parser = argparse.ArgumentParser(
        description="Scan and discover PineBuds Pro GATT services"
    )
    parser.add_argument(
        "--name", default="PineBuds Pro",
        help="BLE device name to search for"
    )
    parser.add_argument(
        "--timeout", type=float, default=10.0,
        help="Scan timeout in seconds"
    )
    args = parser.parse_args()

    asyncio.run(scan_and_connect(args.name, args.timeout))


if __name__ == "__main__":
    main()
