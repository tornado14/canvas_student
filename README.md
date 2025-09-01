# Canvas (Student) for Home Assistant

![GitHub release (latest SemVer)](https://img.shields.io/github/v/release/tornado14/canvas_student)
![GitHub all releases](https://img.shields.io/github/downloads/tornado14/canvas_student/total)
![Build](https://img.shields.io/github/actions/workflow/status/tornado14/canvas_student/release.yml?branch=main)
![License](https://img.shields.io/github/license/tornado14/canvas_student)
![HACS Custom](https://img.shields.io/badge/HACS-Custom-blue.svg)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-Integration-03A9F4)

Student-focused Canvas integration: courses, grades, upcoming assignments, missing work, announcements, and **GPA per school** (based on per-course **credits** + current grades).

See `examples/cards/` for auto-discovery Markdown cards (Assignments, Missing, Announcements) with local-time formatting and grade links.  
See `custom_components/canvas_student/` for the integration code.

## GPA Setup
In **Configure**:
- Enable **GPA**.
- Optional **GPA scale** (default: US 4.0 with +/-).
- Paste **credits_by_course** JSON (Canvas course_id → credits). Example:
```json
{
  "176": 3,
  "35220": 3,
  "35223": 4
}
```
The **Info** sensor exposes `gpa`, `credits_by_course`, and `grade_points_by_course` for debugging.

MIT © 2025 tornado14
