from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, time as dtime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BASE_URL,
    DEFAULT_ANNOUNCEMENT_DAYS,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_ENABLE_GPA,
    DEFAULT_GPA_SCALE,
    DEFAULT_HIDE_EMPTY,
    DEFAULT_MISSING_LOOKBACK,
    DEFAULT_UPDATE_MINUTES,
    DOMAIN,
    OPT_ANN_DAYS,
    OPT_COURSE_END_DATES_MAP,
    OPT_CREDITS_MAP,
    OPT_DAYS_AHEAD,
    OPT_ENABLE_GPA,
    OPT_GPA_SCALE,
    OPT_HIDE_COURSES,
    OPT_HIDE_EMPTY,
    OPT_MISS_LOOKBACK,
    OPT_UPDATE_MINUTES,
)
from .simple_client import CanvasClient

_LOGGER = logging.getLogger(__name__)


def _letter_from_score(score: float) -> str:
    # Simple default; you can tweak if you want +/- mapping later.
    if score >= 93:
        return "A"
    if score >= 90:
        return "A-"
    if score >= 87:
        return "B+"
    if score >= 83:
        return "B"
    if score >= 80:
        return "B-"
    if score >= 77:
        return "C+"
    if score >= 73:
        return "C"
    if score >= 70:
        return "C-"
    if score >= 67:
        return "D+"
    if score >= 63:
        return "D"
    if score >= 60:
        return "D-"
    return "F"


def _grade_points(letter: str) -> float | None:
    if not letter:
        return None
    l = letter.strip().upper()
    table = {
        "A+": 4.0, "A": 4.0, "A-": 3.7,
        "B+": 3.3, "B": 3.0, "B-": 2.7,
        "C+": 2.3, "C": 2.0, "C-": 1.7,
        "D+": 1.3, "D": 1.0, "D-": 0.7,
        "F": 0.0,
    }
    return table.get(l)


class CanvasCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CanvasClient) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client

        update_minutes = int(entry.options.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))
        super().__init__(
            hass,
            _LOGGER,
            name=f"Canvas ({entry.data.get('school_name', 'School')})",
            update_interval=timedelta(minutes=update_minutes),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            base_url = str(self.entry.data.get(CONF_BASE_URL, "")).rstrip("/")

            hide_empty = bool(self.entry.options.get(OPT_HIDE_EMPTY, DEFAULT_HIDE_EMPTY))
            days_ahead = int(self.entry.options.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
            ann_days = int(self.entry.options.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
            miss_lookback_days = int(self.entry.options.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))
            now = datetime.now(timezone.utc)
            horizon = now + timedelta(days=days_ahead)

            enable_gpa = bool(self.entry.options.get(OPT_ENABLE_GPA, DEFAULT_ENABLE_GPA))
            gpa_scale_raw = self.entry.options.get(OPT_GPA_SCALE, DEFAULT_GPA_SCALE)

            # Accept numeric scale (e.g., 4.0) or a preset string (e.g., "us_4_0_plusminus")
            if isinstance(gpa_scale_raw, (int, float)):
                gpa_scale = float(gpa_scale_raw)
            elif isinstance(gpa_scale_raw, str):
                s = gpa_scale_raw.strip().lower()
                if s in ("us_4_0", "us_4_0_plusminus", "4", "4.0", "4.00"):
                    gpa_scale = 4.0
                else:
                    # Unknown preset -> default safely
                    gpa_scale = float(DEFAULT_GPA_SCALE)
            else:
                gpa_scale = float(DEFAULT_GPA_SCALE)

            # credits map: { "course_id": credits_float }
            credits_raw = (self.entry.options.get(OPT_CREDITS_MAP, {}) or {})
            credits_map: dict[str, float] = {}
            if isinstance(credits_raw, dict):
                for k, v in credits_raw.items():
                    try:
                        if v is None:
                            continue
                        credits_map[str(k)] = float(v)
                    except Exception:
                        continue

            # hide courses list: ["17100","35804"] or [17100,35804]
            hide_courses_raw = (self.entry.options.get(OPT_HIDE_COURSES, []) or [])
            hide_courses: set[str] = set()
            if isinstance(hide_courses_raw, list):
                hide_courses = {str(x) for x in hide_courses_raw if str(x).strip()}

            # end dates map: { "176": "2026-02-14" }
            end_dates_raw = (self.entry.options.get(OPT_COURSE_END_DATES_MAP, {}) or {})
            end_dates_map: dict[str, str] = {}
            if isinstance(end_dates_raw, dict):
                for k, v in end_dates_raw.items():
                    cid_k = str(k)
                    ds = str(v).strip()
                    if not ds:
                        continue
                    try:
                        d = datetime.strptime(ds, "%Y-%m-%d").date()
                        local_dt = datetime.combine(d, dtime(23, 59, 59), tzinfo=dt_util.DEFAULT_TIME_ZONE)
                        end_dates_map[cid_k] = local_dt.astimezone(timezone.utc).isoformat()
                    except Exception:
                        # Ignore bad values quietly
                        continue

            now = datetime.now(timezone.utc)
            horizon = now + timedelta(days=days_ahead)
            miss_floor = now - timedelta(days=miss_lookback_days)

            # --- Courses ---
            courses = await self.client.list_courses()
            if not isinstance(courses, list):
                courses = []

            # Apply hide-courses filtering
            if hide_courses:
                courses = [c for c in courses if str(c.get("id")) not in hide_courses]

            course_names_by_id = {
                str(c.get("id")): (c.get("name") or c.get("course_code") or str(c.get("id")))
                for c in courses
                if c.get("id") is not None
            }
            grade_urls_by_course = {
                str(c.get("id")): f"{base_url}/courses/{c.get('id')}/grades"
                for c in courses
                if c.get("id") is not None and base_url
            }

            # --- Grades ---
            grades_by_course: dict[str, dict[str, Any]] = {}
            for c in courses:
                cid = str(c.get("id"))
                if not cid or cid == "None":
                    continue
                try:
                    enr = await self.client.list_enrollments(cid)
                    e = next(
                        (e for e in (enr or []) if e.get("type") == "StudentEnrollment" or "grades" in e),
                        None,
                    )
                    if e and e.get("grades"):
                        g = e["grades"]
                        grades_by_course[cid] = {
                            "current_score": g.get("current_score"),
                            "current_grade": g.get("current_grade"),
                        }
                except Exception:
                    # Don't let a single course break the whole update
                    continue

            # --- Upcoming Assignments (with fallback) ---
            assignments_by_course: dict[str, list[dict[str, Any]]] = {}

            for c in courses:
                cid = str(c.get("id"))
                if not cid or cid == "None":
                    continue

                # 1) Try Canvas "upcoming" bucket
                used_upcoming_bucket = True
                try:
                    items = await self.client.list_assignments(cid, bucket="upcoming")
                except Exception:
                    items = []
                if not isinstance(items, list):
                    items = []

                # 2) If empty, fall back to all assignments and filter ourselves
                if not items:
                    used_upcoming_bucket = False
                    try:
                        items = await self.client.list_assignments(cid, bucket=None)
                    except Exception:
                        items = []
                    if not isinstance(items, list):
                        items = []

                _LOGGER.warning("Canvas %s %s using upcoming=%s got %d items",
                    self.entry.data.get("school_name"),
                    cid,
                    used_upcoming_bucket,
                    len(items),
                )


                trimmed: list[dict[str, Any]] = []

                for a in items:
                    due = a.get("due_at")
                    due_source = a.get("due_source")

                    # If no due date, apply per-course end date
                    if not due:
                        eff = end_dates_map.get(cid)
                        if eff:
                            due = eff
                            due_source = "course_end"

                    if not due:
                        # Option B: include undated items ONLY when they came from the upcoming bucket.
                        # If we had to fall back to "all", including undated floods the list.
                        if used_upcoming_bucket:
                            trimmed.append(
                                {
                                    "id": a.get("id"),
                                    "name": a.get("name"),
                                    "due_at": None,
                                    "html_url": a.get("html_url"),
                                }
                            )
                        continue

                    dt = dt_util.parse_datetime(due)
                    if dt is not None and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    if dt and now <= dt <= horizon:
                        trimmed.append(
                            {
                                "id": a.get("id"),
                                "name": a.get("name"),
                                "due_at": due,
                                "html_url": a.get("html_url"),
                                "due_source": due_source,
                            }
                        )


                # Optional: hide-empty at course-level? (we keep empty lists and let UI decide)
                assignments_by_course[cid] = trimmed

            # --- Missing Assignments ---
            # Definition here: due date exists and is in [miss_floor, now], and user has no submission.
            # (This can be expensive if Canvas requires per-assignment submission calls; we keep it guarded.)
            missing_by_course: dict[str, list[dict[str, Any]]] = {}

            for c in courses:
                cid = str(c.get("id"))
                if not cid or cid == "None":
                    continue

                try:
                    all_assignments = await self.client.list_assignments(cid, bucket=None)
                except Exception:
                    all_assignments = []
                if not isinstance(all_assignments, list):
                    all_assignments = []

                miss_list: list[dict[str, Any]] = []

                for a in all_assignments:
                    due = a.get("due_at")
                    due_source = a.get("due_source")

                    if not due:
                        eff = end_dates_map.get(cid)
                        if eff:
                            due = eff
                            due_source = "course_end"

                    if not due:
                        continue

                    dt = dt_util.parse_datetime(due)
                    if dt is not None and dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    # Only within lookback window and already due
                    if not dt or dt < miss_floor or dt > now:
                        continue

                    # Check submission state
                    sub = None
                    try:
                        sub = await self.client.get_submission_self(cid, a.get("id"))
                    except Exception:
                        sub = None

                    submitted_at = (sub or {}).get("submitted_at")
                    workflow_state = (sub or {}).get("workflow_state")

                    if submitted_at or workflow_state in ("submitted", "graded"):
                        continue

                    miss_list.append(
                        {
                            "id": a.get("id"),
                            "name": a.get("name"),
                            "due_at": due,
                            "html_url": a.get("html_url"),
                            "due_source": due_source,
                        }
                    )

                if miss_list:
                    missing_by_course[cid] = miss_list

            # --- Awaiting Grading (submitted but ungraded) ---
            ungraded_by_course: dict[str, list[dict[str, Any]]] = {}

            for c in courses:
                cid = str(c.get("id"))
                if not cid or cid == "None":
                    continue
                try:
                    submissions = await self.client.list_submissions_self(cid, workflow_state="submitted")
                except Exception:
                    continue
                if not isinstance(submissions, list):
                    continue

                items: list[dict[str, Any]] = []
                for sub in submissions:
                    # Already graded?
                    if sub.get("graded_at") or sub.get("grade") is not None or sub.get("score") is not None:
                        continue

                    assignment = sub.get("assignment") or {}
                    items.append(
                        {
                            "id": sub.get("assignment_id"),
                            "name": assignment.get("name"),
                            "submitted_at": sub.get("submitted_at"),
                            "due_at": assignment.get("due_at"),
                            "html_url": assignment.get("html_url"),
                        }
                    )

                if items:
                    ungraded_by_course[cid] = items

            # --- Undated outstanding by course (no due date, not submitted) ---
            # NOTE: this can be expensive; keep it lightweight and guarded.
            undated_outstanding_by_course: dict[str, list[dict[str, Any]]] = {}

            for c in courses:
                cid = str(c.get("id"))
                if not cid or cid == "None":
                    continue

                try:
                    all_assignments = await self.client.list_assignments(cid, bucket=None)
                except Exception:
                    continue
                if not isinstance(all_assignments, list):
                    continue

                out_list: list[dict[str, Any]] = []

                for a in all_assignments:
                    # Only truly undated (no due_at) AND no course_end override in this view
                    if a.get("due_at"):
                        continue

                    # If you set a course_end_date, those become "dated" for planning purposes
                    if end_dates_map.get(cid):
                        continue

                    sub = None
                    try:
                        sub = await self.client.get_submission_self(cid, a.get("id"))
                    except Exception:
                        sub = None

                    submitted_at = (sub or {}).get("submitted_at")
                    workflow_state = (sub or {}).get("workflow_state")

                    if submitted_at or workflow_state in ("submitted", "graded"):
                        continue

                    out_list.append(
                        {
                            "id": a.get("id"),
                            "name": a.get("name"),
                            "due_at": None,
                            "html_url": a.get("html_url"),
                        }
                    )

                if out_list:
                    undated_outstanding_by_course[cid] = out_list

            # --- Announcements ---
            announcements: list[dict[str, Any]] = []
            start_anns = (dt_util.now() - timedelta(days=ann_days)).astimezone(timezone.utc)
            end_anns = dt_util.now().astimezone(timezone.utc)

            context_codes = [f"course_{c.get('id')}" for c in courses if c.get("id") is not None]
            if context_codes:
                try:
                    for a in await self.client.get_announcements(context_codes, start_anns, end_anns):
                        cid = a.get("course_id")
                        if not cid:
                            ctx = a.get("context_code") or ""
                            if ctx.startswith("course_"):
                                try:
                                    cid = int(ctx.split("_", 1)[1])
                                except Exception:
                                    cid = None
                        announcements.append(
                            {
                                "course_id": cid,
                                "title": a.get("title"),
                                "html_url": a.get("html_url"),
                                "posted_at": a.get("posted_at"),
                            }
                        )
                except Exception:
                    pass

            # --- GPA ---
            grade_points_by_course: dict[str, float] = {}
            credits_by_course: dict[str, float] = {}
            gpa = None
            gpa_credits = 0.0
            gpa_quality_points = 0.0

            if enable_gpa:
                for cid, g in grades_by_course.items():
                    score = g.get("current_score")
                    letter = g.get("current_grade")

                    if not letter and score is not None:
                        try:
                            letter = _letter_from_score(float(score))
                        except Exception:
                            letter = None

                    gp = _grade_points(letter or "")
                    cr = credits_map.get(cid)

                    if gp is None or cr is None:
                        continue

                    grade_points_by_course[cid] = gp
                    credits_by_course[cid] = cr
                    gpa_credits += cr
                    gpa_quality_points += (gp * cr)

                if gpa_credits > 0:
                    raw = gpa_quality_points / gpa_credits
                    # If someone uses a different scale, allow scaling (default 4.0)
                    if gpa_scale and gpa_scale != 4.0:
                        raw = raw * (gpa_scale / 4.0)
                    gpa = raw

            options_applied = {
                "hide_empty": hide_empty,
                "days_ahead": days_ahead,
                "announcement_days": ann_days,
                "missing_lookback_days": miss_lookback_days,
                "enable_gpa": enable_gpa,
                "gpa_scale": gpa_scale,
                "hidden_courses_count": len(hide_courses),
                "end_dates_count": len(end_dates_map),
                "credits_count": len(credits_map),
            }

            return {
                "course_names_by_id": course_names_by_id,
                "grade_urls_by_course": grade_urls_by_course,
                "grades_by_course": grades_by_course,
                "assignments_by_course": assignments_by_course,
                "missing_by_course": missing_by_course,
                "ungraded_by_course": ungraded_by_course,
                "undated_outstanding_by_course": undated_outstanding_by_course,
                "announcements": announcements,
                "credits_by_course": credits_by_course,
                "grade_points_by_course": grade_points_by_course,
                "gpa": gpa,
                "gpa_credits": gpa_credits,
                "gpa_quality_points": gpa_quality_points,
                "options_applied": options_applied,
                "courses_total": len(courses),
                "grades_total": len(grades_by_course),
            }

        except Exception as err:
            raise UpdateFailed(f"Canvas update failed: {err}") from err
