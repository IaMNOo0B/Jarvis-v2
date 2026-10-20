"""Code skill — read, write, edit, verify, map, and sandbox-run Python in a jail.

All paths are relative to the code jail (``<data_dir>/code``); the
SkillContext denies ``..`` escapes and absolute paths before anything runs.

Tools:
  - ``code_read``  (tier 1) whole-file read with line numbers; records a
    freshness stamp (mtime, size, sha256) for the edit gate.
  - ``code_write`` (tier 2) whole-file write with ``.bak`` undo.
  - ``code_edit``  (tier 2) surgical edit through a 4-rung match ladder
    (exact -> whitespace-normalized -> Unicode-fold -> structural);
    location matching only — replacement text is always applied verbatim.
  - ``code_verify`` (tier 1) differential test verification: snapshot a
    baseline, edit, re-run, get a FULL / PARTIAL / NO verdict computed
    from test outcomes only.
  - ``code_map``   (tier 1) AST def/ref map of the jail's Python files,
    PageRank-ranked, sqlite-cached.
  - ``code_run``   (tier 3) sandboxed execution, see below.

``code_run`` executes in a separate interpreter process with:
  - no shell (argv list, never a command string)
  - 10 s wall-clock timeout; the WHOLE process tree is killed on timeout
  - a child environment built from an ALLOWLIST (PATH, SYSTEMROOT,
    TEMP/TMP, LANG/LC_*, PYTHONIOENCODING; temp dirs re-pinned into the
    jail) — parent secrets cannot leak because they are never copied
  - network neutered at the socket layer, spawns blocked, and an audit
    hook that refuses ``open()`` outside the jail / interpreter tree
  - cwd pinned to the jail
  - stdout+stderr capped at 10 KB COMBINED

Honesty box (defense-in-depth, not a proof): the audit hook and the
monkeypatched neuters are best-effort stdlib fences. Determined code can
still escape them (ctypes, direct syscalls, ``import _socket`` reloads,
interpreter bugs) — the real boundary is the tier-3 owner approval in
the gate, plus the fact that the owner only runs code they have seen.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

SKILL_NAME = "code"

# Sandbox constants
RUN_TIMEOUT_S = 10
VERIFY_TIMEOUT_S = 120
OUTPUT_CAP_CHARS = 10_000

# Skill state files (inside the jail, next to the owner's code)
_STATE_FILE = ".code_state.json"      # read/write freshness stamps (P3)
_VERIFY_FILE = ".code_verify.json"    # code_verify baselines (P2)
_MAP_DB = ".code_map.db"              # code_map sqlite cache (P4)

# ---------------------------------------------------------------------------
# P1 — sandbox hardening: env allowlist, audit-hook preamble, tree kill
# ---------------------------------------------------------------------------

# The child gets ONLY these variables from the parent environment. Anything
# not listed (API keys, tokens, secrets of any kind) is never copied, so
# sandboxed code cannot read what was never handed to it.
_ENV_ALLOW_EXACT = {"PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG",
                    "PYTHONIOENCODING"}
_ENV_ALLOW_PREFIXES = ("LC_",)


def _pin_tmp(env: Dict[str, str], ctx) -> None:
    """Re-pin TEMP/TMP/TMPDIR to ``<jail>/.tmp`` so temp files land
    inside the jail instead of the host temp dir."""
    jail_tmp = Path(ctx.jail_dir) / ".tmp"
    try:
        jail_tmp.mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = env["TEMP"] = env["TMP"] = str(jail_tmp)
    except OSError:
        pass  # temp pinning is best-effort


def _sandbox_env(ctx) -> Dict[str, str]:
    """Build the code_run child environment from the allowlist ONLY.

    Anything not listed (API keys, tokens, secrets of any kind) is
    never copied, so sandboxed code cannot read what it was never
    handed. Temp dirs are re-pinned into the jail, where the audit
    hook allows them.
    """
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        if key in _ENV_ALLOW_EXACT or key.startswith(_ENV_ALLOW_PREFIXES):
            env[key] = value
    _pin_tmp(env, ctx)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


# code_verify runs the OWNER's own test command over the OWNER's own
# project — a different trust posture from code_run's untrusted inline
# code. A bare allowlist would break the toolchain itself (e.g. pytest
# installed as a user-site package is only importable when HOME is
# set), so verify gets the normal environment with secret-looking keys
# scrubbed out, and temp pinned into the jail like the sandbox.
_VERIFY_ENV_DENY = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "APIKEY",
                    "API_KEY", "PRIVATE", "CREDENTIAL", "AUTH", "PROXY",
                    "COOKIE", "SESSION", "BEARER", "KEY_")


def _verify_env(ctx) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for key, value in os.environ.items():
        upper = key.upper()
        if any(marker in upper for marker in _VERIFY_ENV_DENY):
            continue
        env[key] = value
    _pin_tmp(env, ctx)
    return env


# Prepended to every sandboxed run:
#   0. put the jail (the child's cwd) on sys.path — python -I implies
#      safe-path, which would otherwise make sibling jail modules
#      unimportable and the jail useless for multi-file projects
#   1. neuter the network at the socket layer (covers socket, urllib,
#      requests, http.client — anything built on it)
#   2. neuter os.system / os.popen
#   3. install an audit hook: deny process-spawn events outright, and
#      deny open() for paths outside the jail and the interpreter's own
#      install tree (stdlib must stay readable or nothing can import).
_SANDBOX_PREAMBLE = (
    "import sys as _p_guard, os as _p_os;\n"
    "_p_guard.path.insert(0, _p_os.getcwd());\n"
    "del _p_guard, _p_os\n"
    "import socket as _sock_guard;\n"
    "def _no_net(*a, **k):\n"
    "    raise OSError('network disabled in code sandbox')\n"
    "_sock_guard.socket = _no_net\n"
    "_sock_guard.create_connection = _no_net\n"
    "_sock_guard.getaddrinfo = _no_net\n"
    "_sock_guard.gethostbyname = _no_net\n"
    "del _sock_guard, _no_net\n"
    "import os as _os_guard;\n"
    "def _no_spawn(*a, **k):\n"
    "    raise PermissionError('process spawn disabled in code sandbox')\n"
    "_os_guard.system = _no_spawn\n"
    "_os_guard.popen = _no_spawn\n"
    "del _os_guard, _no_spawn\n"
    "def _sg_install():\n"
    "    import sys, os, sysconfig\n"
    "    roots = set()\n"
    "    def add(p):\n"
    "        try:\n"
    "            if p:\n"
    "                roots.add(os.path.realpath(p))\n"
    "        except Exception:\n"
    "            pass\n"
    "    add(os.getcwd())\n"
    "    for key in ('stdlib', 'platlib', 'purelib'):\n"
    "        try:\n"
    "            add(sysconfig.get_path(key))\n"
    "        except Exception:\n"
    "            pass\n"
    "    add(sys.prefix)\n"
    "    add(sys.base_prefix)\n"
    "    spawn = {'subprocess.Popen', 'os.fork', 'os.exec',\n"
    "             'os.posix_spawn', 'os.posix_spawnp'}\n"
    "    def hook(event, args):\n"
    "        if event in spawn:\n"
    "            raise PermissionError(\n"
    "                'process spawn disabled in code sandbox')\n"
    "        if event == 'open':\n"
    "            try:\n"
    "                p = args[0]\n"
    "            except Exception:\n"
    "                return\n"
    "            if isinstance(p, int):\n"
    "                return\n"
    "            try:\n"
    "                rp = os.path.realpath(os.fsdecode(p))\n"
    "            except Exception:\n"
    "                return\n"
    "            for r in roots:\n"
    "                if rp == r or rp.startswith(r + os.sep):\n"
    "                    return\n"
    "            raise PermissionError(\n"
    "                'open outside the code sandbox jail is disabled: '\n"
    "                + repr(p))\n"
    "    sys.addaudithook(hook)\n"
    "try:\n"
    "    _sg_install()\n"
    "except Exception:\n"
    "    pass\n"
    "del _sg_install\n"
)


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child AND its whole process tree (best effort).

    POSIX: the child was started in its own session, so killpg reaches
    every descendant that stayed in the group. Windows: ``taskkill /T``
    walks the tree (argv list, no shell — same discipline as the
    sandbox itself); ``proc.kill()`` is the fallback.
    """
    try:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True, timeout=10, shell=False,
                )
            except Exception:
                pass
            proc.kill()
        elif hasattr(os, "killpg"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


def _exec_argv(argv: Sequence[str], *, cwd: str, env: Dict[str, str],
               timeout_s: float) -> Dict[str, Any]:
    """Run an argv list (never a shell string) with a hard timeout.

    On timeout the entire process tree is killed. Returns exit_code,
    stdout, stderr, timed_out — output NOT capped here (callers cap).
    """
    popen_kwargs: Dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        list(argv),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        shell=False,
        cwd=cwd,
        env=env,
        **popen_kwargs,
    )
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return {"exit_code": proc.returncode, "stdout": out or "",
                "stderr": err or "", "timed_out": False}
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        return {"exit_code": -1, "stdout": out or "", "stderr": err or "",
                "timed_out": True}


def _cap(text: str) -> str:
    if len(text) > OUTPUT_CAP_CHARS:
        return text[:OUTPUT_CAP_CHARS] + "\n…[output truncated at 10KB]"
    return text


def _cap_combined(stdout: str, stderr: str) -> Tuple[str, str]:
    """Cap stdout+stderr at OUTPUT_CAP_CHARS COMBINED (stdout first,
    stderr gets whatever budget remains) plus a truncation marker."""
    if len(stdout) + len(stderr) <= OUTPUT_CAP_CHARS:
        return stdout, stderr
    out = stdout
    if len(out) > OUTPUT_CAP_CHARS:
        out = out[:OUTPUT_CAP_CHARS] + "\n…[output truncated at 10KB]"
    remaining = max(0, OUTPUT_CAP_CHARS - min(len(stdout), OUTPUT_CAP_CHARS))
    err = stderr
    if len(err) > remaining:
        err = err[:remaining] + "\n…[output truncated at 10KB]"
    return out, err


# ---------------------------------------------------------------------------
# Shared helpers: jail paths, backups, freshness state (P3)
# ---------------------------------------------------------------------------


def _numbered(text: str) -> str:
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(text.splitlines()))


def _jailed_path(ctx, path: str) -> Path:
    """Resolve ``path`` inside the jail (same rule as SkillContext)."""
    if Path(path).is_absolute():
        raise ValueError(f"absolute paths are denied: {path!r}")
    jail = Path(ctx.jail_dir).resolve()
    target = (jail / path).resolve()
    if target != jail and jail not in target.parents:
        raise ValueError(f"path escapes jail: {path!r}")
    return target


def _backup(ctx, path: str) -> bool:
    """Save the current file content to <path>.bak. Returns False if the
    file did not exist (nothing to back up)."""
    try:
        old = ctx.read_file(path)
    except FileNotFoundError:
        return False
    ctx.write_file(path + ".bak", old)
    return True


def _load_json_state(ctx, name: str) -> dict:
    p = Path(ctx.jail_dir) / name
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json_state(ctx, name: str, data: dict) -> None:
    p = Path(ctx.jail_dir) / name
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)


def _disk_stamp(ctx, path: str) -> Optional[dict]:
    """(mtime, size, sha256) of the file as it currently sits on disk."""
    try:
        target = _jailed_path(ctx, path)
        data = target.read_bytes()
        st = target.stat()
    except (OSError, ValueError):
        return None
    return {"mtime": st.st_mtime, "size": st.st_size,
            "sha256": hashlib.sha256(data).hexdigest()}


def _record_stamp(ctx, path: str) -> None:
    """Remember the on-disk stamp of ``path`` in the skill state."""
    state = _load_json_state(ctx, _STATE_FILE)
    stamp = _disk_stamp(ctx, path)
    if stamp is None:
        state.pop(path, None)
    else:
        state[path] = stamp
    _save_json_state(ctx, _STATE_FILE, state)


def _check_fresh(ctx, path: str) -> None:
    """Freshness gate for edits: the file must have been read (or
    written) through this skill, and must not have changed since."""
    state = _load_json_state(ctx, _STATE_FILE)
    recorded = state.get(path)
    if recorded is None:
        raise ValueError(
            f"cannot edit {path!r}: it has not been read yet — "
            "call code_read on it first, then edit"
        )
    current = _disk_stamp(ctx, path)
    if current is None:
        raise ValueError(
            f"cannot edit {path!r}: the file no longer exists — "
            "nothing to edit"
        )
    if (current["size"] != recorded.get("size")
            or current["sha256"] != recorded.get("sha256")):
        raise ValueError(
            f"cannot edit {path!r}: it changed since it was last read — "
            "call code_read again to see the current content, then edit"
        )


# ---------------------------------------------------------------------------
# P2 (gate part) — SWE-agent lint gate: a syntax-breaking write/edit of a
# .py file auto-reverts from .bak and reports the revert.
# ---------------------------------------------------------------------------


def _lint_gate(ctx, path: str, content: str,
               backed_up: bool) -> Optional[Dict[str, Any]]:
    """ast.parse the just-written content. On SyntaxError, restore the
    pre-write state (.bak content, or delete a brand-new file) and
    return a revert report; None when the content parses (or is not
    Python)."""
    if not path.endswith(".py"):
        return None
    try:
        ast.parse(content)
        return None
    except SyntaxError as exc:
        detail = f"line {exc.lineno}: {exc.msg}"
    if backed_up:
        try:
            ctx.write_file(path, ctx.read_file(path + ".bak"))
        except Exception:
            pass
    else:
        try:
            _jailed_path(ctx, path).unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
    return {"reverted": True, "syntax_error": detail}


# ---------------------------------------------------------------------------
# read / write
# ---------------------------------------------------------------------------


def _read(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path = args["path"]
    content = ctx.read_file(path)
    _record_stamp(ctx, path)
    ctx.log(f"read {path!r} ({len(content.splitlines())} lines)")
    return {"path": path, "content": _numbered(content),
            "lines": len(content.splitlines())}


def _write(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path, content = args["path"], args["content"]
    backed_up = _backup(ctx, path)
    ctx.write_file(path, content)
    gate = _lint_gate(ctx, path, content, backed_up)
    _record_stamp(ctx, path)
    if gate is not None:
        ctx.log(f"write to {path!r} REVERTED (syntax): {gate['syntax_error']}")
        return {"path": path, "written": False, "backed_up": backed_up,
                "reverted": True, "syntax_error": gate["syntax_error"]}
    ctx.log(f"wrote {path!r} (backup={backed_up})")
    return {"path": path, "written": True, "backed_up": backed_up,
            "reverted": False}


# ---------------------------------------------------------------------------
# P3 — code_edit: 4-rung match ladder (location fuzz only; the replacement
# text is ALWAYS applied verbatim) + freshness gate + similar-line hints.
# ---------------------------------------------------------------------------

_FOLD_MAP = {
    "‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"',
    "„": '"', "–": "-", "—": "-", "―": "-",
    "…": "...", " ": " ",
}


def _fold_line(line: str) -> str:
    folded = unicodedata.normalize("NFKC", line)
    return "".join(_FOLD_MAP.get(ch, ch) for ch in folded)


def _block_starts(haystack: List[str], needle: List[str]) -> List[int]:
    """All start indices where ``needle`` occurs as a contiguous block."""
    if not needle or len(needle) > len(haystack):
        return []
    return [i for i in range(len(haystack) - len(needle) + 1)
            if haystack[i:i + len(needle)] == needle]


def _ambiguous(path: str, rung: str, count: int) -> ValueError:
    return ValueError(
        f"old_text matches {count} times in {path!r} at the {rung} rung — "
        "be more specific (include surrounding lines so it matches "
        "exactly once)"
    )


def _similar_hints(content: str, old_text: str) -> str:
    """difflib most-similar lines to the needle's first line (aider's
    'did you mean' diagnostic), as a compact hint string."""
    needle_lines = [ln.strip() for ln in old_text.splitlines() if ln.strip()]
    if not needle_lines:
        return ""
    probe = needle_lines[0]
    scored = []
    for i, line in enumerate(content.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        ratio = difflib.SequenceMatcher(None, probe, stripped).ratio()
        if ratio >= 0.5:
            scored.append((ratio, i + 1, stripped))
    scored.sort(key=lambda t: (-t[0], t[1]))
    hints = "; ".join(f"line {n}: {text[:80]!r}"
                      for _, n, text in scored[:3])
    return f" Closest lines: {hints}." if hints else ""


def _ladder_replace(content: str, old_text: str, new_text: str,
                    path: str) -> Tuple[str, str]:
    """Find old_text in content through the rungs. Returns
    (new_content, rung_name). Raises ValueError on ambiguity / no match.
    The replacement is never fuzzed — only the LOCATION matching is."""
    # Rung 1 — exact (the original v1 behavior, kept first).
    hits = content.count(old_text)
    if hits == 1:
        return content.replace(old_text, new_text, 1), "exact"
    if hits > 1:
        raise _ambiguous(path, "exact", hits)

    lines = content.split("\n")
    needle_lines = old_text.split("\n")

    # Rung 2 — whitespace-normalized (each line stripped both sides).
    starts = _block_starts([ln.strip() for ln in lines],
                           [ln.strip() for ln in needle_lines])
    if len(starts) == 1:
        i = starts[0]
        merged = lines[:i] + new_text.split("\n") + lines[i + len(needle_lines):]
        return "\n".join(merged), "whitespace"
    if len(starts) > 1:
        raise _ambiguous(path, "whitespace", len(starts))

    # Rung 3 — Unicode-folded (smart quotes, dashes, ligatures, NBSP...).
    starts = _block_starts([_fold_line(ln) for ln in lines],
                           [_fold_line(ln) for ln in needle_lines])
    if len(starts) == 1:
        i = starts[0]
        merged = lines[:i] + new_text.split("\n") + lines[i + len(needle_lines):]
        return "\n".join(merged), "unicode"
    if len(starts) > 1:
        raise _ambiguous(path, "unicode", len(starts))

    # Rung 4 — structural: the needle's first line is a def/class header
    # naming exactly one AST node; that node's whole span is replaced.
    first = next((ln.strip() for ln in needle_lines if ln.strip()), "")
    header = re.match(r"(async\s+def|def|class)\s+([A-Za-z_]\w*)", first)
    if header:
        kind_word, name = header.group(1), header.group(2)
        try:
            tree = ast.parse(content)
        except SyntaxError:
            tree = None
        if tree is not None:
            kinds = (ast.FunctionDef, ast.AsyncFunctionDef) \
                if "def" in kind_word else (ast.ClassDef,)
            nodes = [n for n in ast.walk(tree)
                     if isinstance(n, kinds) and n.name == name]
            if len(nodes) == 1:
                node = nodes[0]
                merged = (lines[:node.lineno - 1] + new_text.split("\n")
                          + lines[node.end_lineno:])
                return "\n".join(merged), "structural"
            if len(nodes) > 1:
                raise _ambiguous(path, "structural", len(nodes))

    raise ValueError(
        f"old_text not found in {path!r} at any rung "
        "(exact / whitespace / unicode / structural) — nothing changed."
        + _similar_hints(content, old_text)
    )


def _edit(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    path, old_text, new_text = args["path"], args["old_text"], args["new_text"]
    if not old_text:
        raise ValueError("old_text must not be empty — name the exact text "
                         "to replace (an empty needle matches everywhere)")
    content = ctx.read_file(path)
    _check_fresh(ctx, path)
    new_content, rung = _ladder_replace(content, old_text, new_text, path)
    backed_up = _backup(ctx, path)
    ctx.write_file(path, new_content)
    gate = _lint_gate(ctx, path, new_content, backed_up)
    _record_stamp(ctx, path)
    if gate is not None:
        ctx.log(f"edit to {path!r} REVERTED (syntax): {gate['syntax_error']}")
        return {"path": path, "edited": False, "rung": rung,
                "reverted": True, "syntax_error": gate["syntax_error"]}
    ctx.log(f"edited {path!r} (rung={rung})")
    return {"path": path, "edited": True, "rung": rung, "reverted": False}


# ---------------------------------------------------------------------------
# code_run — sandboxed execution on the P1 machinery
# ---------------------------------------------------------------------------


def _purge_jail_pycache(ctx) -> None:
    """Drop every __pycache__ under the jail before a run.

    Timestamp-based .pyc validation has 1-second granularity: an edit
    that lands in the same second as the first import, with the same
    file size (``a - b`` -> ``a + b``), is silently served STALE
    bytecode. A verify tool that can grade yesterday's code is worse
    than none, so runs always compile jail sources fresh.
    """
    jail = Path(ctx.jail_dir)
    try:
        for cache_dir in jail.rglob("__pycache__"):
            shutil.rmtree(cache_dir, ignore_errors=True)
    except OSError:
        pass


def _run_sandboxed_source(source: str, ctx) -> Dict[str, Any]:
    """Run Python source through the full sandbox (preamble + allowlist
    env + tree-kill timeout). Shared by code_run and code_verify's repro."""
    _purge_jail_pycache(ctx)
    return _exec_argv(
        [sys.executable, "-I", "-c", _SANDBOX_PREAMBLE + source],
        cwd=str(ctx.jail_dir),
        env=_sandbox_env(ctx),
        timeout_s=RUN_TIMEOUT_S,
    )


def _run(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    code = args.get("code")
    path = args.get("path")
    if (code is None) == (path is None):
        raise ValueError("give exactly one of 'code' (inline source) or 'path' (a .py file in the jail)")
    if path is not None:
        source = ctx.read_file(path)
        _record_stamp(ctx, path)
        label = path
    else:
        source = code
        label = "<inline>"
    ctx.log(f"running {label} (sandbox: 10s, no network, jail cwd)")
    raw = _run_sandboxed_source(source, ctx)
    out, err = _cap_combined(raw["stdout"], raw["stderr"])
    return {"exit_code": raw["exit_code"], "stdout": out, "stderr": err,
            "timed_out": raw["timed_out"]}


# ---------------------------------------------------------------------------
# P2 — code_verify: differential verification (SWE-agent / Agentless).
# Snapshot the project's test state BEFORE edits, re-run AFTER, and grade
# ONLY test outcomes: FULL (repro passes + zero regressions + no baseline
# failure left standing) / PARTIAL (verified progress, something remains)
# / NO. No parseable test output means NOT verified — never a vibe grade.
# ---------------------------------------------------------------------------

_VERIFY_XML = ".code_verify_results.xml"


def _outcome_summary(outcome: dict) -> dict:
    """The outcome without the bulky per-test dict (for results/state IO)."""
    return {k: v for k, v in outcome.items() if k != "tests"}


def _parse_junit(ctx, raw: dict) -> Optional[dict]:
    xml_path = Path(ctx.jail_dir) / _VERIFY_XML
    try:
        root = ET.parse(str(xml_path)).getroot()
    except Exception:
        return None
    tests: Dict[str, str] = {}
    for case in root.iter("testcase"):
        name = case.get("name") or ""
        classname = case.get("classname") or ""
        full = f"{classname}::{name}" if classname else name
        status = "passed"
        for child in case:
            if child.tag == "failure":
                status = "failed"
            elif child.tag == "error":
                status = "error"
            elif child.tag == "skipped":
                status = "skipped"
        tests[full] = status
    if not tests:
        return None
    failed_names = sorted(n for n, s in tests.items()
                          if s in ("failed", "error"))
    return {
        "mode": "pytest-junit", "parseable": True, "tests": tests,
        "total": len(tests),
        "passed": sum(1 for s in tests.values() if s == "passed"),
        "failed": sum(1 for s in tests.values() if s == "failed"),
        "errors": sum(1 for s in tests.values() if s == "error"),
        "skipped": sum(1 for s in tests.values() if s == "skipped"),
        "failed_names": failed_names,
        "exit_code": raw["exit_code"], "timed_out": raw["timed_out"],
    }


def _parse_unittest(raw: dict) -> Optional[dict]:
    text = (raw["stdout"] or "") + "\n" + (raw["stderr"] or "")
    total_match = re.search(r"Ran (\d+) tests?", text)
    if not total_match or ("OK" not in text and "FAILED" not in text):
        return None
    fail_names = sorted(set(re.findall(r"^FAIL: (.+)$", text, re.M)))
    error_names = sorted(set(re.findall(r"^ERROR: (.+)$", text, re.M)))
    total = int(total_match.group(1))
    return {
        "mode": "unittest-text", "parseable": True,
        "total": total,
        "passed": max(0, total - len(fail_names) - len(error_names)),
        "failed": len(fail_names), "errors": len(error_names),
        "skipped": 0,
        "failed_names": sorted(fail_names + error_names),
        "exit_code": raw["exit_code"], "timed_out": raw["timed_out"],
    }


def _verify_once(argv: List[str], ctx) -> dict:
    """Run the test command once and parse its outcome (data, not prose)."""
    _purge_jail_pycache(ctx)  # verdicts must grade the code on disk NOW
    run_argv = list(argv)
    is_pytest = any("pytest" in part for part in run_argv)
    if is_pytest and not any("junitxml" in part for part in run_argv):
        run_argv = run_argv + ["--junitxml", _VERIFY_XML]
    raw = _exec_argv(run_argv, cwd=str(ctx.jail_dir),
                     env=_verify_env(ctx), timeout_s=VERIFY_TIMEOUT_S)
    outcome = None
    if is_pytest:
        outcome = _parse_junit(ctx, raw)
    if outcome is None and any("unittest" in part for part in run_argv):
        outcome = _parse_unittest(raw)
    if outcome is None:
        outcome = {
            "mode": "unparseable", "parseable": False,
            "total": 0, "passed": 0, "failed": 0, "errors": 0,
            "skipped": 0, "failed_names": [],
            "exit_code": raw["exit_code"], "timed_out": raw["timed_out"],
        }
    return outcome


def _compare(baseline: dict, after: dict) -> Tuple[List[str], List[str], List[str]]:
    """(fixed, regressions, remaining_failures) — names where known."""
    if "tests" in baseline and "tests" in after:
        b, a = baseline["tests"], after["tests"]
        b_fail = {n for n, s in b.items() if s in ("failed", "error")}
        a_fail = {n for n, s in a.items() if s in ("failed", "error")}
        b_pass = {n for n, s in b.items() if s == "passed"}
        fixed = sorted(n for n in b_fail if a.get(n) == "passed")
        regressions = sorted(n for n in b_pass
                             if n in a_fail or n not in a)
        remaining = sorted(b_fail & a_fail)
        return fixed, regressions, remaining
    b_names = set(baseline.get("failed_names", []))
    a_names = set(after.get("failed_names", []))
    return (sorted(b_names - a_names), sorted(a_names - b_names),
            sorted(b_names & a_names))


def _verdict(after: dict, fixed: list, regressions: list,
             remaining: list) -> str:
    if not after["parseable"]:
        return "NO"  # no parseable output ⇒ not verified, by rule
    repro_ok = after.get("repro") != "failed"
    if repro_ok and not regressions and not remaining:
        return "FULL"
    if fixed or after.get("repro") == "passed":
        return "PARTIAL"
    return "NO"


def _verify(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    command = args.get("command")
    if (not isinstance(command, list) or not command
            or any(not isinstance(part, str) or not part for part in command)):
        raise ValueError("command must be a non-empty list of strings "
                         "(an argv list — never a shell string)")
    argv = list(command)
    if Path(argv[0]).name in ("python", "python3"):
        argv[0] = sys.executable
    repro = args.get("repro")
    reset = bool(args.get("reset"))

    current = _verify_once(argv, ctx)
    if repro:
        source = ctx.read_file(repro)
        raw = _run_sandboxed_source(source, ctx)
        current["repro"] = ("passed" if raw["exit_code"] == 0
                            and not raw["timed_out"] else "failed")
    else:
        current["repro"] = "not_run"

    key = hashlib.sha256(
        json.dumps({"argv": argv, "repro": repro}).encode("utf-8")
    ).hexdigest()[:16]
    state = _load_json_state(ctx, _VERIFY_FILE)
    summary = _outcome_summary(current)

    if reset or key not in state:
        state[key] = current
        _save_json_state(ctx, _VERIFY_FILE, state)
        ctx.log("code_verify: baseline snapshot stored")
        return {"phase": "baseline", "verdict": "BASELINE",
                "parseable": current["parseable"], "baseline": summary,
                "current": summary, "fixed": [], "regressions": [],
                "remaining_failures": summary["failed_names"],
                "repro": current["repro"]}

    baseline = state[key]
    fixed, regressions, remaining = _compare(baseline, current)
    verdict = _verdict(current, fixed, regressions, remaining)
    ctx.log(f"code_verify: verdict {verdict} "
            f"(fixed={len(fixed)}, regressions={len(regressions)}, "
            f"remaining={len(remaining)})")
    return {"phase": "after", "verdict": verdict,
            "parseable": current["parseable"],
            "baseline": _outcome_summary(baseline), "current": summary,
            "fixed": fixed[:50], "regressions": regressions[:50],
            "remaining_failures": remaining[:50],
            "repro": current["repro"]}


# ---------------------------------------------------------------------------
# P4 — code_map: aider's repo map, stdlib port. AST def/ref graph over the
# jail's .py files + personalized PageRank + sqlite mtime cache, rendered
# inside a line budget. No embeddings, no vector DB — exact structure.
# ---------------------------------------------------------------------------

_MAP_MAX_LINES = 250
_MAP_MAX_SYMBOLS = 200


def _ast_defs(tree: ast.AST) -> List[dict]:
    """Qualified defs of one file, each with the names its body refs."""
    defs: List[dict] = []

    def signature(node) -> str:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            return f"class {node.name}({bases})" if bases else f"class {node.name}"
        try:
            args = ast.unparse(node.args)
        except Exception:
            args = "..."
        return f"def {node.name}({args})"

    def collect(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
                qname = prefix + child.name
                refs: Dict[str, int] = {}
                for sub in ast.walk(child):
                    target = None
                    if isinstance(sub, ast.Name):
                        target = sub.id
                    elif isinstance(sub, ast.Attribute):
                        base = sub
                        while isinstance(base, ast.Attribute):
                            base = base.value
                        if isinstance(base, ast.Name):
                            target = base.id
                    if target:
                        refs[target] = refs.get(target, 0) + 1
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                defs.append({"name": qname, "kind": kind,
                             "line": child.lineno,
                             "sig": signature(child)[:70], "refs": refs})
                collect(child, qname + ".")
            else:
                collect(child, prefix)

    collect(tree, "")
    return defs


def _map_load_cache(ctx) -> sqlite3.Connection:
    db = sqlite3.connect(str(Path(ctx.jail_dir) / _MAP_DB))
    db.execute(
        "CREATE TABLE IF NOT EXISTS files ("
        "path TEXT PRIMARY KEY, mtime REAL, size INTEGER, "
        "sha TEXT, defs TEXT)"
    )
    return db


def _map(args: Dict[str, Any], ctx) -> Dict[str, Any]:
    focus = [str(f) for f in (args.get("focus") or [])]
    jail = Path(ctx.jail_dir).resolve()
    files: List[Tuple[str, Path]] = []
    for candidate in sorted(jail.rglob("*.py")):
        rel = candidate.relative_to(jail).as_posix()
        parts = rel.split("/")
        if any(part.startswith(".") or part == "__pycache__"
               for part in parts):
            continue
        files.append((rel, candidate))

    db = None
    try:
        db = _map_load_cache(ctx)
    except Exception:
        db = None  # cache is an optimization; parsing works without it

    per_file: Dict[str, List[dict]] = {}
    seen_paths = set()
    for rel, candidate in files:
        seen_paths.add(rel)
        try:
            data = candidate.read_bytes()
            st = candidate.stat()
        except OSError:
            continue
        sha = hashlib.sha256(data).hexdigest()
        defs = None
        if db is not None:
            row = db.execute(
                "SELECT mtime, size, sha, defs FROM files WHERE path = ?",
                (rel,)).fetchone()
            if row and row[0] == st.st_mtime and row[1] == st.st_size \
                    and row[2] == sha:
                try:
                    defs = json.loads(row[3])
                except Exception:
                    defs = None
        if defs is None:
            try:
                tree = ast.parse(data.decode("utf-8", errors="replace"))
                defs = _ast_defs(tree)
            except SyntaxError:
                defs = []
            if db is not None:
                db.execute(
                    "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?)",
                    (rel, st.st_mtime, st.st_size, sha,
                     json.dumps(defs)))
        per_file[rel] = defs
    if db is not None:
        try:
            stale = [r[0] for r in db.execute("SELECT path FROM files")
                     if r[0] not in seen_paths]
            for path in stale:
                db.execute("DELETE FROM files WHERE path = ?", (path,))
            db.commit()
            db.close()
        except Exception:
            pass

    # Graph: node = "path:qname"; edge A -> B when A's body references
    # B's short name (aider-style; weight = sqrt of the reference count).
    node_file: Dict[str, str] = {}
    node_def: Dict[str, dict] = {}
    by_short: Dict[str, List[str]] = {}
    for rel, defs in per_file.items():
        for d in defs:
            node = f"{rel}:{d['name']}"
            node_file[node] = rel
            node_def[node] = d
            by_short.setdefault(d["name"].split(".")[-1], []).append(node)
    nodes = sorted(node_def)
    if not nodes:
        return {"map": "(no Python definitions found in the jail)",
                "symbols": [], "files": len(per_file), "nodes": 0,
                "truncated": False}

    edges: Dict[str, List[Tuple[str, float]]] = {n: [] for n in nodes}
    for node in nodes:
        for ref_name, count in node_def[node]["refs"].items():
            for target in by_short.get(ref_name, []):
                if target != node:
                    edges[node].append((target, math.sqrt(count)))

    # Personalized PageRank (~25 lines): focus names x10, focus files x5.
    personal = []
    for node in nodes:
        weight = 1.0
        if node_def[node]["name"].split(".")[-1] in focus \
                or node_def[node]["name"] in focus or node in focus:
            weight *= 10.0
        if node_file[node] in focus:
            weight *= 5.0
        personal.append(weight)
    total = sum(personal)
    personal = [w / total for w in personal]
    index = {node: i for i, node in enumerate(nodes)}
    out_sum = {n: sum(w for _, w in edges[n]) for n in nodes}
    rank = list(personal)
    damping = 0.85
    for _ in range(50):
        new = [(1.0 - damping) * p for p in personal]
        for node in nodes:
            i = index[node]
            if out_sum[node] <= 0:
                for j in range(len(nodes)):
                    new[j] += damping * rank[i] * personal[j]
                continue
            for target, w in edges[node]:
                new[index[target]] += damping * rank[i] * w / out_sum[node]
        delta = sum(abs(new[i] - rank[i]) for i in range(len(nodes)))
        rank = new
        if delta < 1e-6:
            break
    score = {node: rank[index[node]] for node in nodes}

    ranked = sorted(nodes, key=lambda n: (-score[n], n))
    symbols = [{"name": node_def[n]["name"], "path": node_file[n],
                "line": node_def[n]["line"], "kind": node_def[n]["kind"],
                "score": round(score[n], 4)}
               for n in ranked[:_MAP_MAX_SYMBOLS]]

    by_file: Dict[str, List[str]] = {}
    for node in ranked:
        by_file.setdefault(node_file[node], []).append(node)
    file_order = sorted(by_file,
                        key=lambda f: (-max(score[n] for n in by_file[f]), f))
    lines = [f"# code map — {len(per_file)} files, {len(nodes)} symbols",
             "# ranked by PageRank over the def/ref graph"]
    truncated = False
    for rel in file_order:
        block = [f"{rel}:"]
        for node in by_file[rel]:
            d = node_def[node]
            block.append(f"  {d['sig']}  · line {d['line']}  "
                         f"· score {score[node]:.4f}")
        if len(lines) + len(block) > _MAP_MAX_LINES:
            truncated = True
            break
        lines.extend(block)
    if len(symbols) >= _MAP_MAX_SYMBOLS:
        truncated = True
    ctx.log(f"code_map: {len(per_file)} files, {len(nodes)} symbols")
    return {"map": "\n".join(lines), "symbols": symbols,
            "files": len(per_file), "nodes": len(nodes),
            "truncated": truncated}


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "code_read":
        return _read(args, ctx)
    if tool_name == "code_write":
        return _write(args, ctx)
    if tool_name == "code_edit":
        return _edit(args, ctx)
    if tool_name == "code_run":
        return _run(args, ctx)
    if tool_name == "code_verify":
        return _verify(args, ctx)
    if tool_name == "code_map":
        return _map(args, ctx)
    raise ValueError(f"unknown tool {tool_name!r}")
