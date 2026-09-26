"""Boolean display and sound preferences."""

from typing import Any, override

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TerrestreamConfigEntry
from .entity import SettingEntity

PARALLEL_UPDATES = 0

SETTINGS = (
    "dark_mode",
    "fahrenheit",
    "time_24h",
    "auto_brightness",
    "quiet_hours",
    "ui_sounds",
    "notification_sounds",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerrestreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add switches supported by this device."""
    caps = entry.runtime_data.data["capabilities"]["settings"]
    async_add_entities(
        PreferenceSwitch(entry.runtime_data, key) for key in SETTINGS if key in caps
    )


class PreferenceSwitch(SettingEntity, SwitchEntity):
    """Control a boolean device preference."""

    @property
    @override
    def is_on(self) -> bool:
        """Return the confirmed setting."""
        return bool(self.coordinator.data["settings"][self.key])

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the preference."""
        await self.coordinator.async_set_setting(self.key, 1)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the preference."""
        await self.coordinator.async_set_setting(self.key, 0)
