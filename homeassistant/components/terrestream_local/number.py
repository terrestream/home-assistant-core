"""Device brightness and volume levels."""

from typing import cast, override

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .coordinator import TerrestreamConfigEntry, TerrestreamCoordinator
from .entity import SettingEntity

PARALLEL_UPDATES = 0

SETTINGS = (
    "display_brightness",
    "ring_brightness",
    "volume",
    "quiet_display",
    "quiet_ring",
    "quiet_volume",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerrestreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add numeric preferences with device-advertised limits."""
    caps = entry.runtime_data.data["capabilities"]["settings"]
    async_add_entities(
        PreferenceNumber(entry.runtime_data, key) for key in SETTINGS if key in caps
    )


class PreferenceNumber(SettingEntity, NumberEntity):
    """Control a level in the device's native scale."""

    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: TerrestreamCoordinator, key: str) -> None:
        """Initialize the supported range."""
        super().__init__(coordinator, key)
        cap = coordinator.data["capabilities"]["settings"][key]
        self._attr_native_min_value = cap["min"]
        self._attr_native_max_value = cap["max"]

    @property
    @override
    def native_value(self) -> int:
        """Return the confirmed level."""
        return cast(int, self.coordinator.data["settings"][self.key])

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Apply a whole-number level."""
        if not value.is_integer():
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="whole_number"
            )
        await self.coordinator.async_set_setting(self.key, int(value))
