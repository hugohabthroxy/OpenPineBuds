"""
UUID definitions for the PineBuds Pro Audio Cueing GATT Service.

These must match the UUIDs defined in the firmware at:
  services/ble_profiles/cueing/cueingps/src/cueingps.c

The 128-bit UUIDs use the base:
  AC0000xx-CAFE-B0BA-F001-DEADBEEF0000
"""

CUEING_SERVICE_UUID = "ac000001-cafe-b0ba-f001-deadbeef0000"
CUE_CMD_CHAR_UUID = "ac000002-cafe-b0ba-f001-deadbeef0000"
CUE_STATUS_CHAR_UUID = "ac000003-cafe-b0ba-f001-deadbeef0000"
CUE_CONFIG_CHAR_UUID = "ac000004-cafe-b0ba-f001-deadbeef0000"

# Command bytes
CUE_CMD_START = 0x01
CUE_CMD_STOP = 0x02
CUE_CMD_CONFIGURE = 0x03

# Status bytes
CUE_STATUS_IDLE = 0x00
CUE_STATUS_CUEING = 0x01
CUE_STATUS_ERROR = 0xFF
