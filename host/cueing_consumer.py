"""
HERMES Consumer subclass for PineBuds Pro Audio Cueing.

This module wraps the bleak BLE communication into a Consumer component
compatible with the HERMES framework. It receives upstream commands from
the AI Pipeline component and translates them into BLE GATT writes to
the PineBuds Pro earbuds.

Usage within HERMES:
    consumer = CueingConsumer(device_name="PineBuds Pro")
    pipeline.add_consumer(consumer)
"""

import asyncio
import logging
import struct
import time
from typing import Any, Optional

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

from cueing_uuids import (
    CUEING_SERVICE_UUID,
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

logger = logging.getLogger(__name__)


class CueingConsumer:
    """
    HERMES Consumer that interfaces with PineBuds Pro over BLE.

    Maintains a persistent BLE connection with automatic reconnection
    on disconnect. Exposes methods to start/stop cueing and configure
    parameters, plus the HERMES Consumer interface (setup/process/teardown).
    """

    def __init__(self, device_name: str = "PineBuds Pro",
                 scan_timeout: float = 10.0,
                 max_reconnect_attempts: int = 5,
                 reconnect_delay: float = 2.0,
                 reconnect_backoff: float = 1.5):
        self.device_name = device_name
        self.scan_timeout = scan_timeout
        self.max_reconnect_attempts = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay
        self.reconnect_backoff = reconnect_backoff

        self._client: Optional[BleakClient] = None
        self._connected = False
        self._current_status = CUE_STATUS_IDLE
        self._status_event = asyncio.Event()
        self._running = False
        self._reconnecting = False
        self._op_timestamps: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return (self._connected
                and self._client is not None
                and self._client.is_connected)

    @property
    def current_status(self) -> int:
        return self._current_status

    @property
    def operation_log(self) -> list[dict]:
        return list(self._op_timestamps)

    def _log_operation(self, op: str, latency_ms: Optional[float] = None,
                       success: bool = True):
        entry = {
            "timestamp": time.time(),
            "perf_counter": time.perf_counter(),
            "operation": op,
            "success": success,
        }
        if latency_ms is not None:
            entry["latency_ms"] = latency_ms
        self._op_timestamps.append(entry)
        logger.debug("OP %s success=%s latency=%s", op, success,
                     f"{latency_ms:.2f}ms" if latency_ms else "N/A")

    def _status_callback(self, sender, data: bytearray):
        if len(data) > 0:
            self._current_status = data[0]
        self._status_event.set()
        logger.debug("Status notification: 0x%02x", self._current_status)

    def _on_disconnect(self, client: BleakClient):
        logger.warning("BLE disconnected from %s", self.device_name)
        self._connected = False
        if self._running and not self._reconnecting:
            asyncio.ensure_future(self._auto_reconnect())

    async def _auto_reconnect(self):
        if self._reconnecting:
            return
        self._reconnecting = True
        delay = self.reconnect_delay

        for attempt in range(1, self.max_reconnect_attempts + 1):
            logger.info("Reconnection attempt %d/%d (delay %.1fs)",
                        attempt, self.max_reconnect_attempts, delay)
            await asyncio.sleep(delay)
            try:
                success = await self._do_connect()
                if success:
                    logger.info("Reconnected on attempt %d", attempt)
                    self._log_operation("reconnect", success=True)
                    self._reconnecting = False
                    return
            except Exception as e:
                logger.warning("Reconnect attempt %d failed: %s", attempt, e)
            delay = min(delay * self.reconnect_backoff, 30.0)

        logger.error("Failed to reconnect after %d attempts",
                     self.max_reconnect_attempts)
        self._log_operation("reconnect", success=False)
        self._reconnecting = False

    async def _do_connect(self) -> bool:
        device = await BleakScanner.find_device_by_name(
            self.device_name, timeout=self.scan_timeout
        )
        if device is None:
            logger.warning("Device '%s' not found during scan",
                           self.device_name)
            return False

        logger.info("Found %s [%s], connecting...", device.name,
                    device.address)
        self._client = BleakClient(
            device, disconnected_callback=self._on_disconnect
        )
        await self._client.connect()
        self._connected = True

        await self._client.start_notify(
            CUE_STATUS_CHAR_UUID, self._status_callback
        )

        logger.info("Connected and subscribed. MTU: %d",
                    self._client.mtu_size)
        return True

    async def connect(self) -> bool:
        """Scan for and connect to the PineBuds Pro."""
        try:
            return await self._do_connect()
        except BleakError as e:
            logger.error("BLE connection error: %s", e)
            self._connected = False
            return False

    async def disconnect(self):
        """Disconnect from the PineBuds Pro."""
        self._running = False
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(CUE_STATUS_CHAR_UUID)
            except BleakError:
                pass
            await self._client.disconnect()
        self._connected = False
        logger.info("Disconnected")

    async def _ensure_connected(self) -> bool:
        if self.is_connected:
            return True
        logger.warning("Not connected, attempting reconnect...")
        try:
            return await self._do_connect()
        except BleakError as e:
            logger.error("Reconnect failed: %s", e)
            return False

    async def start_cue(self, tone_id: int = 0, volume: int = 80) -> bool:
        """Send a START cue command. Returns True on success."""
        if not await self._ensure_connected():
            self._log_operation("start_cue", success=False)
            return False

        cmd = bytes([CUE_CMD_START, tone_id & 0xFF, volume & 0xFF])
        try:
            self._status_event.clear()
            t0 = time.perf_counter()
            await self._client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd,
                                               response=False)
            elapsed = (time.perf_counter() - t0) * 1000
            self._log_operation("start_cue", latency_ms=elapsed)
            logger.info("START cue sent (tone=%d, vol=%d) in %.1fms",
                        tone_id, volume, elapsed)
            return True
        except BleakError as e:
            logger.error("Failed to send START: %s", e)
            self._log_operation("start_cue", success=False)
            self._connected = False
            return False

    async def stop_cue(self) -> bool:
        """Send a STOP cue command. Returns True on success."""
        if not await self._ensure_connected():
            self._log_operation("stop_cue", success=False)
            return False

        cmd = bytes([CUE_CMD_STOP])
        try:
            self._status_event.clear()
            t0 = time.perf_counter()
            await self._client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd,
                                               response=False)
            elapsed = (time.perf_counter() - t0) * 1000
            self._log_operation("stop_cue", latency_ms=elapsed)
            logger.info("STOP cue sent in %.1fms", elapsed)
            return True
        except BleakError as e:
            logger.error("Failed to send STOP: %s", e)
            self._log_operation("stop_cue", success=False)
            self._connected = False
            return False

    async def configure(self, tone_id: int = 0, volume: int = 80,
                        duration_ms: int = 500, burst_count: int = 1,
                        burst_gap_ms: int = 0) -> bool:
        """Send a CONFIGURE command to update cueing parameters."""
        if not await self._ensure_connected():
            self._log_operation("configure", success=False)
            return False

        config_payload = struct.pack(
            "<BBHBH",
            tone_id & 0xFF,
            volume & 0xFF,
            duration_ms & 0xFFFF,
            burst_count & 0xFF,
            burst_gap_ms & 0xFFFF,
        )
        cmd = bytes([CUE_CMD_CONFIGURE]) + config_payload
        try:
            await self._client.write_gatt_char(CUE_CMD_CHAR_UUID, cmd)
            self._log_operation("configure")
            logger.info(
                "CONFIGURE sent: tone=%d vol=%d dur=%dms burst=%d gap=%dms",
                tone_id, volume, duration_ms, burst_count, burst_gap_ms)
            return True
        except BleakError as e:
            logger.error("Failed to send CONFIGURE: %s", e)
            self._log_operation("configure", success=False)
            self._connected = False
            return False

    async def read_config(self) -> Optional[dict]:
        """Read the current configuration from the earbud."""
        if not await self._ensure_connected():
            return None
        try:
            data = await self._client.read_gatt_char(CUE_CONFIG_CHAR_UUID)
            if len(data) >= 7:
                tone_id, volume, duration_ms, burst_count, burst_gap_ms = \
                    struct.unpack("<BBHBH", data[:7])
                return {
                    "tone_id": tone_id,
                    "volume": volume,
                    "duration_ms": duration_ms,
                    "burst_count": burst_count,
                    "burst_gap_ms": burst_gap_ms,
                }
            return {"raw": data.hex()}
        except BleakError as e:
            logger.error("Failed to read config: %s", e)
            return None

    async def read_status(self) -> Optional[int]:
        """Read the current cueing status from the earbud."""
        if not await self._ensure_connected():
            return None
        try:
            data = await self._client.read_gatt_char(CUE_STATUS_CHAR_UUID)
            return data[0] if data else None
        except BleakError as e:
            logger.error("Failed to read status: %s", e)
            return None

    async def wait_for_status(self, timeout: float = 2.0) -> Optional[int]:
        """Wait for a status notification. Returns the status byte or None."""
        self._status_event.clear()
        try:
            await asyncio.wait_for(self._status_event.wait(), timeout=timeout)
            return self._current_status
        except asyncio.TimeoutError:
            return None

    def export_latency_log(self) -> list[dict]:
        """Return the operation timestamp log for post-hoc latency analysis."""
        return list(self._op_timestamps)

    def clear_latency_log(self):
        self._op_timestamps.clear()

    # ---- HERMES Consumer interface ----

    async def setup(self):
        """Called by HERMES on pipeline start. Establishes BLE connection."""
        self._running = True
        connected = await self.connect()
        if not connected:
            raise RuntimeError(
                f"Failed to connect to PineBuds Pro '{self.device_name}'"
            )

    async def process(self, data: Any):
        """
        Called by HERMES when a new data item arrives from upstream.

        Expected data format (dict):
            {"action": "start", "tone_id": 0, "volume": 80}
            {"action": "stop"}
            {"action": "configure", "tone_id": 0, "volume": 80,
             "duration_ms": 500, "burst_count": 1, "burst_gap_ms": 0}
        """
        if not isinstance(data, dict):
            logger.warning("CueingConsumer received non-dict data: %s",
                           type(data))
            return

        action = data.get("action", "").lower()

        if action == "start":
            await self.start_cue(
                tone_id=data.get("tone_id", 0),
                volume=data.get("volume", 80),
            )
        elif action == "stop":
            await self.stop_cue()
        elif action == "configure":
            await self.configure(
                tone_id=data.get("tone_id", 0),
                volume=data.get("volume", 80),
                duration_ms=data.get("duration_ms", 500),
                burst_count=data.get("burst_count", 1),
                burst_gap_ms=data.get("burst_gap_ms", 0),
            )
        else:
            logger.warning("Unknown cueing action: %s", action)

    async def teardown(self):
        """Called by HERMES on pipeline stop. Disconnects BLE."""
        await self.stop_cue()
        await self.disconnect()


async def _demo():
    """Standalone demo: connect, configure burst, cue, disconnect."""
    logging.basicConfig(level=logging.INFO)
    consumer = CueingConsumer()
    await consumer.setup()

    cfg = await consumer.read_config()
    logger.info("Current config: %s", cfg)

    await consumer.configure(tone_id=0, volume=80, duration_ms=300,
                             burst_count=3, burst_gap_ms=200)
    await asyncio.sleep(0.5)

    await consumer.start_cue(tone_id=0, volume=80)
    status = await consumer.wait_for_status(timeout=2.0)
    logger.info("Status after start: 0x%02x", status or 0)

    await asyncio.sleep(3.0)
    await consumer.stop_cue()

    logger.info("Operation log: %s", consumer.export_latency_log())
    await consumer.teardown()


if __name__ == "__main__":
    asyncio.run(_demo())
