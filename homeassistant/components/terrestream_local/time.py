"""Quiet-hours boundaries in the sensor's configured time zone."""

from datetime import time
from typing import cast, override

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import TerrestreamConfigEntry
from .entity import SettingEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerrestreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add supported quiet-hours time controls."""
    caps = entry.runtime_data.data["capabilities"]["settings"]
    async_add_entities(
        QuietTime(entry.runtime_data, key)
        for key in ("quiet_start", "quiet_end")
        if key in caps
    )


class QuietTime(SettingEntity, TimeEntity):
    """Control a minute-resolution wall-clock time."""

    @property
    @override
    def native_value(self) -> time:
        """Return the confirmed local time."""
        minutes = cast(int, self.coordinator.data["settings"][self.key])
        return time(minutes // 60, minutes % 60)

    @override
    async def async_set_value(self, value: time) -> None:
        """Apply a time without silently discarding seconds or a time zone."""
        if value.second or value.microsecond or value.tzinfo is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="minute_precision"
            )
        await self.coordinator.async_set_setting(
            self.key, value.hour * 60 + value.minute
        )
