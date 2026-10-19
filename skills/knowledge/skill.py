"""Knowledge skill: full-text search over Ovi's research library.

The library (knowledge/*.md, ~2MB) ships inside the repo. Search is
sqlite FTS5, stdlib only. The index builds lazily on first query and is
cached as a sqlite file in the data dir (rebuilds when a source file is
newer than the cache).
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

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

_INDEX_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(
    path, title, body, tokenize='porter');
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


def _fingerprint(lib: Path) -> str:
    h = hashlib.sha256()
    for f in _source_files(lib):
        st = f.stat()
        h.update(f"{f.name}:{st.st_size}:{st.st_mtime_ns}".encode())
    return h.hexdigest()


def _build_index(lib: Path, cache: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(cache))
    con.execute("DROP TABLE IF EXISTS docs")
    con.execute("DROP TABLE IF EXISTS meta")
    con.execute(_INDEX_SCHEMA)
    con.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    for f in _source_files(lib):
        text = f.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        title = f.stem
        for line in lines[:5]:
            if line.startswith("#"):
                title = line.lstrip("# ").strip()
                break
        # Prefix path with source dir for clarity.
        try:
            rel = str(f.relative_to(lib))
        except ValueError:
            rel = f.name
        con.execute("INSERT INTO docs (path, title, body) VALUES (?, ?, ?)",
                    (rel, title, text))
    con.execute("INSERT INTO meta (k, v) VALUES ('fingerprint', ?)",
                (_fingerprint(lib),))
    con.commit()
    return con


def _get_index(ctx) -> sqlite3.Connection:
    lib = _library_dir()
    cache = _cache_path(ctx)
    want = _fingerprint(lib)
    if cache.exists():
        try:
            con = sqlite3.connect(str(cache))
            row = con.execute(
                "SELECT v FROM meta WHERE k='fingerprint'").fetchone()
            if row and row[0] == want:
                return con
            con.close()
        except Exception:
            pass
    return _build_index(lib, cache)


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


def _search(ctx, query: str, top_k: int = 3) -> Dict[str, Any]:
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
    try:
        fts_query = _clean_query(query)
        rows = con.execute(
            """SELECT path, title,
                      snippet(docs, 2, '>>>', '<<<', '…', 40) AS snip,
                      rank
               FROM docs WHERE docs MATCH ? ORDER BY rank LIMIT ?""",
            (fts_query, top_k)).fetchall()
    except Exception:
        # FTS5 query syntax error (e.g. unbalanced quotes) — fall back
        # to a plain LIKE search rather than failing.
        like = f"%{query}%"
        rows = con.execute(
            """SELECT path, title, substr(body, 1, 400), 0 FROM docs
               WHERE body LIKE ? LIMIT ?""", (like, top_k)).fetchall()
        rows = [(p, t, s.replace("\n", " ")[:400], r)
                for p, t, s, r in rows]
    results = [{"file": p, "title": t, "passage": s} for p, t, s, _ in rows]
    return {"ok": True, "result": {"query": query,
                                  "matches": results,
                                  "count": len(results)}}


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "knowledge_search":
        return _search(ctx, str(args.get("query", "")),
                       args.get("top_k", 3))
    return {"ok": False, "code": "unknown_tool",
            "message": f"unknown tool: {tool_name}"}
