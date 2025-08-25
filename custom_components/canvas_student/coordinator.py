from __future__ import annotations

import logging
from datetime import timedelta, datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_DAYS_AHEAD,
    DEFAULT_ANNOUNCEMENT_DAYS,
    DEFAULT_MISSING_LOOKBACK,
    DEFAULT_UPDATE_MINUTES,
    OPT_DAYS_AHEAD,
    OPT_ANN_DAYS,
    OPT_MISS_LOOKBACK,
    OPT_UPDATE_MINUTES,
)
from .simple_client import CanvasClient, CanvasApiError

_LOGGER = logging.getLogger(__name__)

class CanvasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CanvasClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client

        upd_mins = int(entry.options.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))
        super().__init__(
            hass,
            _LOGGER,
            name=f"Canvas ({entry.data.get('school_name', '')})",
            update_interval=timedelta(minutes=upd_mins),
        )
        self.data = {}

    async def _async_update_data(self):
        try:
            base_url = self.entry.data.get("base_url")
            school = self.entry.data.get("school_name")

            days_ahead = int(self.entry.options.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
            ann_days = int(self.entry.options.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
            miss_look = int(self.entry.options.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))

            now = datetime.now(timezone.utc)
            horizon = now + timedelta(days=days_ahead)
            start_anns = now - timedelta(days=ann_days)
            end_anns = now
            missing_cutoff = now - timedelta(days=miss_look)

            courses = await self.client.list_courses()
            course_names = {str(c["id"]): c.get("name") or c.get("course_code") or str(c["id"]) for c in courses}
            grade_urls = {str(c["id"]): f"{base_url}/courses/{c['id']}/grades" for c in courses}

            grades_by_course = {}
            for c in courses:
                cid = str(c["id"])
                try:
                    enr = await self.client.list_enrollments(cid)
                    e = next((e for e in enr if e.get("type") == "StudentEnrollment" or "grades" in e), None)
                    if e and "grades" in e and e["grades"]:
                        g = e["grades"]
                        grades_by_course[cid] = {
                            "current_score": g.get("current_score"),
                            "current_grade": g.get("current_grade"),
                        }
                except Exception:
                    pass

            upcoming_by_course = {}
            for c in courses:
                cid = str(c["id"])
                items = await self.client.list_assignments(cid, bucket="upcoming")
                trimmed = []
                for a in items:
                    due = a.get("due_at")
                    if due:
                        dt = dt_util.parse_datetime(due)
                        if dt is not None and dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt and dt <= horizon:
                            trimmed.append({"id": a.get("id"), "name": a.get("name"), "due_at": a.get("due_at"), "html_url": a.get("html_url")})
                    else:
                        trimmed.append({"id": a.get("id"), "name": a.get("name"), "due_at": None, "html_url": a.get("html_url")})
                upcoming_by_course[cid] = trimmed

            missing_by_course = {}
            for c in courses:
                cid = str(c["id"])
                assignments = await self.client.list_assignments(cid, bucket=None)
                miss_list = []
                for a in assignments:
                    due = a.get("due_at")
                    if due:
                        dt = dt_util.parse_datetime(due)
                        if dt is not None and dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt and dt < missing_cutoff:
                            continue
                    try:
                        sub = await self.client.get_submission_self(cid, a.get("id"))
                        if sub and sub.get("missing"):
                            miss_list.append({"id": a.get("id"), "name": a.get("name"), "due_at": a.get("due_at"), "html_url": a.get("html_url")})
                    except Exception:
                        pass
                if miss_list:
                    missing_by_course[cid] = miss_list

            context_codes = [f"course_{c['id']}" for c in courses]
            announcements = []
            if context_codes:
                anns_raw = await self.client.get_announcements(context_codes, start_anns, end_anns)
                for a in anns_raw:
                    cid = a.get("course_id")
                    if not cid:
                        ctx = a.get("context_code") or ""
                        if ctx.startswith("course_"):
                            cid = int(ctx.split("_", 1)[1])
                    announcements.append({
                        "course_id": cid,
                        "title": a.get("title"),
                        "html_url": a.get("html_url"),
                        "posted_at": a.get("posted_at"),
                    })

            self.data = {
                "base_url": base_url,
                "school_name": school,
                "course_names_by_id": course_names,
                "grade_urls_by_course": grade_urls,
                "grades_by_course": grades_by_course,
                "assignments_by_course": upcoming_by_course,
                "missing_by_course": missing_by_course,
                "announcements": announcements,
                "courses_total": len(courses),
                "grades_total": len(grades_by_course),
                "options_applied": {
                    "days_ahead": days_ahead,
                    "announcement_days": ann_days,
                    "missing_lookback": miss_look,
                    "update_interval_minutes": int(self.update_interval.total_seconds() // 60) if self.update_interval else None,
                },
            }
            return self.data
        except CanvasApiError as e:
            raise UpdateFailed(str(e)) from e
