## 0.6.25
- Added diagnostics.py for in UI diagnostics collection

## 0.6.24
- Fix upcoming filter: exclude past-due items

## 0.6.23
- Fix syntax/logic around upcoming assignment filtering and Option B undated handling.

## 0.6.22
- Add course hide-list option (multi-select) to filter out non-course “courses” across sensors and Lovelace output.
- Improve independent study handling by supporting per-course end dates for undated assignments (effective due date) and labeling with `due_source`.
- Internal cleanup: apply course filtering consistently in coordinator + per-course sensors.

## v0.6.21

- Fixed: restore Awaiting Grading per-course entities

- Fixed: sensor module load errors from class order/duplication

## v0.6.20

- Restored awaiting grading logic in sensor.py

## v0.6.19

- Fixed: Awaiting Grading sensor not populating after merge
- Fixed: Undated outstanding not shown in assignments list

## v0.6.18

- Fixed: Awaiting Grading sensor unavailable in 0.6.17

## v0.6.17

### Added
- Support for per-course end dates for assignments without due dates.
- Undated assignments now use the configured course end date as an effective due date.

### Notes
- This is especially useful for independent study courses that do not define assignment due dates.
- No new sensors or Lovelace changes are required.

## 0.6.15
- Added canvas_ungraded_<course_id> sensor to show submitted but ungraded assignments

## 0.6.13
- Bundle full working Markdown cards in `examples/cards/`
