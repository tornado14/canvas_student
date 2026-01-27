from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.components.diagnostics import async_redact_data

from .const import DOMAIN


# If anything sensitive ever ends up in these structures, HA will redact it.
TO_REDACT = {
    "access_token",
    "token",
    "authorization",
    "cookie",
    "set-cookie",
    "client_secret",
    "refresh_token",
}


def _summarize_counts(mapping: dict[str, list[dict[str, Any]]] | None) -> dict[str, int]:
    """Return per-course counts without dumping full assignment payloads."""
    if not isinstance(mapping, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in mapping.items():
        if isinstance(v, list):
            out[str(k)] = len(v)
    return out


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinator = domain_data.get(entry.entry_id)

    diag: dict[str, Any] = {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            # Do NOT include auth fields from entry.data; we only include safe basics.
            "data": {
                "base_url": (entry.data or {}).get("base_url"),
                "school_name": (entry.data or {}).get("school_name"),
            },
            "options": dict(entry.options or {}),
        }
    }

    # Add coordinator snapshot (safe + summarized)
    if coordinator is not None:
        data = getattr(coordinator, "data", {}) or {}

        diag["coordinator"] = {
            "last_update_success": getattr(coordinator, "last_update_success", None),
            "last_update": getattr(coordinator, "last_update", None),
            "update_interval": str(getattr(coordinator, "update_interval", None)),
            "courses_total": data.get("courses_total"),
            "grades_total": data.get("grades_total"),
            "options_applied": data.get("options_applied"),
            "course_names_by_id": data.get("course_names_by_id"),
            "counts": {
                "assignments_by_course": _summarize_counts(data.get("assignments_by_course")),
                "missing_by_course": _summarize_counts(data.get("missing_by_course")),
                "undated_outstanding_by_course": _summarize_counts(data.get("undated_outstanding_by_course")),
            },
        }

    # Redact anything that matches common secret-ish keys
    return async_redact_data(diag, TO_REDACT)

