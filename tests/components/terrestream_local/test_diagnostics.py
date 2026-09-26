"""Test support diagnostics and exclusion of private payloads."""

import json
from unittest.mock import MagicMock

import pytest

from homeassistant.components.terrestream_local.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant

from .conftest import CREDENTIALS, UUID

from tests.common import MockConfigEntry


@pytest.mark.parametrize(
    ("firmware", "expected"), [("4.1.0", "4.1.0"), ("private-person", "unknown")]
)
async def test_diagnostics_allowlist(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    firmware: str,
    expected: str,
) -> None:
    """Free-form endpoint fields and readings must not escape the allowlist."""
    data = mock_client.refresh.return_value
    data.update(
        {
            "firmware": firmware,
            "uuid": UUID,
            "model": "private-person",
            "hardware": "private-person",
            "session": CREDENTIALS.token,
            "boot": "private-person",
        }
    )
    data["measurements"]["co2"]["status"] = "private-person"
    data["measurements"]["private-person"] = {"status": "valid", "value": 777777}
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    assert result["firmware"] == expected
    assert result["last_update_success"] is True
    assert result["measurement_status"]["co2"] == "unknown"
    assert len(result["measurement_status"]) == 12
    payload = json.dumps(result)
    for private in (
        UUID,
        CREDENTIALS.token,
        CREDENTIALS.fingerprint,
        "sensor.local",
        "private-person",
        "777777",
        '"value"',
    ):
        assert private not in payload
    await hass.config_entries.async_unload(config_entry.entry_id)
