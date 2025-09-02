from __future__ import annotations
from typing import Any, Dict
import json
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN, CONF_BASE_URL, CONF_ACCESS_TOKEN, CONF_SCHOOL_NAME, CONF_STUDENT_NAME,
    OPT_HIDE_EMPTY, OPT_DAYS_AHEAD, OPT_ANN_DAYS, OPT_MISS_LOOKBACK, OPT_UPDATE_MINUTES,
    DEFAULT_HIDE_EMPTY, DEFAULT_DAYS_AHEAD, DEFAULT_ANNOUNCEMENT_DAYS, DEFAULT_MISSING_LOOKBACK, DEFAULT_UPDATE_MINUTES,
    OPT_ENABLE_GPA, OPT_GPA_SCALE, OPT_CREDITS_MAP, DEFAULT_ENABLE_GPA, DEFAULT_GPA_SCALE,
)
from .simple_client import CanvasClient

# Actions
ACTION = "action"
ACT_VALIDATE = "validate"
ACT_SAVE = "save"
ACT_EDIT_CREDITS = "edit_credits"   # NEW


class CanvasStudentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            token = user_input[CONF_ACCESS_TOKEN].strip()
            school = user_input.get(CONF_SCHOOL_NAME) or base_url.split("//")[-1].split(".")[0].upper()
            title = f"Canvas ({school} - {user_input.get(CONF_STUDENT_NAME, 'Student')})"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_BASE_URL: base_url,
                    CONF_ACCESS_TOKEN: token,
                    CONF_SCHOOL_NAME: school,
                    CONF_STUDENT_NAME: user_input.get(CONF_STUDENT_NAME, ""),
                },
            )

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
    """Per-entry (per school) options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__(config_entry)
        self._last_result: str = "—"
        self._courses: list[dict[str, Any]] = []    # cache between steps
        self._key_to_cid: dict[str, str] = {}       # visible key -> course_id

    async def async_step_init(self, user_input: Dict[str, Any] | None = None):
        cur = self.config_entry.options or {}
        errors: Dict[str, str] = {}

        hide_default = cur.get(OPT_HIDE_EMPTY, DEFAULT_HIDE_EMPTY)
        days_default = int(cur.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        ann_default = int(cur.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
        miss_default = int(cur.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))
        upd_default = int(cur.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))
        enable_gpa_default = bool(cur.get(OPT_ENABLE_GPA, DEFAULT_ENABLE_GPA))
        gpa_scale_default = cur.get(OPT_GPA_SCALE, DEFAULT_GPA_SCALE)
        credits_default_raw = cur.get(OPT_CREDITS_MAP, {})

        if isinstance(credits_default_raw, dict):
            credits_default_text = json.dumps(credits_default_raw, indent=2)
        else:
            credits_default_text = str(credits_default_raw or "{}")

        def build_schema(dd: Dict[str, Any]):
            return vol.Schema({
                vol.Optional(OPT_HIDE_EMPTY, default=dd.get(OPT_HIDE_EMPTY, hide_default)): bool,
                vol.Optional(OPT_DAYS_AHEAD, default=dd.get(OPT_DAYS_AHEAD, days_default)): int,
                vol.Optional(OPT_ANN_DAYS, default=dd.get(OPT_ANN_DAYS, ann_default)): int,
                vol.Optional(OPT_MISS_LOOKBACK, default=dd.get(OPT_MISS_LOOKBACK, miss_default)): int,
                vol.Optional(OPT_UPDATE_MINUTES, default=dd.get(OPT_UPDATE_MINUTES, upd_default)): int,
                vol.Optional(OPT_ENABLE_GPA, default=dd.get(OPT_ENABLE_GPA, enable_gpa_default)): bool,
                vol.Optional(OPT_GPA_SCALE, default=dd.get(OPT_GPA_SCALE, gpa_scale_default)): vol.In(["us_4_0_plusminus","simple_cutoffs"]),
                # Keep JSON fallback for power users; the credits form is in a separate step.
                vol.Optional(OPT_CREDITS_MAP, default=dd.get(OPT_CREDITS_MAP, credits_default_text)): str,
                vol.Optional(CONF_ACCESS_TOKEN, default=dd.get(CONF_ACCESS_TOKEN, "")): str,
                vol.Required(ACTION, default=dd.get(ACTION, ACT_SAVE)): vol.In([ACT_SAVE, ACT_VALIDATE, ACT_EDIT_CREDITS]),
            })

        if user_input is not None:
            action = user_input.get(ACTION)
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()

            # normalize numeric fields
            for k in (OPT_DAYS_AHEAD, OPT_ANN_DAYS, OPT_MISS_LOOKBACK, OPT_UPDATE_MINUTES):
                try:
                    user_input[k] = int(user_input.get(k, cur.get(k)))
                except Exception:
                    errors["base"] = "invalid_number"

            # JSON credits fallback parsing (only if Save pressed here)
            credits_norm = None
            if action == ACT_SAVE:
                credits_raw = user_input.get(OPT_CREDITS_MAP, "").strip() or "{}"
                try:
                    obj = json.loads(credits_raw)
                    if not isinstance(obj, dict):
                        raise ValueError("credits_by_course must be a JSON object")
                    credits_norm = {str(k): float(v) for (k, v) in obj.items()}
                except Exception:
                    errors[OPT_CREDITS_MAP] = "invalid_json"
                    return self.async_show_form(
                        step_id="init",
                        data_schema=build_schema(user_input),
                        errors=errors,
                        description_placeholders={"last_result": self._last_result},
                    )

            # Branches
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

            if action == ACT_EDIT_CREDITS:
                # Go to credits step
                # Persist any token the user typed before we leave this page
                if token:
                    new_data = dict(self.config_entry.data)
                    new_data[CONF_ACCESS_TOKEN] = token
                    self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
                return await self.async_step_credits()

            # Save options (from JSON entry + toggles)
            new_opts = dict(cur)
            new_opts.update({
                OPT_HIDE_EMPTY: bool(user_input.get(OPT_HIDE_EMPTY, hide_default)),
                OPT_DAYS_AHEAD: user_input.get(OPT_DAYS_AHEAD, days_default),
                OPT_ANN_DAYS: user_input.get(OPT_ANN_DAYS, ann_default),
                OPT_MISS_LOOKBACK: user_input.get(OPT_MISS_LOOKBACK, miss_default),
                OPT_UPDATE_MINUTES: user_input.get(OPT_UPDATE_MINUTES, upd_default),
                OPT_ENABLE_GPA: bool(user_input.get(OPT_ENABLE_GPA, enable_gpa_default)),
                OPT_GPA_SCALE: user_input.get(OPT_GPA_SCALE, gpa_scale_default),
            })
            if credits_norm is not None:
                new_opts[OPT_CREDITS_MAP] = credits_norm
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

    async def async_step_credits(self, user_input: Dict[str, Any] | None = None) -> FlowResult:
        """Dynamically build a form with one numeric field per active course."""
        base_url = self.config_entry.data.get(CONF_BASE_URL)
        token = self.config_entry.data.get(CONF_ACCESS_TOKEN) or ""
        session = async_get_clientsession(self.hass)
        client = CanvasClient(base_url, token, session=session)

        # First time: fetch and build the dynamic schema
        if user_input is None:
            try:
                self._courses = await client.list_courses()  # active enrollments only
            except Exception as ex:
                # Show a simple error and return to init if we can't list courses
                return self.async_abort(reason=f"course_fetch_failed: {ex}")

            # Build schema: one float per course, prefilled from existing options
            existing = self.config_entry.options.get(OPT_CREDITS_MAP, {}) or {}
            self._key_to_cid = {}

            sch: Dict[Any, Any] = {}
            # Sort by name for a stable form
            for c in sorted(self._courses, key=lambda x: (x.get("name") or "").lower()):
                cid = str(c.get("id"))
                name = c.get("name") or c.get("course_code") or cid
                key = f"{name} ({cid})"
                self._key_to_cid[key] = cid
                default_val = existing.get(cid, 0)
                # Number input; HA renders numeric fields fine with vol.Coerce(float)
                sch[vol.Optional(key, default=default_val)] = vol.Coerce(float)

            if not sch:
                # No active courses
                return self.async_show_form(
                    step_id="credits",
                    data_schema=vol.Schema({}),
                    description_placeholders={},
                    errors={"base": "no_active_courses"},
                )

            return self.async_show_form(
                step_id="credits",
                data_schema=vol.Schema(sch),
                description_placeholders={},
                errors={},
            )

        # Handle submission: map visible keys back to course IDs
        credits_map: Dict[str, float] = {}
        for key, val in user_input.items():
            cid = self._key_to_cid.get(key)
            if not cid:
                continue
            try:
                f = float(val)
                if f > 0:
                    credits_map[cid] = f
            except Exception:
                # ignore non-numeric/blank entries
                pass

        # Merge into options
        new_opts = dict(self.config_entry.options or {})
        new_opts[OPT_CREDITS_MAP] = credits_map
        return self.async_create_entry(title="", data=new_opts)

