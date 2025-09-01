# Canvas (Student) for Home Assistant

Student-focused Canvas integration: courses, grades, upcoming assignments, missing work, announcements, and **GPA per school** (credits-weighted).

See `examples/cards/` for Markdown cards (Assignments, Missing, Announcements).

---

## How to set GPA

> GPA is optional. If enabled, it is computed per school as a credits-weighted average.

### 1) Enable GPA in options
Settings → Devices & Services → **Canvas (Student)** → *Configure*  
- Enable **GPA**  
- Choose **GPA scale** (default US 4.0 +/-)

### 2) Provide course credits
Create JSON mapping **Canvas course ID → credits**. You can use:
`examples/credits_by_course.template.json`

Example:
```json
{
  "176": 3,
  "35220": 3,
  "35223": 4,
  "33932": 3.0
}
```

Paste into **Credits mapping (JSON)** and Save.

### 3) How GPA is calculated
GPA = sum(grade_points × credits) / sum(credits).  
Letter → points (default): A 4.0, A- 3.7, B+ 3.3, B 3.0, B- 2.7, C+ 2.3, C 2.0, C- 1.7, D+ 1.3, D 1.0, D- 0.7, F 0.0.  
If only a numeric score exists, we infer a letter by cutoffs (93 A, 90 A-, 87 B+, …).

### 4) Where GPA appears
- Info sensor attributes: `gpa`, `credits_by_course`, `grade_points_by_course`, etc.
- Optional **GPA** sensor numeric state
- Assignments card header shows **GPA per school** when available.

MIT © 2025 tornado14
