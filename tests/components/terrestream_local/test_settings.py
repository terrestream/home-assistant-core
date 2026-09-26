"""Test preference controls through Home Assistant's entity actions."""

import asyncio
from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion
from terrestream_local import Credentials
from terrestream_local.errors import AuthenticationError, ClientError

from homeassistant.const import STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import UUID

from tests.common import MockConfigEntry, snapshot_platform

# Independent firmware-contract examples, including native ranges and local times.
PREFERENCES = {
    "dark_mode": (0, 0, 1),
    "fahrenheit": (0, 0, 1),
    "time_24h": (0, 0, 1),
    "auto_brightness": (0, 0, 1),
    "quiet_hours": (0, 0, 1),
    "ui_sounds": (0, 0, 1),
    "notification_sounds": (0, 0, 1),
    "display_brightness": (100, 10, 255),
    "ring_brightness": (20, 0, 64),
    "volume": (5, 0, 10),
    "quiet_display": (10, 1, 255),
    "quiet_ring": (2, 0, 64),
    "quiet_volume": (1, 0, 10),
    "locale": (0, 0, 1),
    "index_mode": (0, 0, 1),
    "voc_mode": (0, 0, 2),
    "quiet_start": (1320, 0, 1439),
    "quiet_end": (420, 0, 1439),
}


@pytest.fixture
def preferences(mock_client: MagicMock) -> None:
    """Advertise all supported preferences without applying optimistic writes."""
    data = mock_client.refresh.return_value
    data["settings"] = {key: value for key, (value, _, _) in PREFERENCES.items()}
    data["settings"]["timezone"] = "UTC"
    data["capabilities"] = {
        "settings": {
            key: {"type": "integer", "min": minimum, "max": maximum}
            for key, (_, minimum, maximum) in PREFERENCES.items()
        }
    }
    data["capabilities"]["settings"]["timezone"] = {"type": "iana_timezone"}


def entity_id(
    registry: er.EntityRegistry, domain: str, key: str, uuid: str = UUID
) -> str:
    """Find a preference by stable device identity."""
    result = registry.async_get_entity_id(domain, "terrestream_local", f"{uuid}_{key}")
    assert result is not None
    return result


@pytest.mark.usefixtures("preferences")
@pytest.mark.parametrize(
    ("platform", "count"),
    [
        (Platform.SWITCH, 7),
        (Platform.NUMBER, 6),
        (Platform.SELECT, 3),
        (Platform.TIME, 2),
        (Platform.TEXT, 1),
    ],
)
async def test_settings_snapshot(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    platform: Platform,
    count: int,
) -> None:
    """Expose native configuration entities with translated names and device identity."""
    with patch("homeassistant.components.terrestream_local.PLATFORMS", [platform]):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert (
        len(er.async_entries_for_config_entry(entity_registry, config_entry.entry_id))
        == count
    )
    await snapshot_platform(hass, entity_registry, snapshot, config_entry.entry_id)
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
@pytest.mark.parametrize(
    ("domain", "key", "action", "arguments", "expected"),
    [
        *[
            ("switch", key, "turn_on", {}, 1)
            for key in (
                "dark_mode",
                "fahrenheit",
                "time_24h",
                "auto_brightness",
                "quiet_hours",
                "ui_sounds",
                "notification_sounds",
            )
        ],
        ("switch", "dark_mode", "turn_off", {}, 0),
        ("number", "display_brightness", "set_value", {"value": 255}, 255),
        ("number", "ring_brightness", "set_value", {"value": 0}, 0),
        ("number", "volume", "set_value", {"value": 10}, 10),
        ("number", "quiet_display", "set_value", {"value": 1}, 1),
        ("number", "quiet_ring", "set_value", {"value": 64}, 64),
        ("number", "quiet_volume", "set_value", {"value": 0}, 0),
        ("select", "locale", "select_option", {"option": "fr_ca"}, 1),
        ("select", "index_mode", "select_option", {"option": "aqhi_plus"}, 1),
        ("select", "voc_mode", "select_option", {"option": "reset"}, 2),
        ("time", "quiet_start", "set_value", {"time": "23:45:00"}, 1425),
        ("time", "quiet_end", "set_value", {"time": "00:00:00"}, 0),
        ("text", "timezone", "set_value", {"value": "Europe/London"}, "Europe/London"),
    ],
)
async def test_write_and_readback(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    domain: str,
    key: str,
    action: str,
    arguments: dict[str, str | int],
    expected: str | int,
) -> None:
    """Every control sends the correct native value and immediately reads it back."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.command.reset_mock()
    mock_client.refresh.reset_mock()
    target = entity_id(entity_registry, domain, key)
    initial = hass.states.get(target).state
    await hass.services.async_call(
        domain, action, {"entity_id": target, **arguments}, blocking=True
    )
    mock_client.command.assert_awaited_once_with("set", key=key, value=expected)
    mock_client.refresh.assert_awaited_once()
    # A device that still reports the previous value must not appear updated.
    assert hass.states.get(target).state == initial
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
@pytest.mark.parametrize(
    ("domain", "key", "arguments"),
    [
        ("number", "volume", {"value": 1.5}),
        ("number", "volume", {"value": 11}),
        ("time", "quiet_start", {"time": "12:00:01"}),
        ("text", "timezone", {"value": "Not/A_Timezone"}),
    ],
)
async def test_invalid_values(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    domain: str,
    key: str,
    arguments: dict[str, str | float],
) -> None:
    """Invalid inputs never reach the device."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.command.reset_mock()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            domain,
            "set_value",
            {"entity_id": entity_id(entity_registry, domain, key), **arguments},
            blocking=True,
        )
    mock_client.command.assert_not_awaited()
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
@pytest.mark.parametrize(
    "reason", ["busy", "revision_conflict", "storage_failure", "private endpoint error"]
)
async def test_rejected_write(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
    reason: str,
) -> None:
    """Report command failures without exposing arbitrary endpoint details."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.command.side_effect = ClientError(reason)
    target = entity_id(entity_registry, "switch", "dark_mode")
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": target}, blocking=True
        )
    assert error.value.translation_key in {
        "busy",
        "revision_conflict",
        "storage_failure",
        "command_failed",
    }
    assert "private endpoint" not in str(error.value)
    assert hass.states.get(target).state == "off"
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
async def test_readback_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """A successful send with failed readback is explicitly uncertain."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.refresh.side_effect = ClientError("offline")
    target = entity_id(entity_registry, "switch", "dark_mode")
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": target}, blocking=True
        )
    assert error.value.translation_key == "readback_failed"
    assert hass.states.get(target).state == STATE_UNAVAILABLE
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
async def test_external_changes_and_capability_removal(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Reflect settings changed on-device and stop exposing removed controls."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    data = mock_client.refresh.return_value
    data["settings"]["dark_mode"] = 1
    data["settings"]["quiet_start"] = 30
    data["settings"]["voc_mode"] = 99
    del data["capabilities"]["settings"]["volume"]
    await config_entry.runtime_data.async_refresh()
    assert (
        hass.states.get(entity_id(entity_registry, "switch", "dark_mode")).state == "on"
    )
    assert (
        hass.states.get(entity_id(entity_registry, "time", "quiet_start")).state
        == "00:30:00"
    )
    assert (
        hass.states.get(entity_id(entity_registry, "select", "voc_mode")).state
        == "unknown"
    )
    assert (
        hass.states.get(entity_id(entity_registry, "number", "volume")).state
        == STATE_UNAVAILABLE
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
async def test_revoked_write(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Revoked credentials make controls unavailable and initiate repair."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    mock_client.command.side_effect = AuthenticationError("revoked")
    target = entity_id(entity_registry, "switch", "dark_mode")
    with pytest.raises(HomeAssistantError) as error:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": target}, blocking=True
        )
    assert error.value.translation_key == "pairing_revoked"
    await hass.async_block_till_done()
    assert hass.states.get(target).state == STATE_UNAVAILABLE
    assert (
        hass.config_entries.flow.async_progress_by_handler("terrestream_local")[0][
            "context"
        ]["source"]
        == "reauth"
    )
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
async def test_multiple_devices(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    entity_registry: er.EntityRegistry,
) -> None:
    """Settings actions affect only the selected physical device."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    other_uuid = "00000000-0000-4000-8000-000000000002"
    other = deepcopy(mock_client)
    other.credentials = Credentials(other_uuid, "ef" * 32, "12" * 32)
    data = deepcopy(dict(config_entry.data))
    data["credentials"]["uuid"] = other_uuid
    entry = MockConfigEntry(domain="terrestream_local", unique_id=other_uuid, data=data)
    entry.add_to_hass(hass)
    with patch("homeassistant.components.terrestream_local.Client", return_value=other):
        assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    mock_client.command.reset_mock()
    other.command.reset_mock()
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": entity_id(entity_registry, "switch", "dark_mode", other_uuid)},
        blocking=True,
    )
    other.command.assert_awaited_once_with("set", key="dark_mode", value=1)
    mock_client.command.assert_not_awaited()
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.config_entries.async_unload(config_entry.entry_id)


@pytest.mark.usefixtures("preferences")
async def test_commands_serialized_through_readback(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
) -> None:
    """A second edit cannot overtake the first edit's device readback."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    entered = asyncio.Event()
    resume = asyncio.Event()
    calls = []

    async def command(method: str, **arguments: str | int) -> dict[str, bool]:
        calls.append(arguments["value"])
        entered.set()
        await resume.wait()
        return {"ok": True}

    mock_client.command.side_effect = command
    first = hass.async_create_task(
        config_entry.runtime_data.async_set_setting("volume", 1)
    )
    await entered.wait()
    second = hass.async_create_task(
        config_entry.runtime_data.async_set_setting("volume", 2)
    )
    await asyncio.sleep(0)
    assert calls == [1]
    resume.set()
    await asyncio.gather(first, second)
    assert calls == [1, 2]
    mock_client.command.side_effect = None
    await hass.config_entries.async_unload(config_entry.entry_id)
