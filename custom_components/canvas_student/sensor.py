from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, OPT_HIDE_EMPTY
from .coordinator import CanvasCoordinator


def _base_attrs(entry: ConfigEntry) -> dict[str, Any]:
    return {
        "school_name": entry.data.get("school_name"),
        "student_name": entry.data.get("student_name"),
        "base_url": entry.data.get("base_url"),
        "hide_empty": entry.options.get(OPT_HIDE_EMPTY, False),
    }


class _BaseCanvasSensor(CoordinatorEntity[CanvasCoordinator], SensorEntity):
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
    def native_value(self):
        return (self.coordinator.data or {}).get("courses_total", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


class CanvasGradesSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Grades", "mdi:chart-bar")

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("grades_total", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["grades_by_course"] = d.get("grades_by_course", {})
        out["grade_urls_by_course"] = d.get("grade_urls_by_course", {})
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


class CanvasAssignmentsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Assignments", "mdi:calendar-clock")

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        return sum(len(v) for v in (d.get("assignments_by_course") or {}).values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["assignments_by_course"] = d.get("assignments_by_course", {})
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


class CanvasAnnouncementsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Announcements", "mdi:bullhorn")

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        return len(d.get("announcements") or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["announcements"] = d.get("announcements", [])
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


class CanvasMissingSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Missing", "mdi:alert-circle-outline")

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        missing = d.get("missing_by_course") or {}
        return sum(len(v) for v in missing.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        missing = d.get("missing_by_course", {})
        out["missing_by_course"] = missing
        out["missing_total"] = sum(len(v) for v in missing.values())
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


class CanvasUndatedOutstandingSensor(_BaseCanvasSensor):
    """Single sensor that exposes undated outstanding work per course via attributes."""
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Undated Outstanding (by course)", "mdi:clipboard-text-outline")
        self._attr_unique_id = f"{entry.entry_id}_v2_undated_outstanding_by_course"

    @property
    def native_value(self):
        d = self.coordinator.data or {}
        by_course = d.get("undated_outstanding_by_course", {}) or {}
        return sum(len(v) for v in by_course.values())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)

        course_names = d.get("course_names_by_id", {}) or {}
        by_course = d.get("undated_outstanding_by_course", {}) or {}

        # Keep existing attribute names for backward compatibility with your Lovelace
        details: dict[str, Any] = {}
        counts: dict[str, int] = {}
        for cid, items in by_course.items():
            cname = course_names.get(str(cid), str(cid))
            counts[cname] = len(items)
            details[cname] = items

        out["counts_by_course"] = counts
        out["outstanding_undated_by_course"] = details
        out["course_names_by_id"] = course_names
        return out


class CanvasUngradedCourseSensor(_BaseCanvasSensor):
    """Per-course sensor: submitted-but-ungraded assignments."""

    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry, course_id: str, course_name: str) -> None:
        super().__init__(coordinator, entry, f"Awaiting Grading – {course_name}", "mdi:clipboard-text-clock")
        self._course_id = str(course_id)
        self._course_name = str(course_name)
        self._attr_unique_id = f"{entry.entry_id}_v2_ungraded_{self._course_id}"

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

        ungraded_by_course = d.get("ungraded_by_course") or {}
        out["course_id"] = self._course_id
        out["course_name"] = self._course_name
        out["ungraded_assignments"] = ungraded_by_course.get(self._course_id) or []
        return out


class CanvasInfoSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Info", "mdi:information-outline")

    @property
    def native_value(self):
        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["courses_total"] = d.get("courses_total", 0)
        out["grades_total"] = d.get("grades_total", 0)
        out["grade_urls_by_course"] = d.get("grade_urls_by_course", {})
        out["options_applied"] = d.get("options_applied", {})
        out["credits_by_course"] = d.get("credits_by_course", {})
        out["grade_points_by_course"] = d.get("grade_points_by_course", {})
        out["gpa"] = d.get("gpa")
        out["gpa_credits"] = d.get("gpa_credits", 0.0)
        out["gpa_quality_points"] = d.get("gpa_quality_points", 0.0)
        return out


class CanvasGpaSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "GPA", "mdi:school-outline")

    @property
    def native_value(self):
        g = (self.coordinator.data or {}).get("gpa")
        try:
            return round(float(g), 3) if g is not None else None
        except Exception:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["gpa"] = d.get("gpa")
        out["gpa_credits"] = d.get("gpa_credits", 0.0)
        out["gpa_quality_points"] = d.get("gpa_quality_points", 0.0)
        out["grade_points_by_course"] = d.get("grade_points_by_course", {})
        out["credits_by_course"] = d.get("credits_by_course", {})
        out["course_names_by_id"] = d.get("course_names_by_id", {})
        return out


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord: CanvasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    # Base sensors
    ents: list[SensorEntity] = [
        CanvasCoursesSensor(coord, entry),
        CanvasGradesSensor(coord, entry),
        CanvasAssignmentsSensor(coord, entry),
        CanvasAnnouncementsSensor(coord, entry),
        CanvasMissingSensor(coord, entry),
        CanvasUndatedOutstandingSensor(coord, entry),
        CanvasInfoSensor(coord, entry),
        CanvasGpaSensor(coord, entry),
    ]

    # Per-course Awaiting Grading sensors
    d = coord.data or {}
    course_names = d.get("course_names_by_id") or {}
    for cid, cname in course_names.items():
        ents.append(CanvasUngradedCourseSensor(coord, entry, str(cid), str(cname)))

    async_add_entities(ents)
