"""Language and measurement presentation on the device display."""

from typing import cast, override

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TerrestreamConfigEntry, TerrestreamCoordinator
from .entity import SettingEntity

PARALLEL_UPDATES = 0

SETTINGS = {
    "locale": ("en", "fr_ca"),
    "index_mode": ("epa_aqi", "aqhi_plus"),
    "voc_mode": ("voc_index", "well", "reset"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TerrestreamConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add supported presentation choices."""
    caps = entry.runtime_data.data["capabilities"]["settings"]
    async_add_entities(
        PreferenceSelect(entry.runtime_data, key) for key in SETTINGS if key in caps
    )


class PreferenceSelect(SettingEntity, SelectEntity):
    """Choose how the physical sensor displays information."""

    def __init__(self, coordinator: TerrestreamCoordinator, key: str) -> None:
        """Initialize the advertised choices known to this integration."""
        super().__init__(coordinator, key)
        cap = coordinator.data["capabilities"]["settings"][key]
        self._attr_options = [
            option
            for index, option in enumerate(SETTINGS[key])
            if cap["min"] <= index <= cap["max"]
        ]

    @property
    @override
    def current_option(self) -> str | None:
        """Return the confirmed choice, or unknown for a future device option."""
        value = cast(int, self.coordinator.data["settings"][self.key])
        options = SETTINGS[self.key]
        return options[value] if 0 <= value < len(options) else None

    @override
    async def async_select_option(self, option: str) -> None:
        """Apply the corresponding firmware value."""
        await self.coordinator.async_set_setting(
            self.key, SETTINGS[self.key].index(option)
        )
