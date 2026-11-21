---
name: weekend-reminders
description: Preview post-weekend events and unfinished tasks, or prepare a first-workday reminder. Use for Friday previews and first-workday check-ins.
---

# Weekend reminders

Use the local date and time zone, or the user's supplied date and time zone. Read `SCHEMA.md` and `index.md`, then check relevant dated events, appointments, scheduled tasks, and unfinished canonical tasks in the wiki and their sources. Consult a connected calendar only if it is available and authorized; do not assume the knowledge base contains every meeting. State which sources were checked and flag unavailable calendars or uncertain dates rather than inventing events.

The user can configure their workdays, holidays, time zone, and calendar in their own scheduling prompt. Do not infer public holidays or a long weekend from location alone. If the holiday schedule is unknown, say so and include Monday and Tuesday rather than assuming Monday is a workday.

## Friday preview

When asked for the Friday preview, check events on the coming Monday and Tuesday, including morning appointments. Also check the first workday after the weekend and its following day if a known holiday makes those dates later. Include unfinished tasks that need attention before those events. Show the most urgent items first and give one primary next action that can be taken today. If no events are found, say none were found in the sources checked, not that the calendar is clear.

## First-workday reminder

When asked for the first-workday reminder, check whether today is the first configured workday after the weekend, including any known consecutive holidays or days off. On that day, highlight today's and the next day on the calendar's events, especially morning appointments, and relevant unfinished tasks. Give one primary next action. On other days, do not produce a reminder. If the workday or holiday schedule is unknown, say that the first workday cannot be confirmed and offer the check-in without asserting it is scheduled.

## Delivery and deferral

Keep the message concise: a short heading, at most three important items with dates and times when known, and one primary next action. Indicate if more items exist. Make "snooze" or "defer" easy: accept the user's chosen time or next check-in, and use an available authorized scheduling mechanism only when it confirms the change. Otherwise provide a copyable reminder and say that no automatic snooze was set. Do not edit events or task status merely to defer a reminder.

Treat each preview or morning check-in as a separate occurrence identified by its type, local date, and time zone. Deduplicate the same event or canonical task across sources. When the host has reliable delivery state, suppress automatic reruns already confirmed delivered for that occurrence; never suppress an explicit user-requested check-in. If delivery state is unknown, say so and allow a retry rather than claiming delivery or silently dropping it. A retry may produce a duplicate when the host cannot verify delivery.

Do not claim a reminder was delivered, queued, scheduled, or snoozed without confirmation from the host. A prompt alone is not an automation; if the host cannot run while inactive, a missed 8 AM reminder must be retried or queued for the next login using a supported mechanism, or requested manually.
