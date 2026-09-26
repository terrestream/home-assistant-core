"""Pair and rediscover physically authorized Terrestream sensors."""

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any, override
from uuid import UUID

import probatio
from terrestream_local import Client, Credentials, pair_device
from terrestream_local.errors import AuthenticationError, ClientError

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import DOMAIN


class TerrestreamConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure one physically authorized sensor."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize address suggestions and authenticated identity constraints."""
        self._host = ""
        self._expected_uuid: str | None = None

    @override
    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Suggest pairing or authenticate a previously paired sensor's new address."""
        try:
            self._expected_uuid = str(UUID(discovery_info.properties.get("uuid", "")))
        except ValueError:
            return self.async_abort(reason="invalid_discovery")
        self._host = discovery_info.host
        await self.async_set_unique_id(self._expected_uuid)
        entry = self.hass.config_entries.async_entry_for_domain_unique_id(
            DOMAIN, self._expected_uuid
        )
        if entry is not None:
            # An mDNS announcement alone cannot redirect authenticated traffic.
            try:
                await Client(
                    async_get_clientsession(self.hass),
                    self._host,
                    Credentials(**entry.data["credentials"]),
                ).identity()
            except ClientError, ValueError:
                return self.async_abort(reason="cannot_connect")
            self._abort_if_unique_id_configured(updates={"host": self._host})
        self.context["title_placeholders"] = {"name": "Terrestream"}
        return await self.async_step_user()

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Recover credentials without removing the entry or its entity settings."""
        entry = self._get_reauth_entry()
        self._host = entry.data["host"]
        self._expected_uuid = entry.data["credentials"]["uuid"]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require a new physical pairing code for the original sensor."""
        return await self.async_step_user(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate a new address using the saved credentials and certificate pin."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await Client(
                    async_get_clientsession(self.hass),
                    user_input["host"],
                    Credentials(**entry.data["credentials"]),
                ).identity()
            except AuthenticationError:
                errors["base"] = "address_auth_failed"
            except ClientError, ValueError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={"host": user_input["host"]}
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=probatio.Schema(
                {probatio.Required("host", default=entry.data["host"]): str}
            ),
            errors=errors,
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate pairing and prevent duplicate sensor entries."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                credentials, _client = await pair_device(
                    async_get_clientsession(self.hass),
                    user_input["host"],
                    user_input["code"],
                    expected_uuid=self._expected_uuid,
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ClientError, ValueError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(credentials.uuid)
                data = {"host": user_input["host"], "credentials": asdict(credentials)}
                if self.source == SOURCE_REAUTH:
                    self._abort_if_unique_id_mismatch(reason="wrong_device")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(), data_updates=data
                    )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Terrestream", data=data)
        return self.async_show_form(
            step_id="reauth_confirm" if self.source == SOURCE_REAUTH else "user",
            data_schema=probatio.Schema(
                {
                    probatio.Required("host", default=self._host): str,
                    probatio.Required("code"): str,
                }
            ),
            errors=errors,
        )
