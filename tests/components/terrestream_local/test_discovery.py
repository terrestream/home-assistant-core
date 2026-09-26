"""Test local discovery without trusting unauthenticated network metadata."""

from ipaddress import ip_address
from unittest.mock import AsyncMock, patch

import pytest
from terrestream_local.errors import AuthenticationError, ClientError

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import CREDENTIALS, UUID

from tests.common import MockConfigEntry


def discovery(properties: dict[str, str]) -> ZeroconfServiceInfo:
    """Create an announcement using documentation-only network addresses."""
    return ZeroconfServiceInfo(
        ip_address=ip_address("192.0.2.10"),
        ip_addresses=[ip_address("192.0.2.10")],
        hostname="sensor.local.",
        name="sensor._terrestream._tcp.local.",
        port=6053,
        type="_terrestream._tcp.local.",
        properties=properties,
    )


async def test_discovery_pairing(hass: HomeAssistant) -> None:
    """Discovering a sensor still requires physical authorization."""
    result = await hass.config_entries.flow.async_init(
        "terrestream_local",
        context={"source": "zeroconf"},
        data=discovery({"uuid": UUID}),
    )
    assert result["type"] is FlowResultType.FORM
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
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.0.2.10", "code": "00123456"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert pair.call_args.kwargs["expected_uuid"] == UUID


@pytest.mark.parametrize("properties", [{}, {"uuid": "invalid"}])
async def test_invalid_discovery(
    hass: HomeAssistant, properties: dict[str, str]
) -> None:
    """Discard incomplete or malformed announcements without contacting a host."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.Client"
    ) as client:
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "zeroconf"},
            data=discovery(properties),
        )
    assert result["reason"] == "invalid_discovery"
    client.assert_not_called()


async def test_authenticated_address_update(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Update an existing entry only after authentication at the new address."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.Client", autospec=True
    ) as client:
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "zeroconf"},
            data=discovery({"uuid": UUID}),
        )
    client.return_value.identity.assert_awaited_once()
    assert client.call_args.args[2] == CREDENTIALS
    assert result["reason"] == "already_configured"
    assert config_entry.data["host"] == "192.0.2.10"
    assert len(hass.config_entries.async_entries("terrestream_local")) == 1


@pytest.mark.parametrize(
    "error", [AuthenticationError("pin"), ClientError("offline"), ValueError("address")]
)
async def test_untrusted_address_rejected(
    hass: HomeAssistant, config_entry: MockConfigEntry, error: Exception
) -> None:
    """Forged announcements cannot overwrite a paired sensor's endpoint."""
    with patch(
        "homeassistant.components.terrestream_local.config_flow.Client", autospec=True
    ) as client:
        client.return_value.identity.side_effect = error
        result = await hass.config_entries.flow.async_init(
            "terrestream_local",
            context={"source": "zeroconf"},
            data=discovery({"uuid": UUID}),
        )
    assert result["reason"] == "cannot_connect"
    assert config_entry.data["host"] == "sensor.local"
