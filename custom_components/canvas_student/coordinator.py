
from __future__ import annotations
import logging
from datetime import timedelta, datetime, timezone, time
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util
from .const import *
from .simple_client import CanvasClient, CanvasApiError

_LOGGER = logging.getLogger(__name__)

def _letter_from_score(score: float) -> str | None:
    if score is None: return None
    s = float(score)
    if s >= 93: return "A"
    if s >= 90: return "A-"
    if s >= 87: return "B+"
    if s >= 83: return "B"
    if s >= 80: return "B-"
    if s >= 77: return "C+"
    if s >= 73: return "C"
    if s >= 70: return "C-"
    if s >= 67: return "D+"
    if s >= 63: return "D"
    if s >= 60: return "D-"
    return "F"

def _points_from_letter(letter: str | None, scale: str) -> float | None:
    if not letter: return None
    plus_minus = {"A":4.0,"A-":3.7,"B+":3.3,"B":3.0,"B-":2.7,"C+":2.3,"C":2.0,"C-":1.7,"D+":1.3,"D":1.0,"D-":0.7,"F":0.0}
    simple = {"A":4.0,"B":3.0,"C":2.0,"D":1.0,"F":0.0}
    letter = letter.strip().upper()
    if scale == "simple_cutoffs":
        base = letter[0] if letter and letter[0] in "ABCD" else "F"
        return simple.get(base, 0.0)
    return plus_minus.get(letter)

class CanvasCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CanvasClient) -> None:
        upd_mins = int(entry.options.get(OPT_UPDATE_MINUTES, DEFAULT_UPDATE_MINUTES))
        super().__init__(hass, _LOGGER, name=f"Canvas ({entry.data.get('school_name', '')})", update_interval=timedelta(minutes=upd_mins))
        self.hass = hass; self.entry = entry; self.client = client
        self.data = {}

    async def _async_update_data(self):
        try:
            base_url = self.entry.data.get(CONF_BASE_URL)
            school = self.entry.data.get(CONF_SCHOOL_NAME)

            days_ahead  = int(self.entry.options.get(OPT_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))
            ann_days    = int(self.entry.options.get(OPT_ANN_DAYS, DEFAULT_ANNOUNCEMENT_DAYS))
            miss_look   = int(self.entry.options.get(OPT_MISS_LOOKBACK, DEFAULT_MISSING_LOOKBACK))
            enable_gpa  = bool(self.entry.options.get(OPT_ENABLE_GPA, DEFAULT_ENABLE_GPA))
            gpa_scale   = self.entry.options.get(OPT_GPA_SCALE, DEFAULT_GPA_SCALE)
            credits_map = {str(k): float(v) for (k, v) in (self.entry.options.get(OPT_CREDITS_MAP, {}) or {}).items() if v is not None}
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
                        local_dt = datetime.combine(d, time(23, 59, 59), tzinfo=dt_util.DEFAULT_TIME_ZONE)
                        end_dates_map[cid_k] = local_dt.astimezone(timezone.utc).isoformat()
                    except Exception:
                        pass


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
                        grades_by_course[cid] = {"current_score": g.get("current_score"), "current_grade": g.get("current_grade")}
                except Exception:
                    pass

            upcoming_by_course = {}
            for c in courses:
                cid = str(c["id"])
                items = await self.client.list_assignments(cid, bucket="upcoming")
                trimmed = []
                for a in items:
                    due = a.get("due_at")
                    if not due:
                        # Apply per-course end date as effective due date when Canvas has no due date
                        due = end_dates_map.get(cid)
                        if due:
                            a = dict(a)
                            a["due_source"] = "course_end"
                    if due:
                        dt = dt_util.parse_datetime(due)
                        if dt is not None and dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                        if dt and dt <= horizon:
                            trimmed.append({"id": a.get("id"), "name": a.get("name"), "due_at": due, "html_url": a.get("html_url"), "due_source": a.get("due_source")})
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
                    if not due:
                        # Apply per-course end date as effective due date when Canvas has no due date
                        due = end_dates_map.get(cid)
                        if due:
                            a = dict(a)
                            a["due_source"] = "course_end"
                    if due:
                        dt = dt_util.parse_datetime(due)
                        if dt is not None and dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                        if dt and dt < missing_cutoff: continue
                    try:
                        sub = await self.client.get_submission_self(cid, a.get("id"))
                        if sub and sub.get("missing"):
                            miss_list.append({"id": a.get("id"), "name": a.get("name"), "due_at": a.get("due_at"), "html_url": a.get("html_url")})
                    except Exception:
                        pass
                if miss_list:
                    missing_by_course[cid] = miss_list

            undated_outstanding_by_course = {}
            for c in courses:
                cid = str(c["id"])
                assignments = await self.client.list_assignments(cid, bucket=None)

                out_list = []
                for a in assignments:
                    # Only consider assignments with no due date
                    if a.get("due_at"):
                        continue

                    try:
                        sub = await self.client.get_submission_self(cid, a.get("id"))
                    except Exception:
                        sub = None

                    # Your definition: outstanding = no submission.
                    # Canvas often signals submission via submitted_at and/or workflow_state.
                    submitted_at = (sub or {}).get("submitted_at")
                    workflow_state = (sub or {}).get("workflow_state")

                    if submitted_at:
                        continue
                    if workflow_state in ("submitted", "graded"):
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

            context_codes = [f"course_{c['id']}" for c in courses]
            announcements = []
            if context_codes:
                for a in await self.client.get_announcements(context_codes, start_anns, end_anns):
                    cid = a.get("course_id")
                    if not cid:
                        ctx = a.get("context_code") or ""
                        if ctx.startswith("course_"): cid = int(ctx.split("_", 1)[1])
                    announcements.append({"course_id": cid, "title": a.get("title"), "html_url": a.get("html_url"), "posted_at": a.get("posted_at")})

            grade_points_by_course = {}
            if enable_gpa:
                for cid, g in grades_by_course.items():
                    letter = g.get("current_grade"); score = g.get("current_score")
                    if not letter and score is not None: letter = _letter_from_score(score)
                    pts = _points_from_letter(letter, gpa_scale) if letter else None
                    if pts is not None: grade_points_by_course[cid] = pts

            gpa = None; gpa_qp = 0.0; gpa_cr = 0.0
            if enable_gpa and grade_points_by_course:
                for cid, pts in grade_points_by_course.items():
                    cr = float(credits_map.get(cid, 0) or 0)
                    if cr > 0: gpa_qp += pts * cr; gpa_cr += cr
                if gpa_cr > 0: gpa = gpa_qp / gpa_cr

            self.data = {
                "base_url": base_url,
                "school_name": school,
                "course_names_by_id": course_names,
                "grade_urls_by_course": grade_urls,
                "grades_by_course": grades_by_course,
                "assignments_by_course": upcoming_by_course,
                "missing_by_course": missing_by_course,
                "undated_outstanding_by_course": undated_outstanding_by_course,
                "announcements": announcements,
                "courses_total": len(courses),
                "grades_total": len(grades_by_course),
                "credits_by_course": credits_map,
                "grade_points_by_course": grade_points_by_course,
                "gpa": gpa, "gpa_credits": gpa_cr, "gpa_quality_points": gpa_qp,
                "options_applied": {"days_ahead": days_ahead, "announcement_days": ann_days, "missing_lookback": miss_look, "update_interval_minutes": int(self.update_interval.total_seconds() // 60) if self.update_interval else None, "enable_gpa": enable_gpa, "gpa_scale": gpa_scale},
            }
            return self.data
        except CanvasApiError as e:
            raise UpdateFailed(str(e)) from e
