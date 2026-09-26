"""Test clock synchronization alongside measurement polling."""

from unittest.mock import MagicMock, call, patch

import pytest
from terrestream_local.errors import ClientError

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from tests.common import MockConfigEntry


@pytest.mark.parametrize(
    ("elapsed", "expected_epochs"),
    [
        pytest.param(5, [1767225600], id="five-second-poll"),
        pytest.param(59.999, [1767225600], id="before-deadline"),
        pytest.param(60, [1767225600, 1767225660], id="at-deadline"),
        pytest.param(65, [1767225600, 1767225665], id="after-deadline"),
    ],
)
async def test_clock_sync_throttle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    elapsed: float,
    expected_epochs: list[int],
) -> None:
    """Send integer UTC time at setup and at most once per 60 seconds."""
    with patch("homeassistant.components.terrestream_local.coordinator.time") as clock:
        clock.monotonic.return_value = 1000.0
        clock.time.return_value = 1767225600.5
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        mock_client.command.assert_awaited_once_with(
            "time", epoch=1767225600, uncertainty_ms=1000
        )

        clock.monotonic.return_value += elapsed
        clock.time.return_value += elapsed
        await config_entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

        assert mock_client.refresh.await_count == 2
        assert mock_client.command.await_args_list == [
            call("time", epoch=epoch, uncertainty_ms=1000) for epoch in expected_epochs
        ]
        await hass.config_entries.async_unload(config_entry.entry_id)


async def test_storage_repair_lifecycle(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Missing health data cannot clear an actionable storage failure."""
    mock_client.refresh.return_value["health"] = {"preferences_storage_ok": False}
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    registry = issue_registry
    issue_id = f"{config_entry.entry_id}_storage"
    assert registry.async_get_issue("terrestream_local", issue_id) is not None

    mock_client.refresh.return_value["health"] = {}
    await config_entry.runtime_data.async_refresh()
    assert registry.async_get_issue("terrestream_local", issue_id) is not None

    mock_client.refresh.return_value["health"] = {"preferences_storage_ok": True}
    await config_entry.runtime_data.async_refresh()
    assert registry.async_get_issue("terrestream_local", issue_id) is None

    mock_client.refresh.return_value["health"] = {"preferences_storage_ok": False}
    await config_entry.runtime_data.async_refresh()
    assert registry.async_get_issue("terrestream_local", issue_id) is not None
    await hass.config_entries.async_unload(config_entry.entry_id)
    assert registry.async_get_issue("terrestream_local", issue_id) is None


async def test_connection_transition_logging(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log an outage and recovery once, not on each failed poll."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    caplog.clear()
    snapshot = mock_client.refresh.return_value
    mock_client.refresh.side_effect = [
        ClientError("offline"),
        ClientError("offline"),
        snapshot,
    ]
    await config_entry.runtime_data.async_refresh()
    await config_entry.runtime_data.async_refresh()
    await config_entry.runtime_data.async_refresh()
    messages = [
        record.message
        for record in caplog.records
        if record.name == "homeassistant.components.terrestream_local.coordinator"
    ]
    assert sum("Error fetching" in message for message in messages) == 1
    assert (
        sum("Fetching" in message and "recovered" in message for message in messages)
        == 1
    )
    await hass.config_entries.async_unload(config_entry.entry_id)
