"""Reminders skill — persistent alarms/timers (gap #1 from the JARVIS scan).

Storage: reminders.json in the skill jail. Atomic rewrites.
Due-check is a pure read; the chat app polls it per turn and rings.
"""

import json
import time
import uuid
from pathlib import Path

STORE_NAME = "reminders.json"


def _store_path(ctx) -> Path:
    return Path(ctx.jail_dir) / STORE_NAME


def _load(ctx):
    p = _store_path(ctx)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(ctx, items):
    p = _store_path(ctx)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts))


def handle(tool_name, args, ctx):
    now = time.time()
    if tool_name == "reminder_set":
        item = {
            "id": uuid.uuid4().hex[:8],
            "due": now + int(args["in_minutes"]) * 60,
            "text": args["text"],
        }
        items = _load(ctx)
        items.append(item)
        _save(ctx, items)
        return {"id": item["id"], "due_at": _iso(item["due"])}

    if tool_name == "reminder_list":
        pending = [i for i in _load(ctx) if i["due"] > now]
        return {"reminders": [
            {"id": i["id"], "due_at": _iso(i["due"]), "text": i["text"]}
            for i in sorted(pending, key=lambda x: x["due"])]}

    if tool_name == "reminder_cancel":
        items = _load(ctx)
        kept = [i for i in items if i["id"] != args["id"]]
        if len(kept) == len(items):
            return {"cancelled": False}
        _save(ctx, kept)
        return {"cancelled": True}

    if tool_name == "reminder_due":
        items = _load(ctx)
        due = [i for i in items if i["due"] <= now]
        return {"due": [
            {"id": i["id"], "due_at": _iso(i["due"]), "text": i["text"]}
            for i in sorted(due, key=lambda x: x["due"])]}

    raise ValueError(f"unknown tool {tool_name!r}")


def purge_due(ctx):
    """App-side helper: return due reminders and remove them (ring once)."""
    items = _load(ctx)
    now = time.time()
    due = [i for i in items if i["due"] <= now]
    if due:
        _save(ctx, [i for i in items if i["due"] > now])
    return due
