"""Knowledge skill: passage search over Ovi's research library.

The library (knowledge/*.md, ~2MB) ships inside the repo. Retrieval is
two-stage, stdlib only (Team 21 personal-RAG upgrade):

1. Sparse stage — sqlite FTS5/BM25 over *chunks*, not whole files.
   Documents are split by a structure-aware cascade (markdown headings
   -> paragraphs -> sentences -> lines -> char windows) into 256-512
   char passages with ~25 chars of overlap (LEANN/localGPT sizing).
2. Dense stage (optional) — LEANN-style on-demand embedding recall:
   nothing is embedded at ingest and no vectors are stored. When an
   embedder callable is injected (ctx.embedder, or the string "hashed"
   for the built-in stdlib fallback), embeddings are computed at query
   time over the BM25 shortlist only and the shortlist is re-ranked by
   cosine similarity. If the embedder errors or returns malformed
   vectors, the BM25 order is returned unchanged — rerank can never
   make results worse than the sparse stage alone.

Ingest is content-addressed: each source file's sha256 is stored in
the index; unchanged files are skipped on re-sync, changed files are
re-chunked, removed files are dropped (mcp-local-rag pattern). The
index carries a schema version; a stale index is rebuilt into a temp
file and atomically swapped in, so a failed rebuild never corrupts
the live index.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

SKILL_NAME = "knowledge"

TOOL_DEFINITIONS = [
    {
        "name": "knowledge_search",
        "description": ("Search Ovi's research library (70+ deep studies). "
                        "Returns relevant passages with source files."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "What to look up"},
                "top_k": {"type": "integer",
                          "description": "Max passages (default 3, max 8)"},
            },
            "required": ["query"],
        },
        "tier": 1,
        "capabilities": ["fs.read"],
    }
]

# --- index + chunking constants -------------------------------------------
INDEX_VERSION = "2"
CHUNK_MIN = 256          # target floor for a packed chunk (chars)
CHUNK_MAX = 512          # hard ceiling for any emitted chunk (chars)
CHUNK_OVERLAP = 25       # chars carried from the previous chunk's tail
_SHORTLIST_MAX = 32      # BM25 candidates fed to the rerank stage

_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    path, title, section, body, tokenize='porter');
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS file_hashes (
    path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, chunks INTEGER NOT NULL);
"""


def _library_dir() -> Path:
    # skills/knowledge/skill.py -> repo root
    return Path(__file__).resolve().parent.parent.parent


def _source_files(lib: Path):
    """All trainable sources: research library + codebase map + self + source."""
    yield from sorted(lib.glob("knowledge/*.md"))
    for extra in ["CODEBASE.md", "SELF.md", "JARVIS-RULES.txt"]:
        p = lib / extra
        if p.exists():
            yield p
    yield from sorted((lib / "jarvis").glob("*.py"))
    for skill_dir in sorted((lib / "skills").glob("*")):
        if skill_dir.is_dir():
            yield from sorted(skill_dir.glob("*.md"))
            py = skill_dir / "skill.py"
            if py.exists():
                yield py


def _cache_path(ctx) -> Path:
    d = Path(ctx.jail_dir) / "knowledge_index"
    d.mkdir(parents=True, exist_ok=True)
    return d / "fts5.db"


def _rel(lib: Path, f: Path) -> str:
    try:
        return str(f.relative_to(lib))
    except ValueError:
        return f.name


def _doc_title(text: str, fallback: str) -> str:
    for line in text.splitlines()[:5]:
        if line.startswith("#"):
            return line.lstrip("# ").strip()
    return fallback


# --- chunking cascade -------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_PY_DEF_RE = re.compile(r"^(?:async\s+def|def|class)\s")


def _split_sections(text: str, kind: str) -> List[Tuple[str, str]]:
    """Stage 1: split on markdown headings (md/txt only). Code files are
    one anonymous section; their structure is handled at stage 2."""
    if kind == "py":
        return [("", text)]
    sections: List[Tuple[str, List[str]]] = []
    heading = ""
    buf: List[str] = []
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            sections.append((heading, buf))
            heading = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    sections.append((heading, buf))
    return [(h, "\n".join(b)) for h, b in sections if "\n".join(b).strip()]


def _split_units(body: str, kind: str) -> List[str]:
    """Stage 2: paragraph units (blank-line separated). For Python, a
    top-level def/class also starts a new unit."""
    if kind == "py":
        lines: List[str] = []
        for line in body.splitlines():
            if _PY_DEF_RE.match(line) and lines and lines[-1].strip():
                lines.append("")
            lines.append(line)
        body = "\n".join(lines)
    units = [u.strip() for u in re.split(r"\n\s*\n", body)]
    return [u for u in units if u]


def _hard_windows(text: str, limit: int) -> List[str]:
    """Final fallback: char windows of `limit` stepping by limit-overlap."""
    out = []
    step = max(1, limit - CHUNK_OVERLAP)
    for i in range(0, len(text), step):
        out.append(text[i:i + limit])
        if i + limit >= len(text):
            break
    return out


def _split_oversize(unit: str, limit: int) -> List[str]:
    """Split one oversize unit: sentences first, then lines, then chars."""
    if len(unit) <= limit:
        return [unit]
    pieces: List[str] = []
    for sent in _SENTENCE_RE.split(unit):
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= limit:
            pieces.append(sent)
            continue
        # A single sentence longer than the limit: try its lines.
        lines = [ln for ln in sent.splitlines() if ln.strip()]
        if len(lines) > 1:
            cur = ""
            for ln in lines:
                cand = f"{cur}\n{ln}" if cur else ln
                if len(cand) <= limit:
                    cur = cand
                else:
                    if cur:
                        pieces.append(cur)
                    cur = ln if len(ln) <= limit else ""
                    if len(ln) > limit:
                        pieces.extend(_hard_windows(ln, limit))
            if cur:
                pieces.append(cur)
        else:
            pieces.extend(_hard_windows(sent, limit))
    return pieces or _hard_windows(unit, limit)


def _overlap_prefix(prev_core: str) -> str:
    """Tail of the previous chunk (~CHUNK_OVERLAP chars), cut forward to
    a word boundary so no half-word is carried."""
    if not prev_core:
        return ""
    tail = prev_core[-CHUNK_OVERLAP:]
    sp = tail.find(" ")
    if 0 <= sp < len(tail) - 1:
        tail = tail[sp + 1:]
    return tail + " " if tail else ""


def chunk_text(text: str, kind: str = "md") -> List[Tuple[str, str]]:
    """Split a document into (section, chunk) passages via the cascade:
    headings -> paragraphs -> sentences -> lines -> char windows.

    Units are greedily packed toward CHUNK_MIN..CHUNK_MAX; every chunk
    after the first carries a ~CHUNK_OVERLAP-char prefix from the
    previous chunk's tail. Invariant: no emitted chunk exceeds
    CHUNK_MAX chars, and chunk core text is never truncated.
    """
    budget = CHUNK_MAX - CHUNK_OVERLAP
    cores: List[Tuple[str, str]] = []
    for heading, body in _split_sections(text, kind):
        units: List[str] = []
        for unit in _split_units(body, kind):
            units.extend(_split_oversize(unit, CHUNK_MAX))
        cur = ""
        for unit in units:
            cand = f"{cur}\n\n{unit}" if cur else unit
            if len(cand) <= budget:
                cur = cand
            else:
                if cur:
                    cores.append((heading, cur))
                cur = unit  # may itself exceed budget; never truncated
        if cur:
            cores.append((heading, cur))
    out: List[Tuple[str, str]] = []
    prev_core = ""
    for heading, core in cores:
        prefix = _overlap_prefix(prev_core) if out else ""
        chunk = prefix + core
        if len(chunk) > CHUNK_MAX:
            chunk = core  # core alone always fits; drop the prefix
        out.append((heading, chunk))
        prev_core = core
    return out


# --- embedders (query-time only; nothing is ever stored) --------------------

_EMBED_DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def hashed_embedder(text: str) -> List[float]:
    """Stdlib fallback embedder: hashed bag-of-words -> cosine.

    HONEST LIMIT: this is lexical-grade, not neural. It measures token
    overlap in a 256-dim hashed space; it has no semantics (synonyms do
    not match). It exists so the rerank path works with zero
    dependencies and as a stand-in until a real embedder is injected.
    Deterministic: the same text always yields the same vector.
    """
    vec = [0.0] * _EMBED_DIM
    for tok in _TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % _EMBED_DIM
        vec[idx] += 1.0 if digest[2] % 2 == 0 else -1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def make_ollama_embedder(model: str = "nomic-embed-text",
                         host: str = "http://127.0.0.1:11434",
                         timeout: float = 10.0) -> Callable[[str], List[float]]:
    """Build an embedder callable backed by a local Ollama server.

    Embeddings are computed per call, at query time, over the BM25
    shortlist only (LEANN pattern) — never at ingest, never stored.
    Any server/parse failure raises; the rerank stage treats that as
    "no rerank" and keeps the BM25 order.
    """
    url = host.rstrip("/") + "/api/embeddings"

    def embed(text: str) -> List[float]:
        req = urllib.request.Request(
            url,
            data=json.dumps({"model": model, "prompt": text}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return [float(x) for x in payload["embedding"]]

    return embed


# Module-level default; a wiring layer may set this to an embedder.
# None means: sparse BM25 order only, unless ctx provides one.
DEFAULT_EMBEDDER: Optional[Callable[[str], Sequence[float]]] = None


def _valid_vector(v: Any) -> bool:
    if not isinstance(v, (list, tuple)) or not v:
        return False
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return num / (na * nb)


def _resolve_embedder(ctx) -> Optional[Callable[[str], Sequence[float]]]:
    emb = getattr(ctx, "embedder", None)
    if callable(emb):
        return emb
    if emb == "hashed":
        return hashed_embedder
    return DEFAULT_EMBEDDER


def _rerank(query: str, items: List[Dict[str, Any]],
            embedder: Callable[[str], Sequence[float]]) -> List[Dict[str, Any]]:
    """Re-order shortlist items by cosine similarity to the query.

    All-or-nothing: any embedder exception or malformed/mismatched
    vector returns the items in their original (BM25) order, so the
    rerank stage can never degrade the sparse result. Python's sort is
    stable, so cosine ties keep BM25 order.
    """
    try:
        qv = embedder(query)
        if not _valid_vector(qv):
            return items
        scored = []
        for item in items:
            v = embedder(item["body"])
            if not _valid_vector(v) or len(v) != len(qv):
                return items
            scored.append((_cosine(qv, v), item))
    except Exception:
        return items
    scored.sort(key=lambda pair: -pair[0])
    return [item for _, item in scored]


# --- index build / sync -----------------------------------------------------

def _create_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)
    con.execute("INSERT OR REPLACE INTO meta (k, v) VALUES ('index_version', ?)",
                (INDEX_VERSION,))
    con.commit()


def _sync_index(con: sqlite3.Connection, lib: Path) -> Dict[str, int]:
    """Bring the index in step with the library, content-hash addressed.

    Unchanged files (sha256 match) are skipped; changed/new files are
    re-chunked; vanished files lose their chunks and hash row. One
    transaction: a crash mid-sync rolls back to the previous state.
    Returns per-run stats (files_seen/skipped/rechunked/removed,
    chunks_written).
    """
    stats = {"files_seen": 0, "files_skipped": 0, "files_rechunked": 0,
             "files_removed": 0, "chunks_written": 0}
    seen = set()
    try:
        for f in _source_files(lib):
            stats["files_seen"] += 1
            rel = _rel(lib, f)
            seen.add(rel)
            data = f.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            row = con.execute(
                "SELECT sha256 FROM file_hashes WHERE path = ?",
                (rel,)).fetchone()
            if row and row[0] == digest:
                stats["files_skipped"] += 1
                continue
            text = data.decode("utf-8", errors="replace")
            title = _doc_title(text, f.stem)
            kind = "py" if f.suffix == ".py" else (
                "md" if f.suffix == ".md" else "txt")
            chunks = chunk_text(text, kind)
            con.execute("DELETE FROM docs WHERE path = ?", (rel,))
            con.executemany(
                "INSERT INTO docs (path, title, section, body) "
                "VALUES (?, ?, ?, ?)",
                [(rel, title, section, body) for section, body in chunks])
            con.execute(
                "INSERT OR REPLACE INTO file_hashes (path, sha256, chunks) "
                "VALUES (?, ?, ?)", (rel, digest, len(chunks)))
            stats["files_rechunked"] += 1
            stats["chunks_written"] += len(chunks)
        for (path,) in con.execute("SELECT path FROM file_hashes").fetchall():
            if path not in seen:
                con.execute("DELETE FROM docs WHERE path = ?", (path,))
                con.execute("DELETE FROM file_hashes WHERE path = ?", (path,))
                stats["files_removed"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    return stats


def _rebuild_index(lib: Path, cache: Path) -> Tuple[sqlite3.Connection,
                                                    Dict[str, Any]]:
    """Build a fresh index in a temp file and atomically swap it in.
    The live index file is only replaced once the new one is complete;
    on any failure the old index (if any) is opened and returned."""
    tmp = cache.with_name(cache.name + ".tmp")
    try:
        if tmp.exists():
            tmp.unlink()
        con = sqlite3.connect(str(tmp))
        _create_schema(con)
        stats = _sync_index(con, lib)
        con.close()
        os.replace(tmp, cache)
        return sqlite3.connect(str(cache)), {"rebuilt": True, **stats}
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        if cache.exists():
            return sqlite3.connect(str(cache)), {"rebuilt": False,
                                                 "fallback": True}
        raise


def _ensure_index(ctx) -> Tuple[sqlite3.Connection, Dict[str, Any]]:
    """Open the index, syncing/rebuilding as needed. Returns (con, stats).

    A version-current index syncs incrementally in place; a stale or
    unreadable one is rebuilt beside itself and swapped atomically —
    the live index is never corrupted by the upgrade path.
    """
    lib = _library_dir()
    cache = _cache_path(ctx)
    if cache.exists():
        con = None
        try:
            con = sqlite3.connect(str(cache))
            row = con.execute(
                "SELECT v FROM meta WHERE k = 'index_version'").fetchone()
            if row and row[0] == INDEX_VERSION:
                stats = _sync_index(con, lib)
                return con, {"rebuilt": False, **stats}
            con.close()
            con = None
        except Exception:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return _rebuild_index(lib, cache)


def _get_index(ctx) -> sqlite3.Connection:
    con, _stats = _ensure_index(ctx)
    return con


def sync_index(ctx) -> Dict[str, Any]:
    """Public helper: ensure the index is current; return sync stats."""
    con, stats = _ensure_index(ctx)
    con.close()
    return stats


# --- search -----------------------------------------------------------------

_STOPWORDS = frozenset("""
a an and are as at be but by for from has have he her his i in is it its
me my not of on or our she so that the their them they this to was we
were will with you your each every all any some such than then there
here when where which who whom whose what why how do does did can could
should would may might must shall will being been over under again once
""".split())


def _clean_query(query: str) -> str:
    """Strip stopwords so 'go through your database each' doesn't search
    for the literal word 'each'. Returns the meaningful words joined for
    FTS5, or the original query if nothing meaningful remains."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower())
             if w not in _STOPWORDS and len(w) > 2]
    if not words:
        return query
    # FTS5 OR query: any meaningful word matches, ranked by relevance.
    return " OR ".join(words)


def _search(ctx, query: str, top_k: int = 3,
            embedder: Any = None) -> Dict[str, Any]:
    """Two-stage search. `embedder`: a callable to rerank with, False to
    force sparse-only, or None to resolve from ctx / module default."""
    top_k = max(1, min(8, int(top_k or 3)))
    lib = _library_dir()
    if not lib.is_dir():
        return {"ok": False, "code": "no_library",
                "message": "knowledge library not found"}
    try:
        con = _get_index(ctx)
    except Exception as exc:
        return {"ok": False, "code": "index_failed",
                "message": f"could not build search index: {exc}"}
    shortlist_n = min(_SHORTLIST_MAX, max(top_k * 4, 12))
    try:
        fts_query = _clean_query(query)
        rows = con.execute(
            """SELECT path, title, section, body,
                      snippet(docs, 3, '>>>', '<<<', '…', 40) AS snip
               FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?""",
            (fts_query, shortlist_n)).fetchall()
        items = [{"file": p, "title": t, "section": s, "body": b,
                  "passage": snip} for p, t, s, b, snip in rows]
    except Exception:
        # FTS5 query syntax error (e.g. unbalanced quotes) — fall back
        # to a plain LIKE search rather than failing.
        try:
            like = f"%{query}%"
            rows = con.execute(
                """SELECT path, title, section, body FROM docs
                   WHERE body LIKE ? LIMIT ?""", (like, shortlist_n)).fetchall()
        except Exception as exc:
            return {"ok": False, "code": "index_failed",
                    "message": f"search failed: {exc}"}
        items = [{"file": p, "title": t, "section": s, "body": b,
                  "passage": b.replace("\n", " ")[:400]}
                 for p, t, s, b in rows]
    if embedder is False:
        emb = None
    elif embedder is not None:
        emb = embedder
    else:
        emb = _resolve_embedder(ctx)
    if emb is not None and len(items) > 1:
        items = _rerank(query, items, emb)
    results = [{"file": it["file"], "title": it["title"],
                "section": it["section"], "passage": it["passage"]}
               for it in items[:top_k]]
    return {"ok": True, "result": {"query": query,
                                   "matches": results,
                                   "count": len(results)}}


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "knowledge_search":
        return _search(ctx, str(args.get("query", "")),
                       args.get("top_k", 3))
    return {"ok": False, "code": "unknown_tool",
            "message": f"unknown tool: {tool_name}"}
