"""Tests for the knowledge skill RAG upgrade (Team 21 steals).

Covers: the chunking cascade (headings -> paragraphs -> sentences ->
lines -> char windows, 256-512 chars, ~25 overlap), content-hash
ingest skip, versioned index upgrade that never corrupts the live
index, and LEANN-style on-demand embedding rerank over the BM25
shortlist (with the never-worse-than-BM25 fallback guarantee).

Stdlib only; hermetic — synthetic libraries live in tmp_path, and one
end-to-end test runs against the real repo corpus.
"""
from __future__ import annotations

import importlib.util
import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SKILL_PATH = REPO / "skills" / "knowledge" / "skill.py"

spec = importlib.util.spec_from_file_location("knowledge_skill", SKILL_PATH)
know = importlib.util.module_from_spec(spec)
sys.modules["knowledge_skill"] = know
spec.loader.exec_module(know)


# --- fixtures ----------------------------------------------------------------

class Ctx:
    """Minimal SkillContext stand-in: jail_dir (+ optional embedder)."""

    def __init__(self, jail: Path, embedder=None):
        self.jail_dir = str(jail)
        if embedder is not None:
            self.embedder = embedder


def _make_lib(tmp_path: Path, files: dict[str, str]) -> Path:
    lib = tmp_path / "lib"
    (lib / "knowledge").mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (lib / "knowledge" / name).write_text(text, encoding="utf-8")
    return lib


@pytest.fixture()
def lib_env(tmp_path, monkeypatch):
    """Returns (make_lib, ctx_factory) bound to one tmp_path."""
    def _setup(files):
        lib = _make_lib(tmp_path, files)
        monkeypatch.setattr(know, "_library_dir", lambda: lib)
        ctx = Ctx(tmp_path / "jail")
        return lib, ctx
    return _setup


def _files(result):
    return [m["file"] for m in result["result"]["matches"]]


# --- chunking cascade ----------------------------------------------------------

def test_chunk_splits_on_headings_with_sections():
    text = ("# Doc\n\nIntro words here.\n\n"
            "## Alpha Section\n\n" + "Alpha content sentence. " * 30 + "\n\n"
            "## Beta Section\n\n" + "Beta zebra topic sentence. " * 30)
    chunks = know.chunk_text(text, "md")
    sections = {s for s, _ in chunks}
    assert "Alpha Section" in sections and "Beta Section" in sections
    beta = [c for s, c in chunks if s == "Beta Section"]
    assert beta and all("zebra" in c for c in beta)


def test_chunk_sizes_within_bounds_and_mostly_at_floor():
    sentence = "The quick brown fox jumps over the lazy dog again. "
    text = "# Big\n\n" + sentence * 120  # ~6000 chars, one paragraph
    chunks = know.chunk_text(text, "md")
    bodies = [c for _, c in chunks]
    assert len(bodies) >= 10
    assert all(len(c) <= know.CHUNK_MAX for c in bodies)
    # Every chunk but the document tail reaches the target floor.
    assert all(len(c) >= know.CHUNK_MIN for c in bodies[:-1])


def test_chunk_overlap_carries_previous_tail():
    sentence = "Marigold zephyr quill juniper velvet cinder topaz. "
    text = "# Doc\n\n" + sentence * 60
    chunks = [c for _, c in know.chunk_text(text, "md")]
    assert len(chunks) >= 3
    for prev, nxt in zip(chunks, chunks[1:]):
        first_word = nxt.split()[0]
        assert first_word in prev[-(know.CHUNK_OVERLAP + 8):]


def test_chunk_packs_small_paragraphs():
    paras = [f"Short note number {i} about topic {i}." for i in range(20)]
    text = "# Notes\n\n" + "\n\n".join(paras)
    chunks = know.chunk_text(text, "md")
    bodies = [c for _, c in chunks]
    # 20 tiny paragraphs must pack into a couple of chunks, not 20.
    assert len(bodies) <= 3
    assert all(len(c) >= know.CHUNK_MIN for c in bodies[:-1])


def test_chunk_sentence_split_loses_nothing():
    sentences = [f"Sentence {i} explains concept {i} in detail."
                 for i in range(40)]
    text = "# Doc\n\n" + " ".join(sentences)  # one giant paragraph
    chunks = [c for _, c in know.chunk_text(text, "md")]
    assert all(len(c) <= know.CHUNK_MAX for c in chunks)
    joined = "\n".join(chunks)
    for s in sentences:
        assert s in joined


def test_chunk_giant_token_hard_windows():
    text = "x" * 5000
    chunks = [c for _, c in know.chunk_text(text, "txt")]
    assert len(chunks) >= 10
    assert all(len(c) <= know.CHUNK_MAX for c in chunks)
    assert chunks[0] == text[:know.CHUNK_MAX]
    # Only x's, plus at most the single overlap-prefix separator space.
    assert all(set(c) <= {"x", " "} and c.count(" ") <= 1 for c in chunks)


def test_chunk_python_def_boundaries():
    alpha = "def alpha():\n    " + "# alpha work\n    ".join(
        f"x{i} = {i}\n    " for i in range(30)) + "return 'alpha-marker'\n"
    beta = "def beta():\n    " + "# beta work\n    ".join(
        f"y{i} = {i}\n    " for i in range(30)) + "return 'beta-marker'\n"
    chunks = [c for _, c in know.chunk_text(alpha + "\n\n" + beta, "py")]
    alpha_chunks = [c for c in chunks if "alpha-marker" in c]
    beta_chunks = [c for c in chunks if "beta-marker" in c]
    assert alpha_chunks and beta_chunks
    assert not any("beta-marker" in c for c in alpha_chunks)


# --- content-hash ingest skip ---------------------------------------------------

def test_hash_skip_second_sync_rechunks_nothing(lib_env):
    _lib, ctx = lib_env({
        "a.md": "# A\n\n" + "Alpha fact about photon routing. " * 10,
        "b.md": "# B\n\n" + "Beta fact about cache locality. " * 10,
        "c.md": "# C\n\n" + "Gamma fact about wake words. " * 10,
    })
    first = know.sync_index(ctx)
    assert first["files_seen"] == 3 and first["files_rechunked"] == 3
    assert first["chunks_written"] >= 3
    second = know.sync_index(ctx)
    assert second["files_rechunked"] == 0
    assert second["files_skipped"] == 3
    assert second["chunks_written"] == 0


def test_hash_skip_changed_file_rechunked_alone(lib_env):
    lib, ctx = lib_env({
        "a.md": "# A\n\n" + "Alpha fact about photon routing. " * 10,
        "b.md": "# B\n\n" + "Beta fact about cache locality. " * 10,
    })
    know.sync_index(ctx)
    (lib / "knowledge" / "b.md").write_text(
        "# B\n\nBeta revised: now about quantum tunnelling diodes. " * 5,
        encoding="utf-8")
    stats = know.sync_index(ctx)
    assert stats["files_rechunked"] == 1 and stats["files_skipped"] == 1
    res = know.handle("knowledge_search", {"query": "quantum tunnelling"},
                      ctx)
    assert res["ok"] and _files(res) == ["knowledge/b.md"]


def test_removed_file_dropped_from_index(lib_env):
    lib, ctx = lib_env({
        "a.md": "# A\n\n" + "Alpha fact about photon routing. " * 10,
        "gone.md": "# G\n\n" + "Unique xylophone zebra content. " * 10,
    })
    know.sync_index(ctx)
    (lib / "knowledge" / "gone.md").unlink()
    stats = know.sync_index(ctx)
    assert stats["files_removed"] == 1
    res = know.handle("knowledge_search", {"query": "xylophone zebra"}, ctx)
    assert res["ok"] and res["result"]["count"] == 0


# --- versioned index --------------------------------------------------------------

_V1_SCHEMA = """
CREATE VIRTUAL TABLE docs USING fts5(path, title, body, tokenize='porter');
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
"""


def _write_v1_index(cache: Path, body: str) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(cache))
    con.executescript(_V1_SCHEMA)
    con.execute("INSERT INTO docs (path, title, body) VALUES (?, ?, ?)",
                ("knowledge/old.md", "Old Doc", body))
    con.execute("INSERT INTO meta (k, v) VALUES ('fingerprint', 'stale')")
    con.commit()
    con.close()


def test_v1_index_upgraded_in_place(lib_env):
    lib, ctx = lib_env({
        "new.md": "# New\n\n" + "Fresh content about obsidian mirrors. " * 8,
    })
    cache = know._cache_path(ctx)
    body = "Legacy whole-file body about obsidian mirrors and old indexes."
    _write_v1_index(cache, body)
    res = know.handle("knowledge_search", {"query": "obsidian mirrors"}, ctx)
    assert res["ok"] and res["result"]["count"] >= 1
    # Index is now v2: version stamped, docs gained the section column,
    # and the synthetic library (not the fake v1 row) is what got indexed.
    con = sqlite3.connect(str(cache))
    version = con.execute(
        "SELECT v FROM meta WHERE k='index_version'").fetchone()[0]
    cols = [r[1] for r in con.execute("PRAGMA table_info(docs)")]
    paths = {r[0] for r in con.execute("SELECT DISTINCT path FROM docs")}
    con.close()
    assert version == know.INDEX_VERSION
    assert "section" in cols
    assert paths == {"knowledge/new.md"}


def test_failed_rebuild_never_corrupts_live_index(lib_env, monkeypatch):
    _lib, ctx = lib_env({
        "a.md": "# A\n\n" + "Durable content about granite anchors. " * 8,
    })
    assert know.sync_index(ctx)["files_rechunked"] == 1
    # Force the stale-version path, then break the rebuild.
    cache = know._cache_path(ctx)
    con = sqlite3.connect(str(cache))
    con.execute("UPDATE meta SET v='1' WHERE k='index_version'")
    con.commit()
    con.close()

    def boom(*a, **k):
        raise RuntimeError("chunker exploded")

    monkeypatch.setattr(know, "chunk_text", boom)
    res = know.handle("knowledge_search", {"query": "granite anchors"}, ctx)
    assert res["ok"] and res["result"]["count"] >= 1
    assert _files(res) == ["knowledge/a.md"]


# --- rerank -----------------------------------------------------------------------

_A_DOC = ("# Wake\n\nThe wake word listener detects the spoken name "
          "Jarvis locally on the device. Saying the name aloud wakes "
          "the butler instantly, hands free.")
_B_DOC = ("# Names\n\n" + "name name name butler hear name butler hear "
          "name hear butler name. " * 6)


_QUERY = "how does the butler hear his name"


def _fake_embedder(text: str):
    """Semantic oracle: wake-word content and the query share a vector;
    everything else is orthogonal."""
    if text == _QUERY or "wake word" in text:
        return [1.0, 0.0]
    return [0.0, 1.0]


@pytest.fixture()
def rerank_env(lib_env):
    return lib_env({"wake.md": _A_DOC, "names.md": _B_DOC})


def test_bm25_alone_ranks_stuffed_doc_first(rerank_env):
    _lib, ctx = rerank_env
    res = know._search(ctx, _QUERY, 2,
                       embedder=False)
    assert res["ok"]
    assert _files(res)[0] == "knowledge/names.md"


def test_rerank_promotes_semantic_match(rerank_env):
    _lib, ctx = rerank_env
    res = know._search(ctx, _QUERY, 2,
                       embedder=_fake_embedder)
    assert res["ok"]
    assert _files(res)[0] == "knowledge/wake.md"


def test_rerank_embedder_error_falls_back_to_bm25(rerank_env):
    _lib, ctx = rerank_env

    def exploding(text):
        raise RuntimeError("embedder down")

    plain = know._search(ctx, _QUERY, 2,
                         embedder=False)
    degraded = know._search(ctx, _QUERY, 2,
                            embedder=exploding)
    assert degraded["ok"]
    assert _files(degraded) == _files(plain)


def test_rerank_malformed_vectors_fall_back_to_bm25(rerank_env):
    _lib, ctx = rerank_env
    plain = know._search(ctx, _QUERY, 2,
                         embedder=False)
    bad_embedders = [
        lambda text: None,                       # no vector at all
        lambda text: [float("nan"), 0.0],        # non-finite
        lambda text: [1.0],                      # query dim != chunk dim
        lambda text: "not-a-vector",             # wrong type
    ]
    for bad in bad_embedders:
        res = know._search(ctx, _QUERY, 2,
                           embedder=bad)
        assert res["ok"]
        assert _files(res) == _files(plain)


def test_hashed_embedder_properties():
    v1 = know.hashed_embedder("wake word detection")
    v2 = know.hashed_embedder("wake word detection")
    assert v1 == v2  # deterministic
    assert len(v1) == 256
    assert math.sqrt(sum(x * x for x in v1)) == pytest.approx(1.0)
    shared = know._cosine(know.hashed_embedder("wake word"),
                          know.hashed_embedder("wake word listener"))
    unrelated = know._cosine(know.hashed_embedder("wake word"),
                             know.hashed_embedder("banana smoothie recipe"))
    assert shared > unrelated


def test_ctx_hashed_embedder_end_to_end(rerank_env, monkeypatch):
    lib, _ctx0 = rerank_env
    ctx = Ctx(Path(_ctx0.jail_dir), embedder="hashed")
    res = know.handle("knowledge_search",
                      {"query": "butler hear name", "top_k": 2}, ctx)
    assert res["ok"] and res["result"]["count"] == 2


def test_ollama_embedder_parses_and_degrades(monkeypatch):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"embedding": [0.5, 0.25]}).encode()

    monkeypatch.setattr(know.urllib.request, "urlopen",
                        lambda req, timeout=None: FakeResp())
    emb = know.make_ollama_embedder()
    assert emb("anything") == [0.5, 0.25]

    def down(req, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(know.urllib.request, "urlopen", down)
    with pytest.raises(OSError):
        emb("anything")  # raises -> rerank layer falls back to BM25


def test_embeddings_are_never_stored(lib_env):
    _lib, ctx = lib_env({"wake.md": _A_DOC, "names.md": _B_DOC})
    res = know._search(ctx, "butler hear name", 2, embedder=_fake_embedder)
    assert res["ok"]
    con = sqlite3.connect(str(know._cache_path(ctx)))
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    ddl = " ".join(r[0] or "" for r in con.execute(
        "SELECT sql FROM sqlite_master"))
    con.close()
    assert not any("embed" in t or "vector" in t for t in tables)
    assert "embedding" not in ddl.lower()


# --- contract + real corpus ---------------------------------------------------------

def test_tool_contract_unchanged(lib_env):
    _lib, ctx = lib_env({"a.md": "# A\n\nAlpha photon routing content. " * 5})
    res = know.handle("knowledge_search", {"query": "photon routing"}, ctx)
    assert res["ok"]
    match = res["result"]["matches"][0]
    assert {"file", "title", "passage", "section"} <= set(match)
    bad = know.handle("nope", {}, ctx)
    assert bad["ok"] is False and bad["code"] == "unknown_tool"


def test_end_to_end_real_library(tmp_path):
    # No _library_dir patch: the real repo corpus (~115 sources).
    ctx = Ctx(tmp_path / "jail")
    res = know.handle("knowledge_search",
                      {"query": "wake word", "top_k": 3}, ctx)
    assert res["ok"] and res["result"]["count"] >= 1
    for m in res["result"]["matches"]:
        assert m["file"] and m["passage"]
    stats = know.sync_index(ctx)
    assert stats["files_rechunked"] == 0  # second pass: all hash-skipped
    assert stats["files_skipped"] == stats["files_seen"] > 50
