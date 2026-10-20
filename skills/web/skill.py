"""Web skill: internet search + page fetching. Stdlib only, no API keys.

web_search uses DuckDuckGo's HTML endpoint (no key, no signup).
web_fetch pulls readable text from a URL.
web_fetch_tree pulls a page as a pruned, indexed element tree — the
Team 13 representation protocol (see the block below): actionable
elements numbered [n], compound widgets expanded, boilerplate/hidden
content pruned, ~40k-char cap, optional BM25 query filter, `*` marks
for elements new since a previous fetch. Form-field values are
DCL-scanned before they enter the tree (passwords never emitted).

All web content is UNTRUSTED — the gate wraps it, the brain must never
obey instructions found in pages.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import math
import re
import urllib.parse
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

SKILL_NAME = "web"

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web. Titles, URLs, snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "max_results": {"type": "integer",
                                "description": "Max results (default 5, max 10)"},
            },
            "required": ["query"],
        },
        "tier": 1,
        "capabilities": ["net.outbound"],
    },
    {
        "name": "web_fetch",
        "description": "Fetch a page's readable text.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
        "tier": 1,
        "capabilities": ["net.outbound"],
    },
    {
        "name": "web_fetch_tree",
        # NOTE: keep this description SHORT — the brain's system prompt
        # carries one line per tool and sits within ~20 tokens of its
        # 4000-token budget. The full story lives in SKILL.md and in
        # the parameter descriptions below (neither enters the prompt).
        "description": "Fetch a page as an indexed element tree.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
                "query": {"type": "string",
                          "description": "Optional BM25 relevance filter"},
                "seen": {"type": "array", "items": {"type": "string"},
                         "description": "Element fingerprints from a "
                                        "previous fetch of this page"},
                "max_chars": {"type": "integer",
                              "description": "Tree cap (default/max 40000)"},
            },
            "required": ["url"],
        },
        "tier": 1,
        "capabilities": ["net.outbound"],
    },
]

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JARVIS/2.0"}


def _search(query: str, max_results: int = 5) -> Dict[str, Any]:
    max_results = max(1, min(10, int(max_results or 5)))
    params = urllib.parse.urlencode({"q": query})
    # lite.duckduckgo.com: less bot protection than the HTML endpoint.
    req = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/?{params}", headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception as exc:
        return {"ok": False, "code": "search_failed",
                "message": f"search failed: {exc}"}
    results = []
    # Lite format: plain <a href="...">Title</a> links; result URLs are
    # wrapped: //duckduckgo.com/l/?uddg=<encoded-real-url>.
    for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]{10,120})</a>', page):
        raw_url, title = m.group(1), _html.unescape(m.group(2)).strip()
        url = raw_url
        if "uddg=" in raw_url:
            url = urllib.parse.unquote(
                raw_url.split("uddg=", 1)[1].split("&")[0])
        if not url.startswith("http") or not title:
            continue
        # Skip DuckDuckGo's own navigation links.
        if "duckduckgo.com" in url:
            continue
        results.append({"title": title, "url": url, "snippet": ""})
        if len(results) >= max_results:
            break
    return {"ok": True, "result": {"query": query, "results": results,
                                  "count": len(results)}}


def _download(url: str) -> str:
    """Raw page download shared by web_fetch and web_fetch_tree.
    500KB cap, UTF-8 with replacement. Raises on any network error;
    callers map the exception to their own error dict."""
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(500_000).decode("utf-8", "replace")


def _fetch(url: str) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "code": "bad_url",
                "message": "URL must start with http(s)://"}
    try:
        raw = _download(url)
    except Exception as exc:
        return {"ok": False, "code": "fetch_failed",
                "message": f"fetch failed: {exc}"}
    # Strip scripts/styles, then tags; collapse whitespace.
    text = re.sub(r"(?s)<script.*?</script>", " ", raw)
    text = re.sub(r"(?s)<style.*?</style>", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    # Cap at ~8000 chars so it fits the brain's context.
    if len(text) > 8000:
        text = text[:8000] + "\n…[truncated]"
    return {"ok": True, "result": {"url": url, "text": text,
                                  "chars": len(text)}}


# ===========================================================================
# web_fetch_tree — Team 13 representation protocol, tier (a): static HTML
# via html.parser. (Tier (b) — the owner's real Chrome over CDP — can
# reuse this exact render format; the protocol is driver-agnostic.)
#
# Protocol elements (browser-use reference design, team13-browser.md §1):
#   * pruned tree: script/style/invisible/boilerplate subtrees dropped
#   * every actionable element gets a stable per-page handle [n]
#   * compound widgets expanded inline (select -> its options)
#   * page-stats header, ~40k-char hard cap with honest truncation mark
#   * elements new since a previous fetch are prefixed * (stateless:
#     the caller passes the previous fetch's fingerprints as `seen`)
#   * iframes get frame ids (f1, f2, ...); elements inside frame fN are
#     addressed [fN:k] — reserved for the CDP tier; the static tier
#     cannot read frame documents, so it renders the <iframe> itself.
#
# Form-field values are the one place page data routinely hides
# credentials, so they are DCL-scanned before rendering (the system
# skill's clipboard precedent): password values are NEVER emitted;
# other values pass through DCL redact() (SECRET/SENSITIVE spans are
# replaced, PERSONAL/PUBLIC pass — DCL's own doctrine). If DCL is not
# importable in this context, values are withheld entirely (fail
# closed) and the stats say so. Hrefs are replaced only when DCL
# classifies the whole URL SECRET (signed/token URLs); page text is
# NOT scanned here — the gate wraps all tool output already.
# ===========================================================================

TREE_CAP_CHARS = 40_000        # protocol cap (browser-use: 40_000)
_TREE_MIN_CHARS = 500
_MAX_INDEXED = 1_500           # beyond this, elements render unindexed
_TEXT_CAP = 400                # per-text-node render cap
_VALUE_CAP = 120               # per-field-value render cap
_MAX_OPTIONS = 50              # per-<select> option lines
_BM25_K1 = 1.5
_BM25_B = 0.75
_BM25_THRESHOLD = 1.0          # crawl4ai BM25ContentFilter's default

try:  # DCL import: system skill precedent (jarvis.dcl is importable
    from jarvis.dcl import DCL as _DCL_CLS  # from skill context).
    _DCL = _DCL_CLS()
except Exception:  # pragma: no cover — jarvis package not importable
    _DCL = None

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
# Subtrees that never carry perceivable content.
_DROP_TAGS = {"script", "style", "noscript", "template", "svg", "head",
              "link", "meta", "base"}
# Boilerplate by tag (browser-use prunes non-content; crawl4ai prunes
# boilerplate): navigation, page footer, sidebars.
_BOILER_TAGS = {"nav", "footer", "aside"}
# Boilerplate by class/id naming — consent banners, popups, share bars.
_BOILER_RE = re.compile(
    r"cookie|consent|newsletter|popup|modal|sidebar|social[-_]?share|"
    r"advert|promo[-_]?banner", re.I)
# Block-level tags: BM25 scoring units are the INNERMOST of these.
_BLOCK_TAGS = {"address", "article", "blockquote", "div", "dl", "fieldset",
               "figure", "form", "li", "main", "ol", "p", "pre", "section",
               "table", "td", "tr", "ul"}
_ACTIONABLE_ROLES = {"button", "link", "checkbox", "radio", "tab",
                     "menuitem", "switch", "textbox", "combobox"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "it",
              "for", "on", "at", "by", "with", "as", "are", "was", "be",
              "this", "that", "from"}


class _El:
    """One parsed element. children is a list of _El | str, in order."""
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: Dict[str, str],
                 parent: Optional["_El"]) -> None:
        self.tag = tag
        self.attrs = attrs
        self.children: List[Any] = []
        self.parent = parent


def _style_hides(style: str) -> bool:
    flat = re.sub(r"\s+", "", style.lower())
    return "display:none" in flat or "visibility:hidden" in flat


class _TreeBuilder(HTMLParser):
    """html.parser -> light DOM, with pruning applied during the parse.

    A subtree is dropped (and counted in .pruned) when its root is:
    a _DROP_TAGS member, a boilerplate tag/class, or invisible
    (hidden attr, aria-hidden=true, display:none / visibility:hidden
    style, or an input type=hidden). The <title> text is captured
    even though <head> itself is dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self._stack: List[_El] = [self.root]
        self._skip: List[str] = []   # tags of the subtree being dropped
        self.pruned = 0
        self.title = ""
        self._in_title = False
        self._title_parts: List[str] = []

    def _drops(self, tag: str, attrs: Dict[str, str]) -> bool:
        if tag in _DROP_TAGS or tag in _BOILER_TAGS:
            return True
        if "hidden" in attrs:
            return True
        if attrs.get("aria-hidden", "").lower() == "true":
            return True
        if _style_hides(attrs.get("style", "")):
            return True
        if tag == "input" and attrs.get("type", "text").lower() == "hidden":
            return True
        ident = attrs.get("class", "") + " " + attrs.get("id", "")
        return bool(_BOILER_RE.search(ident))

    def handle_starttag(self, tag: str, attrs_list) -> None:
        if tag == "title":
            self._in_title = True
            return
        attrs = {k: (v if v is not None else "") for k, v in attrs_list}
        if self._skip:
            self.pruned += 1
            if tag not in _VOID_TAGS:
                self._skip.append(tag)
            return
        if self._drops(tag, attrs):
            self.pruned += 1
            if tag not in _VOID_TAGS:
                self._skip.append(tag)
            return
        el = _El(tag, attrs, self._stack[-1])
        self._stack[-1].children.append(el)
        if tag == "iframe":
            # Leaf: an iframe's fallback body is not the frame document.
            self._skip.append("iframe")
            return
        if tag not in _VOID_TAGS:
            self._stack.append(el)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
            self.title = " ".join("".join(self._title_parts).split())
            return
        if self._skip:
            if tag in self._skip:
                while self._skip:
                    if self._skip.pop() == tag:
                        break
            return
        # Pop to the nearest matching open element (tolerates misnesting).
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip:
            return
        cur = self._stack[-1]
        if cur.children and isinstance(cur.children[-1], str):
            cur.children[-1] += data
        else:
            cur.children.append(data)


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------

def _iter_text(el: _El) -> List[str]:
    out: List[str] = []
    stack = list(reversed(el.children))
    while stack:
        ch = stack.pop()
        if isinstance(ch, str):
            out.append(ch)
        else:
            stack.extend(reversed(ch.children))
    return out


def _text_of(el: _El) -> str:
    return " ".join(" ".join(_iter_text(el)).split())


def _own_text(el: _El) -> str:
    return " ".join(
        " ".join(c for c in el.children if isinstance(c, str)).split())


def _descendants(el: _El) -> List[_El]:
    """All descendant elements in document (pre-order) order."""
    out: List[_El] = []
    stack = list(reversed(el.children))
    while stack:
        ch = stack.pop()
        if isinstance(ch, _El):
            out.append(ch)
            stack.extend(reversed(ch.children))
    return out


def _is_actionable(el: _El) -> bool:
    """browser-use's is_interactive heuristics, minus what a static
    parse cannot know (CDP click listeners, cursor style)."""
    tag = el.tag
    if tag == "a":
        return "href" in el.attrs
    if tag in ("button", "select", "textarea"):
        return True
    if tag == "input":
        return el.attrs.get("type", "text").lower() != "hidden"
    if el.attrs.get("role", "").lower() in _ACTIONABLE_ROLES:
        return True
    return "onclick" in el.attrs


def _prune_empty(el: _El) -> bool:
    """Drop render-nothing subtrees (wrapper-only chains, whitespace
    text, decorative images). Returns True if el keeps any content."""
    kept: List[Any] = []
    for ch in el.children:
        if isinstance(ch, str):
            if ch.strip():
                kept.append(ch)
        elif _prune_empty(ch):
            kept.append(ch)
    el.children = kept
    if _is_actionable(el):
        return True
    if el.tag == "iframe":
        return True  # the frame element itself is content (its document
        # is a separate fetch — see the frame-id note in _render)
    if el.tag == "img":
        return bool(el.attrs.get("alt", "").strip())
    return bool(kept)


def _fingerprint(el: _El) -> str:
    """Value-identity of an element: tag + salient attrs + visible
    text. Two identical elements share a fingerprint (documented:
    `seen` marking is by value, not by node instance)."""
    a = el.attrs
    salient = "|".join(a.get(k, "") for k in
                       ("href", "name", "type", "id", "role"))
    desc = f"{el.tag}|{salient}|{_text_of(el)[:80]}"
    return hashlib.sha256(desc.encode("utf-8", "replace")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Value safety (DCL)
# ---------------------------------------------------------------------------

def _safe_field_value(raw: str) -> tuple:
    """(rendered_value, was_redacted) for a form field's current value."""
    if raw == "":
        return "", False
    if _DCL is None:
        # Fail closed: no scanner in this context -> withhold values.
        return "[withheld:dcl-unavailable]", True
    redacted, _ = _DCL.redact(raw)
    return redacted, redacted != raw


def _safe_url(url: str) -> str:
    """Hrefs pass through unless DCL classes the whole URL SECRET
    (token/signed URLs — the Skyvern opaque-token concern)."""
    if not url or _DCL is None:
        return url
    try:
        from jarvis.dcl import DataClass
        cls, _ = _DCL.classify(url)
        if cls >= DataClass.SECRET:
            redacted, _ = _DCL.redact(url)
            return redacted
    except Exception:
        pass
    return url


def _clip(text: str, cap: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= cap else text[:cap] + "…"


def _attr(text: str, cap: int = _VALUE_CAP) -> str:
    return _clip(text, cap).replace('"', "'")


# ---------------------------------------------------------------------------
# BM25 query filter (crawl4ai's BM25ContentFilter pattern)
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower())
            if len(t) >= 2 and t not in _STOPWORDS]


def _innermost_blocks(root: _El) -> List[_El]:
    blocks: List[_El] = []

    def rec(el: _El) -> bool:
        self_is = el.tag in _BLOCK_TAGS
        child_has = False
        for ch in el.children:
            if isinstance(ch, _El) and rec(ch):
                child_has = True
        if self_is and not child_has:
            blocks.append(el)
        return self_is or child_has

    rec(root)
    return blocks


def _bm25_filter(root: _El, query: str):
    """Returns (keep_ids, matched_blocks). keep_ids is the render set:
    matched blocks + their descendants + their ancestors + the
    nearest preceding heading of each matched block (its label).
    When nothing scores >= threshold, the render set falls back to a
    headings outline (h1-h3 + ancestors) and matched_blocks is 0."""
    units = _innermost_blocks(root) or [root]
    docs = [Counter(_tokenize(_text_of(u))) for u in units]
    n = len(docs)
    df: Counter = Counter()
    for d in docs:
        for t in d:
            df[t] += 1
    avgdl = (sum(sum(d.values()) for d in docs) / n) or 1.0
    qterms = set(_tokenize(query))
    kept_units: List[_El] = []
    for u, d in zip(units, docs):
        dl = sum(d.values()) or 1
        score = 0.0
        for t in qterms:
            tf = d.get(t, 0)
            if not tf:
                continue
            idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
            denom = tf + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * dl / avgdl)
            score += idf * (tf * (_BM25_K1 + 1.0)) / denom
        if score >= _BM25_THRESHOLD:
            kept_units.append(u)

    keep: set = set()

    def _keep_with_context(u: _El) -> None:
        keep.add(id(u))
        for d in _descendants(u):
            keep.add(id(d))
        node = u
        while node.parent is not None:
            parent = node.parent
            keep.add(id(parent))
            # The heading that labels this branch: nearest preceding
            # heading sibling at this level.
            sibs = parent.children
            idx = sibs.index(node)
            for sib in reversed(sibs[:idx]):
                if isinstance(sib, _El) and sib.tag in _HEADING_TAGS:
                    keep.add(id(sib))
                    break
            node = parent

    if kept_units:
        for u in kept_units:
            _keep_with_context(u)
    else:
        for el in _descendants(root):
            if el.tag in ("h1", "h2", "h3"):
                keep.add(id(el))
                node = el
                while node.parent is not None:
                    node = node.parent
                    keep.add(id(node))
    return keep, len(kept_units)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

class _RenderState:
    def __init__(self, seen: Optional[set]) -> None:
        self.seen = seen
        self.records: List[Dict[str, Any]] = []
        self.frames = 0
        self.indexed = 0


def _emit(st: _RenderState, line: str, kind: Optional[str],
          fp: Optional[str], is_new: bool = False,
          redacted: bool = False) -> None:
    st.records.append({"line": line, "kind": kind, "fp": fp,
                       "new": is_new, "redacted": redacted})


def _index_prefix(st: _RenderState, fp: str):
    """Assign the next [n] handle. Returns (prefix, is_new)."""
    is_new = st.seen is not None and fp not in st.seen
    if st.indexed >= _MAX_INDEXED:
        return "", is_new
    st.indexed += 1
    return ("*" if is_new else "") + f"[{st.indexed}]", is_new


def _emit_actionable(st: _RenderState, el: _El, indent: str) -> None:
    fp = _fingerprint(el)
    prefix, is_new = _index_prefix(st, fp)
    tag = el.tag
    a = el.attrs
    redacted = False
    if tag == "a":
        text = _text_of(el)
        if not text:  # image link: fall back to the image's alt
            for d in _descendants(el):
                if d.tag == "img" and d.attrs.get("alt", "").strip():
                    text = d.attrs["alt"]
                    break
        line = (f'{indent}{prefix}<a href="{_attr(_safe_url(a.get("href", "")), 300)}">'
                f'{_clip(text, 120)}</a>')
        _emit(st, line, "link", fp, is_new)
    elif tag == "button":
        line = f"{indent}{prefix}<button>{_clip(_text_of(el), 120)}</button>"
        _emit(st, line, "button", fp, is_new)
    elif tag == "input":
        itype = (a.get("type") or "text").lower()
        parts = [f'type="{_attr(itype, 30)}"']
        if a.get("name"):
            parts.append(f'name="{_attr(a["name"], 60)}"')
        if itype == "password":
            parts.append('value="[redacted:password]"')
            redacted = True
        else:
            value, red = _safe_field_value(a.get("value", ""))
            redacted = red
            if value:
                parts.append(f'value="{_attr(value)}"')
            elif a.get("placeholder"):
                parts.append(f'placeholder="{_attr(a["placeholder"])}"')
        if "checked" in a:
            parts.append("checked")
        line = f"{indent}{prefix}<input {' '.join(parts)}>"
        _emit(st, line, "input", fp, is_new, redacted)
    elif tag == "textarea":
        value, red = _safe_field_value(_text_of(el))
        name = f' name="{_attr(a["name"], 60)}"' if a.get("name") else ""
        line = f"{indent}{prefix}<textarea{name}>{_clip(value, 200)}</textarea>"
        _emit(st, line, "textarea", fp, is_new, red)
    elif tag == "select":
        name = f' name="{_attr(a["name"], 60)}"' if a.get("name") else ""
        _emit(st, f"{indent}{prefix}<select{name}>", "select", fp, is_new)
        options = [d for d in _descendants(el) if d.tag == "option"]
        for opt in options[:_MAX_OPTIONS]:
            oval = opt.attrs.get("value", "")
            sel = " selected" if "selected" in opt.attrs else ""
            oline = (f'{indent}  <option value="{_attr(oval, 60)}"{sel}>'
                     f'{_clip(_text_of(opt), 80)}</option>')
            _emit(st, oline, None, None)
        if len(options) > _MAX_OPTIONS:
            _emit(st, f"{indent}  <!-- +{len(options) - _MAX_OPTIONS} "
                      f"more options -->", None, None)
        _emit(st, f"{indent}</select>", None, None)
    else:  # role=/onclick interactive element
        role = a.get("role", "")
        marker = f'role="{_attr(role, 30)}"' if role else "onclick"
        line = (f"{indent}{prefix}<{tag} {marker}>"
                f"{_clip(_text_of(el), 120)}</{tag}>")
        _emit(st, line, "generic", fp, is_new)


def _render(root: _El, keep: Optional[set],
            seen: Optional[set]) -> _RenderState:
    st = _RenderState(seen)

    def rec(el: _El, depth: int) -> None:
        indent = "  " * min(depth, 10)
        if _is_actionable(el):
            _emit_actionable(st, el, indent)
            return  # leaf rule: inner markup summarized as text
        tag = el.tag
        if tag == "iframe":
            st.frames += 1
            fp = _fingerprint(el)
            prefix, is_new = _index_prefix(st, fp)
            line = (f'{indent}{prefix}<iframe frame="f{st.frames}" '
                    f'src="{_attr(_safe_url(el.attrs.get("src", "")), 300)}">')
            _emit(st, line, "frame", fp, is_new)
            return
        if tag in _HEADING_TAGS:
            txt = _clip(_text_of(el), 200)
            if txt:
                _emit(st, f"{indent}{'#' * int(tag[1])} {txt}", None, None)
            return
        if tag == "img":
            alt = el.attrs.get("alt", "").strip()
            if alt:
                _emit(st, f'{indent}<img alt="{_attr(alt)}">', None, None)
            return
        own = _own_text(el)
        if own:
            _emit(st, f"{indent}{_clip(own, _TEXT_CAP)}", None, None)
        for ch in el.children:
            if isinstance(ch, _El) and (keep is None or id(ch) in keep):
                rec(ch, depth + 1)

    rec(root, 0)
    return st


# ---------------------------------------------------------------------------
# web_fetch_tree
# ---------------------------------------------------------------------------

def _fetch_tree(url: str, query: Optional[str] = None,
                seen: Optional[set] = None,
                max_chars: int = TREE_CAP_CHARS) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "code": "bad_url",
                "message": "URL must start with http(s)://"}
    max_chars = max(_TREE_MIN_CHARS, min(TREE_CAP_CHARS, int(max_chars)))
    try:
        raw = _download(url)
    except Exception as exc:
        return {"ok": False, "code": "fetch_failed",
                "message": f"fetch failed: {exc}"}

    builder = _TreeBuilder()
    builder.feed(raw)
    builder.close()
    root = builder.root
    _prune_empty(root)

    keep = None
    matched: Optional[int] = None
    if query:
        keep, matched = _bm25_filter(root, query)

    st = _render(root, keep, seen)
    records = st.records

    # Hard cap at a line boundary, with an honest truncation marker.
    marker = ""
    shown = records
    truncated = False
    total_chars = sum(len(r["line"]) + 1 for r in records)
    budget = max_chars - min(600, max_chars // 4)  # header + marker room
    if total_chars > budget:
        acc, cut = 0, 0
        for i, r in enumerate(records):
            acc += len(r["line"]) + 1
            if acc > budget:
                cut = i
                break
        else:
            cut = len(records)
        shown = records[:cut]
        truncated = True
        marker = (f"…[tree truncated: {len(records) - cut} lines omitted "
                  f"of {len(records)} — narrow with 'query' or re-fetch]")

    kinds = Counter(r["kind"] for r in shown if r["kind"])
    indexed_shown = sum(1 for r in shown if r["fp"])
    new_shown = sum(1 for r in shown if r["new"])
    values_redacted = sum(1 for r in shown if r["redacted"])

    header_lines = [f"# {builder.title or '(untitled page)'}",
                    f"url: {url}",
                    f"elements: {indexed_shown} "
                    f"(links: {kinds.get('link', 0)}, "
                    f"buttons: {kinds.get('button', 0)}, "
                    f"inputs: {kinds.get('input', 0)}, "
                    f"selects: {kinds.get('select', 0)}, "
                    f"textareas: {kinds.get('textarea', 0)}, "
                    f"frames: {kinds.get('frame', 0)}) | "
                    f"pruned: {builder.pruned} | "
                    f"truncated: {'yes' if truncated else 'no'}"]
    if query:
        header_lines.append(
            f'query: "{query}" | matched_blocks: {matched}')
        if matched == 0:
            header_lines.append(
                "[no content blocks matched the query — "
                "headings outline shown]")
    if seen is not None:
        header_lines.append(f"new_since_last_fetch: {new_shown}")
    header_lines.append("---")

    body = "\n".join(r["line"] for r in shown)
    if marker:
        body = body + "\n" + marker if body else marker
    tree = "\n".join(header_lines) + "\n" + body

    return {"ok": True, "result": {
        "url": url,
        "title": builder.title,
        "tree": tree,
        "chars": len(tree),
        "elements": indexed_shown,
        "links": kinds.get("link", 0),
        "buttons": kinds.get("button", 0),
        "inputs": kinds.get("input", 0),
        "selects": kinds.get("select", 0),
        "textareas": kinds.get("textarea", 0),
        "frames": kinds.get("frame", 0),
        "pruned_nodes": builder.pruned,
        "truncated": truncated,
        "query": query or None,
        "matched_blocks": matched,
        "new_count": new_shown if seen is not None else None,
        "values_redacted": values_redacted,
        "dcl": "on" if _DCL is not None else "off",
        "fingerprints": [r["fp"] for r in shown if r["fp"]],
    }}


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "web_search":
        return _search(str(args.get("query", "")),
                       args.get("max_results", 5))
    if tool_name == "web_fetch":
        return _fetch(str(args.get("url", "")))
    if tool_name == "web_fetch_tree":
        seen_arg = args.get("seen")
        seen = ({str(x) for x in seen_arg[:5000]}
                if isinstance(seen_arg, list) else None)
        try:
            max_chars = int(args.get("max_chars") or TREE_CAP_CHARS)
        except (TypeError, ValueError):
            max_chars = TREE_CAP_CHARS
        query = str(args.get("query") or "").strip() or None
        return _fetch_tree(str(args.get("url", "")), query=query,
                           seen=seen, max_chars=max_chars)
    return {"ok": False, "code": "unknown_tool",
            "message": f"unknown tool: {tool_name}"}
