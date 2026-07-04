# Shifts (Config)

Configure the station's **shifts** — their **labels** and **start times** — and turn
shift tracking on. This drives the **business day** that analytics count by.

## The rules
- Shifts run **back-to-back over 24 hours**: each shift runs until the **next** shift's
  start; the last shift **wraps past midnight**.
- The **business day rolls over at the earliest shift's start**. So a night shift that
  starts at 22:00 and runs to 06:00 belongs to the **day it started on** — even though
  part of it is after midnight. This is why "1 business day can span 2 calendar days".
- A run is tagged with the shift + business day of its **start time**.

## Set it up
1. Turn **Shifts enabled** on.
2. **Add shift** for each shift; set a **Label** (e.g. Morning) and a **Start** time.
   The "Ends (→)" column shows where each shift stops (the next shift's start); the
   earliest start is the **day boundary**.
3. **Save.**

Example (three 8-hour shifts):
| Label | Start | Ends → |
|---|---|---|
| Morning | 06:00 | 14:00 (boundary) |
| Evening | 14:00 | 22:00 |
| Night | 22:00 | 06:00 (next day) |

## What it changes
- The **Test Bench** shows the **current shift**.
- **Reports** are stamped with the shift + business day when they finish.
- **Analytics** count by **business day** (not calendar date) and gain a **Shift**
  filter + a **Yield by shift** chart.

Stamping is **forward-only** — reports created before you set up shifts keep their
calendar-date grouping; new reports use the business day.
