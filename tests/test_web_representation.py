"""Tests for skills/web web_fetch_tree — Team 13 representation protocol.

Covers: manifest validity + clean static scan; the pruned indexed tree
(boilerplate/hidden/script pruning, sequential [n] handles, compound
widget expansion, frame ids, stats header); DCL handling of form values
(password never emitted, SECRET redacted, PERSONAL passes, fail-closed
withholding when DCL is unavailable); the BM25 query filter (irrelevant
subtree dropped, ancestors + section heading kept, honest outline
fallback on no match); `seen` fingerprint diff marking; the ~40k cap
with truncation marker; and handle() routing incl. legacy tools.
"""

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "web"
spec = importlib.util.spec_from_file_location(
    "web_skill", SKILL_DIR / "skill.py")
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)

from jarvis.skills.registry import SkillManifest, scan_skill  # noqa: E402

URL = "https://acme.example/"

PAGE = """<!DOCTYPE html><html><head><title>Acme Store</title>
<style>body{color:red}</style><script>var secret_script = 1;</script></head>
<body>
<nav class="main-nav"><a href="/home">Home</a><a href="/about">About</a></nav>
<header><h1>Acme Store</h1></header>
<main>
 <section id="pricing">
   <h2>Pricing plans</h2>
   <p>Our pricing plans are simple. The basic plan costs ten dollars per
   month and the pro plan costs thirty dollars per month. Every plan
   includes support and updates.</p>
   <a href="/signup">Sign up</a>
   <form action="/subscribe" method="post">
     <label>Email <input type="text" name="email" value="owner@example.com"></label>
     <input type="password" name="pw" value="hunter2">
     <input type="hidden" name="csrf" value="zzz-should-not-appear">
     <input type="text" name="api_key" value="ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa">
     <select name="plan">
       <option value="basic">Basic</option>
       <option value="pro" selected>Pro</option>
       <option value="team">Team</option>
     </select>
     <button type="submit">Subscribe</button>
   </form>
 </section>
 <section id="gardening">
   <h2>Gardening tools</h2>
   <p>Water your tomatoes every morning. Prune the roses in early spring
   and mulch the beds before winter arrives.</p>
   <a href="/garden-guide">Garden guide</a>
 </section>
 <div style="display:none"><a href="/secret">Secret link</a><p>invisible text</p></div>
 <div aria-hidden="true"><p>aria hidden text</p></div>
 <p hidden>attribute hidden text</p>
 <iframe src="https://ads.example.com/banner"></iframe>
 <div role="button" id="cta">Custom action</div>
</main>
<footer><a href="/privacy">Privacy</a><p>Copyright Acme</p></footer>
<div class="cookie-consent"><p>We use cookies on this site</p></div>
</body></html>"""


@pytest.fixture()
def fetch(monkeypatch):
    """Route the skill's downloader at the fixture page."""
    monkeypatch.setattr(web, "_download", lambda url: PAGE)
    return web


def _tree(fetch, **args):
    out = fetch.handle("web_fetch_tree", {"url": URL, **args}, None)
    assert out["ok"], out
    return out["result"]


# ---------------------------------------------------------------------------
# Manifest / scan
# ---------------------------------------------------------------------------

def test_manifest_parses_and_declares_tree_tool():
    data = json.loads((SKILL_DIR / "skill.json").read_text())
    m = SkillManifest.from_dict(data, source="skills/web/skill.json")
    tools = {t.name: t for t in m.tools}
    assert {"web_search", "web_fetch", "web_fetch_tree"} <= set(tools)
    tree = tools["web_fetch_tree"]
    assert tree.tier == 1
    assert tree.capabilities == ("net.outbound",)
    # The registry cap must not cut the 40k protocol tree at 10KB.
    assert tree.output_cap_chars >= 40_000
    params = tree.parameters["properties"]
    assert {"url", "query", "seen", "max_chars"} <= set(params)


def test_static_scan_is_clean():
    assert scan_skill(str(SKILL_DIR)) == []


# ---------------------------------------------------------------------------
# Structure: pruning, indexing, header
# ---------------------------------------------------------------------------

def test_boilerplate_and_invisible_content_pruned(fetch):
    res = _tree(fetch)
    tree = res["tree"]
    for gone in ("Home", "About", "Privacy", "Copyright Acme", "cookies",
                 "Secret link", "invisible text", "aria hidden text",
                 "attribute hidden text", "secret_script", "color:red",
                 "zzz-should-not-appear"):
        assert gone not in tree, gone
    assert res["pruned_nodes"] > 0


def test_stats_header_and_counts(fetch):
    res = _tree(fetch)
    lines = res["tree"].splitlines()
    assert lines[0] == "# Acme Store"
    assert lines[1] == f"url: {URL}"
    assert lines[2].startswith("elements: ")
    assert "truncated: no" in lines[2]
    # links: Sign up, Garden guide | inputs: email, pw, api_key |
    # selects: plan | buttons: Subscribe | generic: role=button div |
    # frames: the iframe
    assert res["links"] == 2
    assert res["inputs"] == 3
    assert res["selects"] == 1
    assert res["buttons"] == 1
    assert res["frames"] == 1
    assert res["elements"] == 2 + 3 + 1 + 1 + 1 + 1
    assert res["chars"] == len(res["tree"])
    assert res["truncated"] is False


def test_indices_are_sequential_and_match_fingerprints(fetch):
    res = _tree(fetch)
    idx = [int(m) for m in re.findall(r"(?<!\*)\[(\d+)\]", res["tree"])]
    assert idx == list(range(1, res["elements"] + 1))
    assert len(res["fingerprints"]) == res["elements"]
    assert all(len(fp) == 12 for fp in res["fingerprints"])


def test_select_expanded_in_document_order(fetch):
    tree = _tree(fetch)["tree"]
    assert '<select name="plan">' in tree
    basic = tree.index('<option value="basic">Basic</option>')
    pro = tree.index('<option value="pro" selected>Pro</option>')
    team = tree.index('<option value="team">Team</option>')
    assert basic < pro < team
    assert "</select>" in tree


def test_iframe_gets_frame_id(fetch):
    res = _tree(fetch)
    assert '<iframe frame="f1" src="https://ads.example.com/banner">' \
        in res["tree"]


def test_role_button_is_actionable(fetch):
    tree = _tree(fetch)["tree"]
    assert '<div role="button">Custom action</div>' in tree


def test_headings_and_text_present(fetch):
    tree = _tree(fetch)["tree"]
    assert "# Acme Store" in tree
    assert "## Pricing plans" in tree
    assert "## Gardening tools" in tree
    assert "Water your tomatoes" in tree


# ---------------------------------------------------------------------------
# DCL / field values
# ---------------------------------------------------------------------------

def test_password_value_never_emitted(fetch):
    tree = _tree(fetch)["tree"]
    assert "hunter2" not in tree
    assert 'value="[redacted:password]"' in tree


def test_secret_field_value_redacted_by_dcl(fetch):
    res = _tree(fetch)
    assert "ghp_" not in res["tree"]
    assert "[REDACTED:SECRET]" in res["tree"]
    assert res["values_redacted"] >= 2  # password + api key
    assert res["dcl"] == "on"


def test_personal_value_passes_through(fetch):
    # DCL doctrine: PERSONAL (an email) is not span-redacted.
    tree = _tree(fetch)["tree"]
    assert 'value="owner@example.com"' in tree


def test_values_withheld_when_dcl_unavailable(fetch, monkeypatch):
    monkeypatch.setattr(web, "_DCL", None)
    res = _tree(fetch)
    assert res["dcl"] == "off"
    assert "owner@example.com" not in res["tree"]
    assert "[withheld:dcl-unavailable]" in res["tree"]
    assert "hunter2" not in res["tree"]  # passwords: still never


# ---------------------------------------------------------------------------
# BM25 query filter
# ---------------------------------------------------------------------------

def test_query_filter_keeps_match_ancestors_and_heading(fetch):
    res = _tree(fetch, query="pricing plans cost per month")
    tree = res["tree"]
    assert res["matched_blocks"] >= 1
    assert "pricing plans are simple" in tree
    assert "## Pricing plans" in tree        # the block's section heading
    # The irrelevant subtree is gone entirely.
    assert "Gardening" not in tree
    assert "tomatoes" not in tree
    assert "Garden guide" not in tree


def test_query_filter_no_match_falls_back_to_outline(fetch):
    res = _tree(fetch, query="quantum entanglement lecture")
    assert res["matched_blocks"] == 0
    tree = res["tree"]
    assert "no content blocks matched" in tree
    assert "## Pricing plans" in tree and "## Gardening tools" in tree
    assert "tomatoes" not in tree            # outline = headings only
    assert "Water your" not in tree


# ---------------------------------------------------------------------------
# seen / new-node marks
# ---------------------------------------------------------------------------

def test_new_elements_marked_against_seen(fetch, monkeypatch):
    first = _tree(fetch)
    assert first["new_count"] is None       # no seen -> no marking
    assert "*" not in first["tree"].split("---", 1)[1]

    page2 = PAGE.replace("</main>",
                         '<button id="fresh">Fresh action</button></main>')
    monkeypatch.setattr(web, "_download", lambda url: page2)
    second = _tree(fetch, seen=first["fingerprints"])
    assert second["new_count"] == 1
    starred = [ln for ln in second["tree"].splitlines() if ln.strip().startswith("*[")]
    assert len(starred) == 1 and "Fresh action" in starred[0]
    assert "new_since_last_fetch: 1" in second["tree"]


def test_fingerprints_stable_across_identical_fetches(fetch):
    a = _tree(fetch)
    b = _tree(fetch)
    assert a["fingerprints"] == b["fingerprints"]
    again = _tree(fetch, seen=a["fingerprints"])
    assert again["new_count"] == 0


# ---------------------------------------------------------------------------
# Cap / truncation
# ---------------------------------------------------------------------------

def test_tree_cap_and_truncation_marker(monkeypatch):
    big = "<html><head><title>Big</title></head><body>" + "".join(
        f"<section><h2>Section {i}</h2><p>{'lorem ipsum dolor sit amet ' * 8}"
        f"unique{i}</p></section>" for i in range(300)) + "</body></html>"
    monkeypatch.setattr(web, "_download", lambda url: big)
    res = _tree(web)
    assert res["truncated"] is True
    assert len(res["tree"]) <= web.TREE_CAP_CHARS
    assert "tree truncated" in res["tree"]
    assert "truncated: yes" in res["tree"]


def test_max_chars_is_clamped_to_protocol_cap(fetch):
    res = _tree(fetch, max_chars=10 ** 9)
    assert len(res["tree"]) <= web.TREE_CAP_CHARS


# ---------------------------------------------------------------------------
# handle() routing / errors / legacy tools untouched
# ---------------------------------------------------------------------------

def test_bad_url_and_unknown_tool(fetch):
    out = fetch.handle("web_fetch_tree", {"url": "ftp://x"}, None)
    assert out["ok"] is False and out["code"] == "bad_url"
    out = fetch.handle("nope", {}, None)
    assert out["ok"] is False and out["code"] == "unknown_tool"


def test_fetch_failure_maps_to_fetch_failed(monkeypatch):
    def boom(url):
        raise OSError("no route")
    monkeypatch.setattr(web, "_download", boom)
    out = web.handle("web_fetch_tree", {"url": URL}, None)
    assert out["ok"] is False and out["code"] == "fetch_failed"


def test_legacy_web_fetch_still_works(fetch):
    out = fetch.handle("web_fetch", {"url": URL}, None)
    assert out["ok"] is True
    assert "Pricing plans" in out["result"]["text"]
    assert out["result"]["url"] == URL
