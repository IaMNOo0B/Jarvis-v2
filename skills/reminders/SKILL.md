# Reminders Skill

Set, list, and cancel reminders. Reminders persist across restarts (JSON in
the skill's jail dir). The chat app checks due reminders at the start of
every turn and rings them (call-ringing model: visual + soft tone).

Rules:
- Time is relative: `in_minutes` (e.g. 30 = "in half an hour").
- Keep reminder text short and clear.
- Never invent a due time — if the user says "tomorrow morning," ask which hour.
- `reminder_due` is for the app's own polling; the brain normally doesn't call it.
