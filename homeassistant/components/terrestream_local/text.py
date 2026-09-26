"""Device time zone configuration."""

from typing import cast, override
from zoneinfo import available_timezones

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import TerrestreamConfigEntry, TerrestreamCoordinator
from .entity import SettingEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerrestreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Load time zone names off the event loop."""
    if "timezone" in entry.runtime_data.data["capabilities"]["settings"]:
        zones = await hass.async_add_executor_job(available_timezones)
        async_add_entities([DeviceTimeZone(entry.runtime_data, zones)])


class DeviceTimeZone(SettingEntity, TextEntity):
    """Set an IANA time zone; the sensor validates its own supported database."""

    _attr_native_min = 1
    _attr_native_max = 63

    def __init__(self, coordinator: TerrestreamCoordinator, zones: set[str]) -> None:
        """Initialize local validation without changing the sensor."""
        super().__init__(coordinator, "timezone")
        self._zones = zones

    @property
    @override
    def native_value(self) -> str:
        """Return the confirmed time zone."""
        return cast(str, self.coordinator.data["settings"][self.key])

    @override
    async def async_set_value(self, value: str) -> None:
        """Validate and apply the time zone."""
        if value not in self._zones:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_timezone"
            )
        await self.coordinator.async_set_setting(self.key, value)
