from __future__ import annotations
from typing import Any, Dict
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import (
    DOMAIN, CONF_BASE_URL, CONF_ACCESS_TOKEN, CONF_SCHOOL_NAME, CONF_STUDENT_NAME,
    OPT_HIDE_EMPTY, OPT_DAYS_AHEAD, OPT_ANN_DAYS, OPT_MISS_LOOKBACK, OPT_UPDATE_MINUTES,
    DEFAULT_HIDE_EMPTY, DEFAULT_DAYS_AHEAD, DEFAULT_ANNOUNCEMENT_DAYS, DEFAULT_MISSING_LOOKBACK, DEFAULT_UPDATE_MINUTES,
)
from .simple_client import CanvasClient
ACTION = "action"; ACT_VALIDATE = "validate"; ACT_SAVE = "save"

class CanvasStudentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            token = user_input[CONF_ACCESS_TOKEN].strip()
            school = user_input.get(CONF_SCHOOL_NAME) or base_url.split("//")[-1].split(".")[0].upper()
            title = f"Canvas ({school} - {user_input.get(CONF_STUDENT_NAME, 'Student')})"
            return self.async_create_entry(title=title, data={
                CONF_BASE_URL: base_url, CONF_ACCESS_TOKEN: token,
                CONF_SCHOOL_NAME: school, CONF_STUDENT_NAME: user_input.get(CONF_STUDENT_NAME, ""),
            })
        schema = vol.Schema({
            vol.Required(CONF_BASE_URL): str,
            vol.Required(CONF_ACCESS_TOKEN): str,
            vol.Required(CONF_SCHOOL_NAME): str,
            vol.Optional(CONF_STUDENT_NAME): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return CanvasStudentOptionsFlow(config_entry)

class CanvasStudentOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__(config_entry)
        self._last_result: str = "—"

    async def async_step_init(self, user_input: Dict[str, Any] | None = None):
        cur = self.config_entry.options or {}
        errors: Dict[str, str] = {}

        hide_default = cur.get(OPT_HIDE_EMPTY, DEFAULT_HIDE_EMPTY)
        days_default = int(cur.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        ann_default = int(cur.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
        miss_default = int(cur.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))
        upd_default = int(cur.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))

        def build_schema(dd: Dict[str, Any]):
            return vol.Schema({
                vol.Optional(OPT_HIDE_EMPTY, default=dd.get(OPT_HIDE_EMPTY, hide_default)): bool,
                vol.Optional(OPT_DAYS_AHEAD, default=dd.get(OPT_DAYS_AHEAD, days_default)): int,
                vol.Optional(OPT_ANN_DAYS, default=dd.get(OPT_ANN_DAYS, ann_default)): int,
                vol.Optional(OPT_MISS_LOOKBACK, default=dd.get(OPT_MISS_LOOKBACK, miss_default)): int,
                vol.Optional(OPT_UPDATE_MINUTES, default=dd.get(OPT_UPDATE_MINUTES, upd_default)): int,
                vol.Optional(CONF_ACCESS_TOKEN, default=dd.get(CONF_ACCESS_TOKEN, "")): str,
                vol.Required("action", default=dd.get("action", ACT_SAVE)): vol.In([ACT_SAVE, ACT_VALIDATE]),
            })

        if user_input is not None:
            action = user_input.get("action")
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()

            for k in (OPT_DAYS_AHEAD, OPT_ANN_DAYS, OPT_MISS_LOOKBACK, OPT_UPDATE_MINUTES):
                try:
                    user_input[k] = int(user_input.get(k, cur.get(k)))
                except Exception:
                    errors["base"] = "invalid_number"

            if action == ACT_VALIDATE:
                if not token:
                    errors[CONF_ACCESS_TOKEN] = "required"
                else:
                    session = async_get_clientsession(self.hass)
                    client = CanvasClient(self.config_entry.data.get(CONF_BASE_URL), token, session=session)
                    try:
                        me = await client.get_users_self()
                        name = me.get("name") or me.get("short_name") or "unknown"
                        uid = me.get("id")
                        self._last_result = f"✅ Valid — {name} ({uid})"
                    except Exception as ex:
                        self._last_result = f"❌ Invalid — {ex}"
                return self.async_show_form(
                    step_id="init",
                    data_schema=build_schema(user_input),
                    errors=errors,
                    description_placeholders={"last_result": self._last_result},
                )

            new_opts = dict(cur)
            new_opts.update({
                OPT_HIDE_EMPTY: bool(user_input.get(OPT_HIDE_EMPTY, hide_default)),
                OPT_DAYS_AHEAD: user_input.get(OPT_DAYS_AHEAD, days_default),
                OPT_ANN_DAYS: user_input.get(OPT_ANN_DAYS, ann_default),
                OPT_MISS_LOOKBACK: user_input.get(OPT_MISS_LOOKBACK, miss_default),
                OPT_UPDATE_MINUTES: user_input.get(OPT_UPDATE_MINUTES, upd_default),
            })
            if token:
                new_data = dict(self.config_entry.data)
                new_data[CONF_ACCESS_TOKEN] = token
                self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
            return self.async_create_entry(title="", data=new_opts)

        return self.async_show_form(
            step_id="init",
            data_schema=build_schema({}),
            errors=errors,
            description_placeholders={"last_result": self._last_result},
        )
