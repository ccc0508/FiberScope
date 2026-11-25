"""Public-only search transport. It receives one already-authorized query."""

import re
from html import unescape
from urllib.parse import urlsplit

import httpx


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
RESULT_LIMIT = 4


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    return " ".join(unescape(re.sub(r"</?[a-zA-Z][^<>]*>", "", value)).split())[:limit]


def _safe_url(value):
    if not isinstance(value, str) or len(value) > 1800 or any(c.isspace() or c == "\\" for c in value):
        return False
    try:
        url = urlsplit(value)
        return url.scheme in {"https", "http"} and bool(url.hostname) and not url.username and url.password is None
    except ValueError:
        return False


class BravePublicSearch:
    def __init__(self, api_key, client=None):
        self.api_key = api_key
        self.client = client

    def _request(self, client, query, timeout):
        response = client.post(
            BRAVE_SEARCH_URL,
            headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            json={"q": query, "count": RESULT_LIMIT, "result_filter": ["web"], "text_decorations": False,
                  "spellcheck": False, "operators": False},
            timeout=min(timeout, 8),
        )
        response.raise_for_status()
        return response.json()

    def __call__(self, query, timeout):
        if self.client is None:
            with httpx.Client(follow_redirects=False) as client:
                payload = self._request(client, query, timeout)
        else:
            payload = self._request(self.client, query, timeout)
        if not isinstance(payload, dict) or not isinstance(payload.get("web", {}), dict):
            raise ValueError("Invalid public search response")
        rows = payload.get("web", {}).get("results", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid public search results")
        results = []
        for row in rows[:RESULT_LIMIT]:
            if not isinstance(row, dict) or not _safe_url(row.get("url")):
                continue
            title = _text(row.get("title"), 180)
            snippet = _text(row.get("description"), 900)
            if title and snippet:
                results.append(dict(title=title, url=row["url"], snippet=snippet))
        return results
