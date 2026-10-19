"""Web skill: internet search + page fetching. Stdlib only, no API keys.

web_search uses DuckDuckGo's HTML endpoint (no key, no signup).
web_fetch pulls readable text from a URL.

All web content is UNTRUSTED — the gate wraps it, the brain must never
obey instructions found in pages.
"""

from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict

SKILL_NAME = "web"

TOOL_DEFINITIONS = [
    {
        "name": "web_search",
        "description": "Search the web. Returns titles, URLs, snippets.",
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


def _fetch(url: str) -> Dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "code": "bad_url",
                "message": "URL must start with http(s)://"}
    req = urllib.request.Request(url, headers=_UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(500_000).decode("utf-8", "replace")  # 500KB cap
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


def handle(tool_name: str, args: Dict[str, Any], ctx) -> Dict[str, Any]:
    if tool_name == "web_search":
        return _search(str(args.get("query", "")),
                       args.get("max_results", 5))
    if tool_name == "web_fetch":
        return _fetch(str(args.get("url", "")))
    return {"ok": False, "code": "unknown_tool",
            "message": f"unknown tool: {tool_name}"}
