"""Tokenised shell guard — the second layer over pc.shell (ledger L125).

Why this exists: pc_control's tier-3 blocklist matches regexes against the RAW
command string. Raw matching is bypassable by anything that changes the text
without changing the meaning -- quoting the program name ('r"m"'), splitting
flags ('-r -f'), long flags ('--recursive'), env prefixes, /bin/ paths,
interpreter inline payloads ('bash -c ...'). A shell does not care about any
of that; it tokenises first. So do we (casha-cashu/jarvis pattern, team6):

  1. Split the command into segments on shell separators (;, &&, ||, |, &).
  2. Tokenise each segment respecting quotes (minimally: quotes group and are
     then dropped, escapes honoured outside single quotes).
  3. Normalise: expansions ($VAR, ${...}, $(...), backticks) collapse to
     placeholders -- and command-substitution payloads are kept aside and
     screened recursively. The program token is de-pathed and lowercased.
  4. Match DANGEROUS TOKEN SEQUENCES (program + flags + targets), never raw
     substrings.

Doctrine (fail-closed, mirroring casha): where runtime expansion hides the
real program or a destructive target, refuse outright -- the expansion cannot
be resolved statically, and pc.shell commands are machine-generated, so no
legitimate command needs it.

This module is a SECOND layer. It never replaces or weakens the legacy
raw-string blocklist in pc_control: check_command() runs a caller-supplied
legacy check first (preserving its reason strings) and this layer second;
either layer may block.

Stdlib only: re, dataclasses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VAR_PLACEHOLDER = "<VAR>"
SUBST_PLACEHOLDER = "<SUBST>"

_MAX_DEPTH = 3  # inline-payload / substitution recursion cap

_WRAPPERS = {"sudo", "doas", "env", "command", "nice", "time"}
_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DEVICE_RE = re.compile(
    r"^(sd[a-z]|hd[a-z]|nvme\d|vd[a-z]|mmcblk\d|mapper/|disk\d)")
_PIPE_SOURCES = {"curl", "wget", "aria2c", "iwr", "invoke-webrequest"}
_PIPE_SHELLS = {"sh", "bash", "zsh", "dash", "ash", "powershell", "pwsh",
                "cmd", "python", "python2", "python3", "perl", "iex",
                "invoke-expression"}
_INTERPRETERS = {"sh", "bash", "zsh", "dash", "ash", "powershell", "pwsh",
                 "python", "python2", "python3", "perl", "ruby", "node"}
_POWERSHELL = {"powershell", "pwsh"}
_ENCODED_FLAGS = {"-e", "-enc", "-encodedcommand", "-ec"}
_SHUTDOWN_PROGRAMS = {"shutdown", "reboot", "halt", "poweroff"}
_ALWAYS_BLOCK_PROGRAMS = {"mkfs", "takeown", "icacls", "bcdedit", "diskpart",
                          "regedit"}
_DANGEROUS_OPERANDS = {"/", "/*", "~", "~/", "~/*", "*", ".", "..", "./*"}
_FORK_BOMB_FLAT = ":(){:|:&};:"


@dataclass
class ShellVerdict:
    blocked: bool
    reason: str = ""
    rule: str = ""                       # which rule / layer fired
    segments: list = field(default_factory=list)  # normalised tokens


# ---------------------------------------------------------------------------
# Tokeniser
# ---------------------------------------------------------------------------

@dataclass
class _Segment:
    tokens: list[str]
    sep_before: str | None               # None, ";", "&&", "||", "|", "&"
    subst_payloads: list[str] = field(default_factory=list)


def _read_expansion(cmd: str, i: int) -> tuple[str, int, str | None]:
    """cmd[i] == '$'. Returns (replacement, next_index, subst_payload|None)."""
    n = len(cmd)
    if i + 1 < n and cmd[i + 1] == "(":
        # Command substitution: capture the balanced-paren payload.
        depth = 0
        j = i + 1
        while j < n:
            if cmd[j] == "(":
                depth += 1
            elif cmd[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        payload = cmd[i + 2:j]
        return SUBST_PLACEHOLDER, min(j + 1, n), payload
    if i + 1 < n and cmd[i + 1] == "{":
        j = cmd.find("}", i + 2)
        return VAR_PLACEHOLDER, (n if j == -1 else j + 1), None
    m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*", cmd[i:])
    if m:
        return VAR_PLACEHOLDER, i + len(m.group(0)), None
    return "$", i + 1, None


def _parse(command: str) -> list[_Segment]:
    """Split + tokenise. Quotes group (then vanish); operators separate."""
    segments: list[_Segment] = []
    tokens: list[str] = []
    payloads: list[str] = []
    buf: list[str] = []
    sep: str | None = None
    state: str | None = None  # None | "'" | '"'
    i, n = 0, len(command)

    def flush_token() -> None:
        if buf:
            tokens.append("".join(buf))
            buf.clear()

    def flush_segment(new_sep: str | None) -> None:
        nonlocal tokens, payloads, sep
        flush_token()
        segments.append(_Segment(tokens, sep, payloads))
        tokens, payloads, sep = [], [], new_sep

    while i < n:
        ch = command[i]
        if state == "'":
            if ch == "'":
                state = None
            else:
                buf.append(ch)
            i += 1
            continue
        if state == '"':
            if ch == '"':
                state = None
                i += 1
                continue
            if ch == "\\" and i + 1 < n and command[i + 1] in '"$`\\':
                buf.append(command[i + 1])
                i += 2
                continue
            if ch == "`":
                j = command.find("`", i + 1)
                if j == -1:
                    j = n
                payloads.append(command[i + 1:j])
                buf.append(SUBST_PLACEHOLDER)
                i = min(j + 1, n)
                continue
            if ch == "$":
                rep, i, payload = _read_expansion(command, i)
                buf.append(rep)
                if payload is not None:
                    payloads.append(payload)
                continue
            buf.append(ch)
            i += 1
            continue
        # Unquoted.
        if ch == "'":
            state = "'"
            i += 1
            continue
        if ch == '"':
            state = '"'
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            buf.append(command[i + 1])
            i += 2
            continue
        if ch == "`":
            j = command.find("`", i + 1)
            if j == -1:
                j = n
            payloads.append(command[i + 1:j])
            buf.append(SUBST_PLACEHOLDER)
            i = min(j + 1, n)
            continue
        if ch == "$":
            rep, i, payload = _read_expansion(command, i)
            buf.append(rep)
            if payload is not None:
                payloads.append(payload)
            continue
        two = command[i:i + 2]
        if two in ("&&", "||", ">>"):
            if two == ">>":
                flush_token()
                tokens.append(">>")
            else:
                flush_segment(two)
            i += 2
            continue
        if ch in ";|&\n":
            flush_segment("|" if ch == "|" else ("&" if ch == "&" else ";"))
            i += 1
            continue
        if ch == ">":
            flush_token()
            tokens.append(">")
            i += 1
            continue
        if ch == "<":
            flush_token()
            tokens.append("<")
            i += 1
            continue
        if ch in " \t\r":
            flush_token()
            i += 1
            continue
        buf.append(ch)
        i += 1

    flush_segment(None)
    # Drop segments that are entirely empty (leading/trailing separators).
    return [s for s in segments if s.tokens or s.subst_payloads]


def tokenize(command: str) -> list[list[str]]:
    """Public: normalised tokens per segment (quotes stripped, expansions
    collapsed to <VAR>/<SUBST> placeholders)."""
    return [list(s.tokens) for s in _parse(command or "")]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _program_name(token: str) -> str:
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for ext in (".exe", ".bat", ".cmd", ".com"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


def _program_index(tokens: list[str]) -> int | None:
    """Index of the program token, skipping env assignments and wrappers
    (sudo/env/... plus their flags). None if the segment has no program."""
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if _ASSIGNMENT_RE.match(tok):
            i += 1
            continue
        if _program_name(tok) in _WRAPPERS:
            i += 1
            # Skip the wrapper's own flags (and the value of -u).
            while i < len(tokens) and tokens[i].startswith("-"):
                flag = tokens[i]
                i += 1
                if flag in ("-u", "-C", "-g", "-h") and i < len(tokens):
                    i += 1
            continue
        return i
    return None


def _short_flag_chars(tokens: list[str]) -> set[str]:
    """All single-dash flag characters (combined clusters split), up to --."""
    chars: set[str] = set()
    for tok in tokens:
        if tok == "--":
            break
        if tok.startswith("-") and not tok.startswith("--") and len(tok) > 1:
            chars.update(tok[1:])
    return chars


def _operands(tokens: list[str]) -> list[str]:
    """Non-flag arguments after the program, honouring --."""
    out: list[str] = []
    seen_dd = False
    for tok in tokens:
        if tok == "--":
            seen_dd = True
            continue
        if not seen_dd and tok.startswith("-") and tok != "-":
            continue
        out.append(tok)
    return out


def _is_device_path(path: str) -> bool:
    p = path.replace("\\", "/")
    if p.startswith("/dev/"):
        return bool(_DEVICE_RE.match(p[5:]))
    return False


def _dangerous_target(tok: str) -> bool:
    """Catastrophic destructive target test (casha semantics): root, home,
    cwd, globs, top-level absolute paths, and anything hidden by expansion."""
    if VAR_PLACEHOLDER in tok or SUBST_PLACEHOLDER in tok:
        return True
    low = tok.lower().replace("\\", "/")
    if low in _DANGEROUS_OPERANDS or "*" in low:
        return True
    if low.startswith("~/"):
        return True
    if low.startswith("/"):
        parts = [p for p in low.split("/") if p]
        return len(parts) <= 1
    if re.match(r"^[a-z]:/?$", low):       # bare drive root, e.g. C:\
        return True
    if re.match(r"^[a-z]:/[^/]+/?$", low):  # one level deep: C:\Windows
        return True
    return False


# ---------------------------------------------------------------------------
# Rule engine
# ---------------------------------------------------------------------------

def _check_segment(seg: _Segment, depth: int) -> str | None:
    """Returns a block reason for one segment, or None."""
    tokens = seg.tokens
    if not tokens:
        return None
    idx = _program_index(tokens)
    if idx is None:
        return None
    prog_token = tokens[idx]
    prog = _program_name(prog_token)
    args = tokens[idx + 1:]

    if VAR_PLACEHOLDER in prog_token or SUBST_PLACEHOLDER in prog_token:
        return "program name hidden by shell expansion -- refuse outright"

    # Redirection into a block device, in ANY segment (even echo's).
    for pos, tok in enumerate(tokens):
        if tok in (">", ">>") and pos + 1 < len(tokens) \
                and _is_device_path(tokens[pos + 1]):
            return f"redirect into block device {tokens[pos + 1]}"

    if prog.startswith("mkfs") or prog in _ALWAYS_BLOCK_PROGRAMS:
        return f"forbidden program: {prog}"
    if prog in _SHUTDOWN_PROGRAMS:
        return f"system power command: {prog}"

    if prog == "rm":
        flags = _short_flag_chars(args)
        recursive = "r" in flags or "--recursive" in args
        if recursive:
            for target in _operands(args):
                if _dangerous_target(target):
                    return (f"recursive delete of catastrophic target "
                            f"{target!r}")
    elif prog == "dd":
        for tok in args:
            if tok.startswith("of=") and _is_device_path(tok[3:]):
                return f"dd writing to block device {tok[3:]}"
    elif prog == "format":
        if any(re.match(r"^[a-zA-Z]:", t) for t in _operands(args)):
            return "disk format"
    elif prog == "chmod":
        flags = _short_flag_chars(args)
        if "R" in flags or "--recursive" in args:
            operands = _operands(args)
            modes = [t for t in operands
                     if re.fullmatch(r"[0-7]{3,4}", t)
                     or "rwx" in t.lower()]
            world_open = any(
                (len(m) >= 3 and m[-1] in "2367") or "a+rwx" in m.lower()
                or "o+w" in m.lower() for m in modes)
            if world_open:
                for target in operands:
                    if target not in modes and _dangerous_target(target):
                        return ("recursive world-writable chmod on "
                                f"catastrophic target {target!r}")
    elif prog == "reg":
        operands = _operands(args)
        if operands and operands[0].lower() == "delete":
            return "Windows registry deletion"
    elif prog == "net":
        operands = _operands(args)
        if operands and operands[0].lower() in ("user", "localgroup"):
            return "account/group modification"
    elif prog in ("del", "erase", "rd", "rmdir"):
        flags = _short_flag_chars(args)
        if "s" in flags or "/s" in [a.lower() for a in args]:
            for target in _operands(args):
                low = target.lower().replace("\\", "/")
                if "windows" in low or _dangerous_target(target):
                    return f"mass delete via {prog} of {target!r}"

    # Interpreter inline code: screen the payload recursively. Encoded
    # PowerShell payloads are refused outright (never decoded-and-trusted).
    if prog in _INTERPRETERS:
        for pos, tok in enumerate(args):
            low = tok.lower()
            if prog in _POWERSHELL and low in _ENCODED_FLAGS:
                return "encoded PowerShell payload (obfuscation)"
            if low in ("-c", "-command") and pos + 1 < len(args):
                inner = analyze(args[pos + 1], _depth=depth + 1)
                if inner.blocked:
                    return (f"interpreter inline payload blocked: "
                            f"{inner.reason}")
    return None


def analyze(command: str, _depth: int = 0) -> ShellVerdict:
    """Tokenised-layer analysis of a full command string."""
    if _depth > _MAX_DEPTH:
        return ShellVerdict(True, "inline/substitution nesting too deep",
                            "depth-cap")
    segments = _parse(command or "")
    norm = [list(s.tokens) for s in segments]

    # Fork bomb: whitespace is not a token, so stripping it from the raw
    # command reconstructs the shape no matter how the author spaced it
    # (": ( ) { : | : & } ; :" compacts to the same string as ":(){:|:&};:").
    compact = re.sub(r"\s+", "", command or "").lower()
    if _FORK_BOMB_FLAT in compact:
        return ShellVerdict(True, "fork bomb", "fork-bomb", norm)

    prev_prog: str | None = None
    for seg in segments:
        idx = _program_index(seg.tokens) if seg.tokens else None
        prog = _program_name(seg.tokens[idx]) \
            if idx is not None else None
        # Pipe-to-shell: download tool piped into an interpreter.
        if seg.sep_before == "|" and prev_prog in _PIPE_SOURCES \
                and prog in _PIPE_SHELLS:
            return ShellVerdict(
                True, f"download piped to shell ({prev_prog} | {prog})",
                "pipe-to-shell", norm)
        reason = _check_segment(seg, _depth)
        if reason:
            return ShellVerdict(True, reason, "segment", norm)
        # Command substitutions are screened too (their payload is code).
        for payload in seg.subst_payloads:
            inner = analyze(payload, _depth=_depth + 1)
            if inner.blocked:
                return ShellVerdict(
                    True, f"command substitution blocked: {inner.reason}",
                    "substitution", norm)
        prev_prog = prog
    return ShellVerdict(False, "", "", norm)


def check_command(command: str, legacy_check=None) -> ShellVerdict:
    """Combined entry point. Layer 1: the legacy raw-string blocklist (via the
    caller's callable, preserving its reason strings). Layer 2: this
    tokenised guard. Either layer may block; neither is weakened."""
    if legacy_check is not None:
        try:
            why = legacy_check(command)
        except Exception:
            why = "legacy blocklist error -- fail closed"
        if why:
            return ShellVerdict(True, str(why), "legacy",
                                tokenize(command))
    return analyze(command)
