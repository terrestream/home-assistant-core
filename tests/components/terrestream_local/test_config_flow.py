"""Test physical pairing and duplicate prevention."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from terrestream_local.errors import AuthenticationError, ClientError

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import CREDENTIALS, UUID

from tests.common import MockConfigEntry


async def test_user_form(hass: HomeAssistant) -> None:
    """Show a pairing form without contacting the sensor."""
    result = await hass.config_entries.flow.async_init(
        "terrestream_local", context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_pairing(hass: HomeAssistant) -> None:
    """Persist authenticated identity and preserve leading zeros."""
    with (
        patch(
            "homeassistant.components.terrestream_local.config_flow.pair_device",
            return_value=(CREDENTIALS, AsyncMock()),
        ) as pair,
        patch(
            "homeassistant.components.terrestream_local.async_setup_entry",
            return_value=True,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "user"},
            data={"host": "sensor.local", "code": "00123456"},
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == UUID
    assert result["data"]["credentials"]["fingerprint"] == CREDENTIALS.fingerprint
    assert pair.call_args.args[2] == "00123456"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(AuthenticationError("invalid"), "invalid_auth", id="wrong-code"),
        pytest.param(ClientError("offline"), "cannot_connect", id="offline"),
        pytest.param(ValueError("host"), "cannot_connect", id="invalid-address"),
    ],
)
async def test_pairing_error(
    hass: HomeAssistant, error: Exception, expected: str
) -> None:
    """Keep pairing failures recoverable in the form."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.pair_device",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "user"},
            data={"host": "sensor.local", "code": "00123456"},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_duplicate(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Do not create two entries for the same authenticated UUID."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.pair_device",
        return_value=(CREDENTIALS, AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "user"},
            data={"host": "sensor.local", "code": "00123456"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_preserves_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Replace only the original sensor's credentials and retain its entry."""
    result = await hass.config_entries.flow.async_init(
        "terrestream_local",
        context={"source": "reauth", "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    with (
        patch(
            "homeassistant.components.terrestream_local.config_flow.pair_device",
            return_value=(CREDENTIALS, AsyncMock()),
        ) as pair,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
        ) as reload,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "sensor-new.local", "code": "00123456"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["host"] == "sensor-new.local"
    assert config_entry.unique_id == UUID
    assert len(hass.config_entries.async_entries("terrestream_local")) == 1
    assert pair.call_args.kwargs["expected_uuid"] == UUID
    reload.assert_awaited_once_with(config_entry.entry_id)


async def test_reauth_rejects_another_sensor(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Never attach a different device to the original entity identities."""
    result = await hass.config_entries.flow.async_init(
        "terrestream_local",
        context={"source": "reauth", "entry_id": config_entry.entry_id},
        data=config_entry.data,
    )
    with patch(
        "homeassistant.components.terrestream_local.config_flow.pair_device",
        return_value=(
            replace(CREDENTIALS, uuid="00000000-0000-4000-8000-000000000002"),
            AsyncMock(),
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "other.local", "code": "00123456"}
        )
    assert result["reason"] == "wrong_device"
    assert config_entry.data["host"] == "sensor.local"


async def test_reconfigure(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Check the saved TLS identity before changing the address."""
    result = await hass.config_entries.flow.async_init(
        "terrestream_local",
        context={"source": "reconfigure", "entry_id": config_entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"
    with (
        patch(
            "homeassistant.components.terrestream_local.config_flow.Client",
            autospec=True,
        ) as client,
        patch(
            "homeassistant.config_entries.ConfigEntries.async_reload", return_value=True
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "sensor-new.local"}
        )
        await hass.async_block_till_done()
    client.return_value.identity.assert_awaited_once()
    assert client.call_args.args[2] == CREDENTIALS
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data["host"] == "sensor-new.local"
    assert config_entry.data["credentials"]["fingerprint"] == CREDENTIALS.fingerprint


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AuthenticationError("pin"), "address_auth_failed"),
        (ClientError("offline"), "cannot_connect"),
        (ValueError("host"), "cannot_connect"),
    ],
)
async def test_reconfigure_error(
    hass: HomeAssistant, config_entry: MockConfigEntry, error: Exception, expected: str
) -> None:
    """An unverified address must never replace the saved endpoint."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.Client", autospec=True
    ) as client:
        client.return_value.identity.side_effect = error
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "reconfigure", "entry_id": config_entry.entry_id},
            data={"host": "unverified.local"},
        )
    assert result["errors"] == {"base": expected}
    assert config_entry.data["host"] == "sensor.local"
