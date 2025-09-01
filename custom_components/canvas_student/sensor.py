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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coord: CanvasCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    entities = [
        CanvasCoursesSensor(coord, entry),
        CanvasGradesSensor(coord, entry),
        CanvasAssignmentsSensor(coord, entry),
        CanvasAnnouncementsSensor(coord, entry),
        CanvasMissingSensor(coord, entry),
        CanvasInfoSensor(coord, entry),
        CanvasGpaSensor(coord, entry),
    ]
    async_add_entities(entities)

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
    def native_value(self):
        return (self.coordinator.data or {}).get("courses_total", 0)
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out

class CanvasGradesSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Grades", "mdi:chart-bar")
    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("grades_total", 0)
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["grades_by_course"] = data.get("grades_by_course", {})
        out["grade_urls_by_course"] = data.get("grade_urls_by_course", {})
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out

class CanvasAssignmentsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Assignments", "mdi:calendar-clock")
    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return sum(len(v) for v in (data.get("assignments_by_course") or {}).values())
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["assignments_by_course"] = data.get("assignments_by_course", {})
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out

class CanvasAnnouncementsSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Announcements", "mdi:bullhorn")
    @property
    def native_value(self):
        data = self.coordinator.data or {}
        return len(data.get("announcements") or [])
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["announcements"] = data.get("announcements", [])
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out

class CanvasMissingSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Missing", "mdi:alert-circle-outline")
    @property
    def native_value(self):
        data = self.coordinator.data or {}
        missing = data.get("missing_by_course") or {}
        return sum(len(v) for v in missing.values())
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        missing = data.get("missing_by_course", {})
        out["missing_by_course"] = missing
        out["missing_total"] = sum(len(v) for v in missing.values())
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out

class CanvasInfoSensor(_BaseCanvasSensor):
    def __init__(self, coordinator: CanvasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "Info", "mdi:information-outline")
    @property
    def native_value(self):
        return "ok"
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["courses_total"] = data.get("courses_total", 0)
        out["grades_total"] = data.get("grades_total", 0)
        out["grade_urls_by_course"] = data.get("grade_urls_by_course", {})
        out["options_applied"] = data.get("options_applied", {})
        out["credits_by_course"] = data.get("credits_by_course", {})
        out["grade_points_by_course"] = data.get("grade_points_by_course", {})
        out["gpa"] = data.get("gpa")
        out["gpa_credits"] = data.get("gpa_credits", 0.0)
        out["gpa_quality_points"] = data.get("gpa_quality_points", 0.0)
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
        data = self.coordinator.data or {}
        out = _base_attrs(self._entry)
        out["gpa"] = data.get("gpa")
        out["gpa_credits"] = data.get("gpa_credits", 0.0)
        out["gpa_quality_points"] = data.get("gpa_quality_points", 0.0)
        out["grade_points_by_course"] = data.get("grade_points_by_course", {})
        out["credits_by_course"] = data.get("credits_by_course", {})
        out["course_names_by_id"] = data.get("course_names_by_id", {})
        return out
