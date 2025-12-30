
from __future__ import annotations
from typing import Any
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN, OPT_HIDE_EMPTY
from .coordinator import CanvasCoordinator

def _base_attrs(entry: ConfigEntry) -> dict[str, Any]:
    return {"school_name": entry.data.get("school_name"), "student_name": entry.data.get("student_name"), "base_url": entry.data.get("base_url"), "hide_empty": entry.options.get(OPT_HIDE_EMPTY, False)}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord: CanvasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    ents = [
        CanvasCoursesSensor(coord, entry),
        CanvasGradesSensor(coord, entry),
        CanvasAssignmentsSensor(coord, entry),
        CanvasAnnouncementsSensor(coord, entry),
        CanvasMissingSensor(coord, entry),
        CanvasUndatedOutstandingSensor(coord, entry),
        CanvasInfoSensor(coord, entry),
        CanvasGpaSensor(coord, entry),
    ]

    # Create one Awaiting Grading sensor per course
    d = coord.data or {}
    course_names = d.get("course_names_by_id") or {}
    for cid, cname in course_names.items():
        ents.append(CanvasAwaitingGradingByCourseSensor(coord, entry, str(cid), str(cname)))

    async_add_entities(ents)

class CanvasAwaitingGradingByCourseSensor(_BaseCanvasSensor):
    """One sensor per course. State = count of awaiting grading assignments."""
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry, course_id: str, course_name: str) -> None:
        super().__init__(coordinator, entry, f"Awaiting Grading – {course_name}", "mdi:clipboard-text-clock")
        self._course_id = str(course_id)
        self._course_name = course_name
        self._attr_unique_id = f"{entry.entry_id}_awaiting_grading_{self._course_id}"

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        ungraded_by_course = d.get("ungraded_by_course") or {}
        items = ungraded_by_course.get(self._course_id) or []
        return len(items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["course_id"] = self._course_id
        out["course_name"] = self._course_name

        ungraded_by_course = d.get("ungraded_by_course") or {}
        out["ungraded_assignments"] = ungraded_by_course.get(self._course_id) or []
        return out

class CanvasUndatedOutstandingSensor(SensorEntity):
    _attr_icon = "mdi:clipboard-text-outline"

    def __init__(self, coordinator, entry):
        self.coordinator = coordinator
        self.entry = entry

        # "Per course" but this is a single sensor that exposes counts per course
        # via attributes. If you truly want ONE ENTITY PER COURSE, tell me and
        # we’ll generate entities dynamically from course IDs instead.
        self._attr_name = "Canvas Undated Outstanding (by course)"
        self._attr_unique_id = f"{entry.entry_id}_undated_outstanding_by_course"

    @property
    def native_value(self):
        data = self.coordinator.data or {}
        by_course = data.get("undated_outstanding_by_course", {})
        # total across all courses; still “per course” details are in attributes
        return sum(len(v) for v in by_course.values())

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        course_names = data.get("course_names_by_id", {})
        by_course = data.get("undated_outstanding_by_course", {})

        # Attributes: per-course list + per-course count
        details = {}
        counts = {}
        for cid, items in by_course.items():
            cname = course_names.get(str(cid), str(cid))
            counts[cname] = len(items)
            details[cname] = items

        return {
            "counts_by_course": counts,
            "outstanding_undated_by_course": details,
        }

    async def async_added_to_hass(self):
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self):
        self.coordinator.async_remove_listener(self.async_write_ha_state)
        
class _BaseCanvasSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry, name_suffix: str, icon: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = f"Canvas ({entry.data.get('school_name')} - {entry.data.get('student_name') or 'Student'}) {name_suffix}"
        self._attr_unique_id = f"{entry.entry_id}_v2_{name_suffix.lower().replace(' ', '_')}"
        self._attr_icon = icon

class CanvasCoursesSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Courses", "mdi:book-multiple")
    @property
    def native_value(self): return (self.coordinator.data or {}).get("courses_total", 0)
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry); out["course_names_by_id"] = d.get("course_names_by_id", {}); return out

class CanvasGradesSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Grades", "mdi:chart-bar")
    @property
    def native_value(self): return (self.coordinator.data or {}).get("grades_total", 0)
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry); out["grades_by_course"] = d.get("grades_by_course", {}); out["grade_urls_by_course"] = d.get("grade_urls_by_course", {}); out["course_names_by_id"] = d.get("course_names_by_id", {}); return out

class CanvasAssignmentsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Assignments", "mdi:calendar-clock")
    @property
    def native_value(self):
        d = self.coordinator.data or {}; return sum(len(v) for v in (d.get("assignments_by_course") or {}).values())
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry); out["assignments_by_course"] = d.get("assignments_by_course", {}); out["course_names_by_id"] = d.get("course_names_by_id", {}); return out

class CanvasAnnouncementsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Announcements", "mdi:bullhorn")
    @property
    def native_value(self):
        d = self.coordinator.data or {}; return len(d.get("announcements") or [])
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry); out["announcements"] = d.get("announcements", []); out["course_names_by_id"] = d.get("course_names_by_id", {}); return out

class CanvasMissingSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Missing", "mdi:alert-circle-outline")
    @property
    def native_value(self):
        d = self.coordinator.data or {}; missing = d.get("missing_by_course") or {}; return sum(len(v) for v in missing.values())
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry); missing = d.get("missing_by_course", {}); out["missing_by_course"] = missing; out["missing_total"] = sum(len(v) for v in missing.values()); out["course_names_by_id"] = d.get("course_names_by_id", {}); return out

class CanvasUngradedCourseSensor(_BaseCanvasSensor):
    """Per-course sensor: submitted-but-ungraded assignments."""

    def __init__(
        self,
        coordinator: CanvasCoordinator,
        entry: ConfigEntry,
        course_id: str,
        course_name: str,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            f"Awaiting Grading – {course_name}",
            "mdi:clipboard-text-clock",
        )
        self._course_id = course_id
        self._attr_unique_id = f"{entry.entry_id}_v2_ungraded_{course_id}"
    @property
    def native_value(self):
        """Number of ungraded submissions for this course."""
        d = self.coordinator.data or {}
        ungraded_by_course = d.get("ungraded_by_course") or {}
        items = ungraded_by_course.get(self._course_id) or []
        return len(items)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """
        Attributes include the detailed ungraded list.

        ungraded_assignments = [
          {
            "id": ...,
            "name": ...,
            "submitted_at": ...,
            "due_at": ...,
            "html_url": ...,
          },
          ...
        ]
        """
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        course_names = d.get("course_names_by_id") or {}
        ungraded_by_course = d.get("ungraded_by_course") or {}

        out["course_id"] = self._course_id
        out["course_name"] = course_names.get(self._course_id, self._course_id)
        out["ungraded_assignments"] = ungraded_by_course.get(self._course_id) or []
        return out

class CanvasInfoSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Info", "mdi:information-outline")
    @property
    def native_value(self): return "ok"
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry)
        out["courses_total"] = d.get("courses_total", 0); out["grades_total"] = d.get("grades_total", 0)
        out["grade_urls_by_course"] = d.get("grade_urls_by_course", {}); out["options_applied"] = d.get("options_applied", {})
        out["credits_by_course"] = d.get("credits_by_course", {}); out["grade_points_by_course"] = d.get("grade_points_by_course", {})
        out["gpa"] = d.get("gpa"); out["gpa_credits"] = d.get("gpa_credits", 0.0); out["gpa_quality_points"] = d.get("gpa_quality_points", 0.0)
        return out

class CanvasGpaSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "GPA", "mdi:school-outline")
    @property
    def native_value(self):
        g = (self.coordinator.data or {}).get("gpa")
        try: return round(float(g), 3) if g is not None else None
        except Exception: return None
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}; out = _base_attrs(self._entry)
        out["gpa"] = d.get("gpa"); out["gpa_credits"] = d.get("gpa_credits", 0.0); out["gpa_quality_points"] = d.get("gpa_quality_points", 0.0)
        out["grade_points_by_course"] = d.get("grade_points_by_course", {}); out["credits_by_course"] = d.get("credits_by_course", {}); out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out
