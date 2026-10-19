"""Code skill — read, write, edit, and sandbox-run Python in a jail.

All paths are relative to the code jail (``<data_dir>/code``); the
SkillContext denies ``..`` escapes and absolute paths before anything runs.
``code_run`` executes in a separate interpreter process with:
  - no shell (argv list, never a command string)
  - 10 s wall-clock timeout
  - network blocked (the socket module is neutered in the child)
  - cwd pinned to the jail
  - stdout/stderr capped at 10 KB combined
It is tier 3, so the gate always asks the owner before it runs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict

SKILL_NAME = "code"

# Sandbox constants
RUN_TIMEOUT_S = 10
OUTPUT_CAP_CHARS = 10_000

# Prepended to every sandboxed run: neuter the network at the socket layer
# (covers socket, urllib, requests, http.client — anything built on it).
_SANDBOX_PREAMBLE = (
    "import socket as _sock_guard;\n"
    "def _no_net(*a, **k):\n"
    "    raise OSError('network disabled in code sandbox')\n"
    "_sock_guard.socket = _no_net\n"
    "_sock_guard.create_connection = _no_net\n"
    "_sock_guard.getaddrinfo = _no_net\n"
    "_sock_guard.gethostbyname = _no_net\n"
    "del _sock_guard, _no_net\n"
)


def _numbered(text: str) -> str:
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(text.splitlines()))


def _backup(ctx, path: str) -> bool:
    """Save the current file content to <path>.bak. Returns False if the
    file did not exist (nothing to back up)."""
    try:
        old = ctx.read_file(path)
    except FileNotFoundError:
        return False
    ctx.write_file(path + ".bak", old)
    return True


def _cap(text: str) -> str:
    if len(text) > OUTPUT_CAP_CHARS:
        return text[:OUTPUT_CAP_CHARS] + "\n…[output truncated at 10KB]"
    return text


def _read(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path = args["path"]
    content = ctx.read_file(path)
    ctx.log(f"read {path!r} ({len(content.splitlines())} lines)")
    return {"path": path, "content": _numbered(content), "lines": len(content.splitlines())}


def _write(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path, content = args["path"], args["content"]
    backed_up = _backup(ctx, path)
    ctx.write_file(path, content)
    ctx.log(f"wrote {path!r} (backup={backed_up})")
    return {"path": path, "written": True, "backed_up": backed_up}


def _edit(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path, old_text, new_text = args["path"], args["old_text"], args["new_text"]
    content = ctx.read_file(path)
    hits = content.count(old_text)
    if hits == 0:
        raise ValueError(f"old_text not found in {path!r} — nothing changed")
    if hits > 1:
        raise ValueError(
            f"old_text matches {hits} times in {path!r} — be more specific "
            "(include surrounding lines so it matches exactly once)"
        )
    _backup(ctx, path)
    ctx.write_file(path, content.replace(old_text, new_text, 1))
    ctx.log(f"edited {path!r}")
    return {"path": path, "edited": True}


def _run(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    code = args.get("code")
    path = args.get("path")
    if (code is None) == (path is None):
        raise ValueError("give exactly one of 'code' (inline source) or 'path' (a .py file in the jail)")
    if path is not None:
        source = ctx.read_file(path)
        label = path
    else:
        source = code
        label = "<inline>"
    ctx.log(f"running {label} (sandbox: 10s, no network, jail cwd)")

    env = {k: v for k, v in os.environ.items()
           if "proxy" not in k.lower()}  # belt-and-braces with the socket guard
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", _SANDBOX_PREAMBLE + source],
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            shell=False,
            cwd=str(ctx.jail_dir),
            env=env,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": _cap(proc.stdout or ""),
            "stderr": _cap(proc.stderr or ""),
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        return {
            "exit_code": -1,
            "stdout": _cap(out),
            "stderr": _cap(err),
            "timed_out": True,
        }


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "code_read":
        return _read(args, ctx)
    if tool_name == "code_write":
        return _write(args, ctx)
    if tool_name == "code_edit":
        return _edit(args, ctx)
    if tool_name == "code_run":
        return _run(args, ctx)
    raise ValueError(f"unknown tool {tool_name!r}")
