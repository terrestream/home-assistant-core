"""Expose support diagnostics without credentials, addresses, or measurements."""

import re
from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import TerrestreamConfigEntry
from .sensor import SENSORS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TerrestreamConfigEntry
) -> dict[str, Any]:
    """Export only fixed status labels and a numeric firmware version."""
    coordinator = entry.runtime_data
    data = coordinator.data
    firmware = data.get("firmware", "")
    return {
        "firmware": firmware
        if re.fullmatch(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", firmware)
        else "unknown",
        "last_update_success": coordinator.last_update_success,
        "measurement_status": {
            key: (
                measurement["status"]
                if measurement["status"]
                in {"valid", "warming_up", "stale", "cleaning", "sensor_error"}
                else "unknown"
            )
            for key, measurement in data["measurements"].items()
            if key in SENSORS
        },
    }
