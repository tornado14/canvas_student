from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime
import json

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_BASE_URL,
    CONF_ACCESS_TOKEN,
    CONF_SCHOOL_NAME,
    CONF_STUDENT_NAME,
    OPT_HIDE_EMPTY,
    OPT_DAYS_AHEAD,
    OPT_ANN_DAYS,
    OPT_MISS_LOOKBACK,
    OPT_UPDATE_MINUTES,
    OPT_ENABLE_GPA,
    OPT_GPA_SCALE,
    OPT_CREDITS_MAP,
    OPT_COURSE_END_DATES_MAP,
    OPT_HIDE_COURSES,
    DEFAULT_HIDE_EMPTY,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_ANNOUNCEMENT_DAYS,
    DEFAULT_MISSING_LOOKBACK,
    DEFAULT_UPDATE_MINUTES,
    DEFAULT_ENABLE_GPA,
    DEFAULT_GPA_SCALE,
)
from .simple_client import CanvasClient, CanvasApiError


def _validate_yyyy_mm_dd(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("empty")
    # Accept strictly YYYY-MM-DD
    datetime.strptime(value, "%Y-%m-%d")
    return value


class CanvasStudentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        errors: Dict[str, str] = {}

        if user_input is not None:
            base_url = (user_input.get(CONF_BASE_URL) or "").strip().rstrip("/")
            token = (user_input.get(CONF_ACCESS_TOKEN) or "").strip()
            school = (user_input.get(CONF_SCHOOL_NAME) or "").strip()
            student = (user_input.get(CONF_STUDENT_NAME) or "").strip()

            # Validate credentials
            try:
                session = async_get_clientsession(self.hass)
                client = CanvasClient(base_url, token, session=session)
                await client.get_user_self()
            except CanvasApiError:
                errors["base"] = "auth"
            except Exception:
                errors["base"] = "cannot_connect"

            if not errors:
                # One entry per (base_url + student + school) combo
                await self.async_set_unique_id(f"{base_url}|{school}|{student}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"{school} - {student or 'Student'}",
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_ACCESS_TOKEN: token,
                        CONF_SCHOOL_NAME: school,
                        CONF_STUDENT_NAME: student,
                    },
                    options={},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_BASE_URL): str,
                vol.Required(CONF_ACCESS_TOKEN): str,
                vol.Required(CONF_SCHOOL_NAME): str,
                vol.Optional(CONF_STUDENT_NAME, default="Student"): str,
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> "CanvasStudentOptionsFlow":
        return CanvasStudentOptionsFlow(config_entry)


class CanvasStudentOptionsFlow(config_entries.OptionsFlowWithConfigEntry):
    """Per-entry options flow (wizard style)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__(config_entry)
        self._courses: list[dict[str, Any]] = []
        self._key_to_cid: dict[str, str] = {}

    async def _ensure_courses_loaded(self) -> None:
        if self._courses:
            return
        base_url = self.config_entry.data.get(CONF_BASE_URL)
        token = self.config_entry.data.get(CONF_ACCESS_TOKEN)
        session = async_get_clientsession(self.hass)
        client = CanvasClient(base_url, token, session=session)
        courses = await client.list_courses()
        # Build stable mapping for UI: "Course Name (12345)" -> "12345"
        key_to_cid: dict[str, str] = {}
        for c in courses:
            cid = str(c.get("id"))
            name = c.get("name") or c.get("course_code") or cid
            key = f"{name} ({cid})"
            # Avoid collisions if Canvas returns duplicates
            if key in key_to_cid and key_to_cid[key] != cid:
                key = f"{name} ({cid})"
            key_to_cid[key] = cid
        self._courses = courses
        self._key_to_cid = key_to_cid

    def _cid_to_key(self, cid: str) -> str | None:
        cid = str(cid)
        for k, v in self._key_to_cid.items():
            if v == cid:
                return k
        return None

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        await self._ensure_courses_loaded()

        cur = self.config_entry.options or {}
        errors: Dict[str, str] = {}

        # Current option values
        hide_default = bool(cur.get(OPT_HIDE_EMPTY, DEFAULT_HIDE_EMPTY))
        days_default = int(cur.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
        ann_default = int(cur.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
        miss_default = int(cur.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))
        upd_default = int(cur.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))
        enable_gpa_default = bool(cur.get(OPT_ENABLE_GPA, DEFAULT_ENABLE_GPA))
        gpa_scale_default = cur.get(OPT_GPA_SCALE, DEFAULT_GPA_SCALE)

        credits_default_raw = cur.get(OPT_CREDITS_MAP, {})
        credits_default_text = json.dumps(credits_default_raw, indent=2) if isinstance(credits_default_raw, dict) else str(credits_default_raw or "{}")

        end_dates_map = cur.get(OPT_COURSE_END_DATES_MAP, {})
        if not isinstance(end_dates_map, dict):
            end_dates_map = {}

        hide_courses_raw = cur.get(OPT_HIDE_COURSES, [])
        if not isinstance(hide_courses_raw, list):
            hide_courses_raw = []

        # Convert stored IDs -> UI keys
        hide_keys_default: list[str] = []
        for cid in hide_courses_raw:
            k = self._cid_to_key(str(cid))
            if k:
                hide_keys_default.append(k)

        actions = {
            "save": "Save options",
            "enddate_add": "Add / update a course end date",
            "enddate_remove": "Remove a course end date",
            "credits_add": "Add / update course credits",
            "credits_remove": "Remove course credits",
        }

        if user_input is not None:
            action = user_input.get("action", "save")

            # Always save base options from this screen
            new_opts: dict[str, Any] = dict(cur)

            new_opts[OPT_HIDE_EMPTY] = bool(user_input.get(OPT_HIDE_EMPTY))
            new_opts[OPT_DAYS_AHEAD] = int(user_input.get(OPT_DAYS_AHEAD))
            new_opts[OPT_ANN_DAYS] = int(user_input.get(OPT_ANN_DAYS))
            new_opts[OPT_MISS_LOOKBACK] = int(user_input.get(OPT_MISS_LOOKBACK))
            new_opts[OPT_UPDATE_MINUTES] = int(user_input.get(OPT_UPDATE_MINUTES))
            new_opts[OPT_ENABLE_GPA] = bool(user_input.get(OPT_ENABLE_GPA))
            new_opts[OPT_GPA_SCALE] = user_input.get(OPT_GPA_SCALE)

            # Credits map (still JSON like today)
            credits_text = (user_input.get("credits_map_text") or "").strip()
            try:
                parsed = json.loads(credits_text or "{}")
                if not isinstance(parsed, dict):
                    raise ValueError("not dict")
                new_opts[OPT_CREDITS_MAP] = parsed
            except Exception:
                errors["credits_map_text"] = "invalid_json"
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema_init(
                        hide_default,
                        days_default,
                        ann_default,
                        miss_default,
                        upd_default,
                        enable_gpa_default,
                        gpa_scale_default,
                        credits_default_text,
                        hide_keys_default,
                        actions,
                    ),
                    errors=errors,
                )

            # Hide courses selector -> store as IDs
            hide_keys = user_input.get(OPT_HIDE_COURSES, []) or []
            hide_ids: list[str] = []
            if isinstance(hide_keys, list):
                for k in hide_keys:
                    cid = self._key_to_cid.get(k)
                    if cid:
                        hide_ids.append(str(cid))
            new_opts[OPT_HIDE_COURSES] = sorted(set(hide_ids), key=lambda x: int(x) if x.isdigit() else x)

            # Persist base options now (so add/remove steps don't lose them)
            self.hass.config_entries.async_update_entry(self.config_entry, options=new_opts)

            if action == "enddate_add":
                return await self.async_step_enddate_add()
            if action == "enddate_remove":
                return await self.async_step_enddate_remove()
            if action == "credits_add":
                return await self.async_step_credits_add()
            if action == "credits_remove":
                return await self.async_step_credits_remove()


            return self.async_create_entry(title="", data=new_opts)

        return self.async_show_form(
            step_id="init",
            data_schema=self._schema_init(
                hide_default,
                days_default,
                ann_default,
                miss_default,
                upd_default,
                enable_gpa_default,
                gpa_scale_default,
                credits_default_text,
                hide_keys_default,
                actions,
            ),
            errors=errors,
        )

    def _schema_init(
        self,
        hide_default: bool,
        days_default: int,
        ann_default: int,
        miss_default: int,
        upd_default: int,
        enable_gpa_default: bool,
        gpa_scale_default: str,
        credits_default_text: str,
        hide_keys_default: list[str],
        actions: dict[str, str],
    ) -> vol.Schema:
        course_keys = sorted(self._key_to_cid.keys(), key=lambda s: s.lower())
        return vol.Schema(
            {
                vol.Optional("action", default="save"): SelectSelector(
                    SelectSelectorConfig(options=[{"value": k, "label": v} for k, v in actions.items()], mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Optional(OPT_HIDE_COURSES, default=hide_keys_default): SelectSelector(
                    SelectSelectorConfig(options=course_keys, mode=SelectSelectorMode.DROPDOWN, multiple=True)
                ),
                vol.Optional(OPT_HIDE_EMPTY, default=hide_default): bool,
                vol.Optional(OPT_DAYS_AHEAD, default=days_default): int,
                vol.Optional(OPT_ANN_DAYS, default=ann_default): int,
                vol.Optional(OPT_MISS_LOOKBACK, default=miss_default): int,
                vol.Optional(OPT_UPDATE_MINUTES, default=upd_default): int,
                vol.Optional(OPT_ENABLE_GPA, default=enable_gpa_default): bool,
                vol.Optional(OPT_GPA_SCALE, default=gpa_scale_default): str,
                vol.Optional("credits_map_text", default=credits_default_text): str,
            }
        )

    async def async_step_enddate_add(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        await self._ensure_courses_loaded()
        cur = self.config_entry.options or {}
        end_dates_map = cur.get(OPT_COURSE_END_DATES_MAP, {})
        if not isinstance(end_dates_map, dict):
            end_dates_map = {}

        errors: Dict[str, str] = {}

        course_keys = sorted(self._key_to_cid.keys(), key=lambda s: s.lower())

        if user_input is not None:
            key = user_input.get("course_key")
            date_str = (user_input.get("end_date") or "").strip()
            try:
                date_str = _validate_yyyy_mm_dd(date_str)
                cid = self._key_to_cid.get(key)
                if not cid:
                    raise ValueError("bad course")
                end_dates_map = dict(end_dates_map)
                end_dates_map[str(cid)] = date_str
                new_opts = dict(cur)
                new_opts[OPT_COURSE_END_DATES_MAP] = end_dates_map
                return self.async_create_entry(title="", data=new_opts)
            except Exception:
                errors["end_date"] = "invalid_date"

        schema = vol.Schema(
            {
                vol.Required("course_key"): SelectSelector(SelectSelectorConfig(options=course_keys, mode=SelectSelectorMode.DROPDOWN)),
                vol.Required("end_date"): str,
            }
        )
        return self.async_show_form(step_id="enddate_add", data_schema=schema, errors=errors)

    async def async_step_enddate_remove(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        await self._ensure_courses_loaded()
        cur = self.config_entry.options or {}
        end_dates_map = cur.get(OPT_COURSE_END_DATES_MAP, {})
        if not isinstance(end_dates_map, dict):
            end_dates_map = {}

        errors: Dict[str, str] = {}

        # Build list of only courses that currently have an end date
        keyed = []
        for cid in sorted(end_dates_map.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            k = self._cid_to_key(str(cid))
            if k:
                keyed.append(k)

        if user_input is not None:
            key = user_input.get("course_key")
            cid = self._key_to_cid.get(key)
            if cid and str(cid) in end_dates_map:
                end_dates_map = dict(end_dates_map)
                end_dates_map.pop(str(cid), None)
            new_opts = dict(cur)
            new_opts[OPT_COURSE_END_DATES_MAP] = end_dates_map
            return self.async_create_entry(title="", data=new_opts)

        schema = vol.Schema(
            {
                vol.Required("course_key"): SelectSelector(SelectSelectorConfig(options=keyed or course_keys_fallback(self._key_to_cid), mode=SelectSelectorMode.DROPDOWN)),
            }
        )
        return self.async_show_form(step_id="enddate_remove", data_schema=schema, errors=errors)

    async def async_step_credits_add(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        await self._ensure_courses_loaded()
        cur = self.config_entry.options or {}

        credits_map = cur.get(OPT_CREDITS_MAP, {})
        if not isinstance(credits_map, dict):
            credits_map = {}

        errors: Dict[str, str] = {}
        course_keys = sorted(self._key_to_cid.keys(), key=lambda s: s.lower())

        if user_input is not None:
            key = user_input.get("course_key")
            credits_raw = (user_input.get("credits") or "").strip()
            try:
                cid = self._key_to_cid.get(key)
                if not cid:
                    raise ValueError("bad course")

                # allow "3" or "3.0"
                credits_val = float(credits_raw)
                if credits_val <= 0:
                    raise ValueError("credits must be positive")

                credits_map = dict(credits_map)
                credits_map[str(cid)] = credits_val

                new_opts = dict(cur)
                new_opts[OPT_CREDITS_MAP] = credits_map
                return self.async_create_entry(title="", data=new_opts)
            except Exception:
                errors["credits"] = "invalid_credits"

        schema = vol.Schema(
            {
                vol.Required("course_key"): SelectSelector(
                    SelectSelectorConfig(options=course_keys, mode=SelectSelectorMode.DROPDOWN)
                ),
                vol.Required("credits"): str,
            }
        )
        return self.async_show_form(step_id="credits_add", data_schema=schema, errors=errors)

    async def async_step_credits_remove(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        await self._ensure_courses_loaded()
        cur = self.config_entry.options or {}

        credits_map = cur.get(OPT_CREDITS_MAP, {})
        if not isinstance(credits_map, dict):
            credits_map = {}

        # only courses that currently have credits
        keyed = []
        for cid in sorted(credits_map.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
            k = self._cid_to_key(str(cid))
            if k:
                keyed.append(k)

        if user_input is not None:
            key = user_input.get("course_key")
            cid = self._key_to_cid.get(key)
            if cid and str(cid) in credits_map:
                credits_map = dict(credits_map)
                credits_map.pop(str(cid), None)

            new_opts = dict(cur)
            new_opts[OPT_CREDITS_MAP] = credits_map
            return self.async_create_entry(title="", data=new_opts)

        schema = vol.Schema(
            {
                vol.Required("course_key"): SelectSelector(
                    SelectSelectorConfig(
                        options=keyed or course_keys_fallback(self._key_to_cid),
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="credits_remove", data_schema=schema, errors={})


def course_keys_fallback(key_to_cid: dict[str, str]) -> list[str]:
    return sorted(key_to_cid.keys(), key=lambda s: s.lower())
