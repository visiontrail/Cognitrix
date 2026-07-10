"""Web research toolface — search providers, SSRF-hardened fetch, body extraction.

This module is the single outbound-HTTP surface for the BI agent's web-search
capability. It is deliberately provider-agnostic (``SearchProvider`` protocol),
and every fetch is forced through code-level SSRF protection: the model controls
the outbound URL, so private/loopback/link-local/metadata addresses are rejected
before any socket connects, and every redirect hop is re-validated.

The functions here are synchronous by design: the agent dispatches BI tools
synchronously and off-loads them to a worker thread via ``anyio.to_thread``, so a
blocking ``httpx.Client`` inside that thread is the correct fit and avoids nesting
event loops.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from .config import Settings, get_settings

logger = logging.getLogger("cognitrix.web_research")

_FETCH_USER_AGENT = (
    "Mozilla/5.0 (compatible; CognitrixBI/1.0; +https://cognitrix.local/bot)"
)
_MAX_REDIRECTS = 3
# Cap concurrent outbound fetches process-wide. Tools run in worker threads, so a
# threading semaphore is the right primitive.
_FETCH_SEMAPHORE = threading.Semaphore(4)

# Networks that must never be reachable via an LLM-controlled URL, on top of the
# categories ``ipaddress`` already flags (private / loopback / link-local /
# reserved / multicast / unspecified).
_EXTRA_BLOCKED_NETWORKS: tuple[ipaddress._BaseNetwork, ...] = (
    ipaddress.ip_network("100.64.0.0/10"),   # carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),    # IETF protocol assignments
    ipaddress.ip_network("192.0.2.0/24"),    # TEST-NET-1
    ipaddress.ip_network("198.18.0.0/15"),   # benchmarking
    ipaddress.ip_network("198.51.100.0/24"), # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("fc00::/7"),        # unique local addresses
)


class WebResearchError(Exception):
    """Structured failure for search/fetch, mapped to a tool-visible observation."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message}


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
        }
        if self.published_at:
            payload["published_at"] = self.published_at
        return payload


class SearchProvider(Protocol):
    """Provider abstraction — absorbs per-vendor response differences."""

    name: str

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        ...


# ---------------------------------------------------------------------------
# Search providers
# ---------------------------------------------------------------------------


class BochaSearchProvider:
    name = "bocha"
    endpoint = "https://api.bochaai.com/v1/web-search"

    def __init__(self, *, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        if not self._api_key.strip():
            raise WebResearchError(
                code="WEB_SEARCH_NOT_CONFIGURED",
                message="Bocha search API key is not configured.",
            )
        try:
            response = httpx.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query, "count": top_k, "summary": True},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(
                code="WEB_SEARCH_PROVIDER_ERROR",
                message=f"Bocha search request failed: {exc}",
            ) from exc
        except ValueError as exc:
            raise WebResearchError(
                code="WEB_SEARCH_PROVIDER_ERROR",
                message="Bocha search returned an unparseable response.",
            ) from exc
        return _normalize_bocha_results(payload, top_k)


class TavilySearchProvider:
    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, *, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        if not self._api_key.strip():
            raise WebResearchError(
                code="WEB_SEARCH_NOT_CONFIGURED",
                message="Tavily search API key is not configured.",
            )
        try:
            response = httpx.post(
                self.endpoint,
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": top_k,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise WebResearchError(
                code="WEB_SEARCH_PROVIDER_ERROR",
                message=f"Tavily search request failed: {exc}",
            ) from exc
        except ValueError as exc:
            raise WebResearchError(
                code="WEB_SEARCH_PROVIDER_ERROR",
                message="Tavily search returned an unparseable response.",
            ) from exc
        return _normalize_tavily_results(payload, top_k)


def _normalize_bocha_results(payload: Any, top_k: int) -> list[SearchResult]:
    data = payload.get("data") if isinstance(payload, dict) else None
    web_pages = data.get("webPages") if isinstance(data, dict) else None
    values = web_pages.get("value") if isinstance(web_pages, dict) else None
    if not isinstance(values, list):
        return []
    results: list[SearchResult] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("name") or item.get("title") or url).strip()
        snippet = str(item.get("summary") or item.get("snippet") or "").strip()
        published = item.get("datePublished") or item.get("dateLastCrawled")
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                published_at=str(published).strip() if published else None,
            )
        )
        if len(results) >= top_k:
            break
    return results


def _normalize_tavily_results(payload: Any, top_k: int) -> list[SearchResult]:
    values = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return []
    results: list[SearchResult] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        title = str(item.get("title") or url).strip()
        snippet = str(item.get("content") or item.get("snippet") or "").strip()
        published = item.get("published_date")
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                published_at=str(published).strip() if published else None,
            )
        )
        if len(results) >= top_k:
            break
    return results


def get_search_provider(settings: Settings | None = None) -> SearchProvider:
    settings = settings or get_settings()
    provider = (settings.web_search_provider or "bocha").strip().lower()
    if provider == "tavily":
        return TavilySearchProvider(
            api_key=settings.web_search_api_key,
            timeout=settings.web_fetch_timeout_seconds,
        )
    return BochaSearchProvider(
        api_key=settings.web_search_api_key,
        timeout=settings.web_fetch_timeout_seconds,
    )


def search_web(
    query: str,
    *,
    top_k: int | None = None,
    settings: Settings | None = None,
    provider: SearchProvider | None = None,
) -> list[SearchResult]:
    settings = settings or get_settings()
    resolved_top_k = top_k if top_k is not None else settings.web_search_max_results
    resolved_top_k = max(1, min(int(resolved_top_k), settings.web_search_max_results))
    active_provider = provider or get_search_provider(settings)
    results = active_provider.search(query, resolved_top_k)
    return results[:resolved_top_k]


# ---------------------------------------------------------------------------
# SSRF protection + fetch
# ---------------------------------------------------------------------------


def is_blocked_ip(ip_text: str) -> bool:
    """Return True when *ip_text* falls in a network the agent must never reach."""
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        # Not a literal IP — treat as unsafe (we only validate resolved IPs).
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True
    for network in _EXTRA_BLOCKED_NETWORKS:
        if ip.version == network.version and ip in network:
            return True
    return False


def normalize_fetch_url(url: str) -> str:
    """Normalize an outbound URL: force https (upgrading http), drop fragment."""
    parsed = urlparse(str(url or "").strip())
    scheme = (parsed.scheme or "").lower()
    if scheme in ("", "http"):
        scheme = "https"
    if scheme != "https":
        raise WebResearchError(
            code="WEB_FETCH_SCHEME_BLOCKED",
            message=f"Only https URLs may be fetched (got scheme '{parsed.scheme}').",
        )
    if not parsed.hostname:
        raise WebResearchError(
            code="WEB_FETCH_INVALID_URL",
            message="The URL is missing a host.",
        )
    return urlunparse((scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))


def resolve_public_ips(host: str, port: int) -> list[str]:
    """Resolve *host* and reject if any resolved address is a blocked network.

    Raises before any connection is attempted, so a URL pointing at a private
    or metadata address never produces an outbound socket to that address.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise WebResearchError(
            code="WEB_FETCH_DNS_FAILED",
            message=f"Could not resolve host '{host}'.",
        ) from exc
    addresses = [str(info[4][0]) for info in infos if info and info[4]]
    if not addresses:
        raise WebResearchError(
            code="WEB_FETCH_DNS_FAILED",
            message=f"Host '{host}' did not resolve to any address.",
        )
    for address in addresses:
        if is_blocked_ip(address):
            raise WebResearchError(
                code="WEB_FETCH_BLOCKED",
                message=f"Refusing to fetch a non-public address ({address}).",
            )
    return addresses


def _validate_hop(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 443
    resolve_public_ips(host, port)


def _extract_main_text(html: str, url: str) -> str:
    """Extract readable body text; prefer trafilatura, fall back to tag stripping."""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if extracted and extracted.strip():
            return extracted.strip()
    except Exception:  # noqa: BLE001 - extraction must never abort a fetch
        logger.debug("trafilatura_extract_failed url=%s", url, exc_info=True)
    return _strip_html(html)


def _strip_html(html: str) -> str:
    import re

    without_scripts = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    text = re.sub(r"&[a-zA-Z#0-9]+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_page(
    url: str,
    *,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Fetch a page over HTTPS with SSRF protection, size cap, and body extraction.

    Redirects are followed manually (max 3) and every hop is re-validated against
    the blocked-network policy. Returns a structured dict; raises
    ``WebResearchError`` for policy/transport failures.
    """
    settings = settings or get_settings()
    max_bytes = settings.web_fetch_max_bytes
    max_chars = settings.web_fetch_max_chars
    timeout = settings.web_fetch_timeout_seconds

    current_url = normalize_fetch_url(url)
    with _FETCH_SEMAPHORE:
        client_kwargs: dict[str, Any] = {
            "timeout": timeout,
            "follow_redirects": False,
            "headers": {"User-Agent": _FETCH_USER_AGENT, "Accept": "text/html,*/*"},
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        with httpx.Client(**client_kwargs) as client:
            for hop in range(_MAX_REDIRECTS + 1):
                _validate_hop(current_url)
                try:
                    with client.stream("GET", current_url) as response:
                        if response.is_redirect:
                            if hop >= _MAX_REDIRECTS:
                                raise WebResearchError(
                                    code="WEB_FETCH_TOO_MANY_REDIRECTS",
                                    message="Exceeded the maximum of 3 redirects.",
                                )
                            location = response.headers.get("location")
                            if not location:
                                raise WebResearchError(
                                    code="WEB_FETCH_INVALID_REDIRECT",
                                    message="Redirect response had no Location header.",
                                )
                            current_url = normalize_fetch_url(urljoin(current_url, location))
                            continue

                        if response.status_code >= 400:
                            raise WebResearchError(
                                code="WEB_FETCH_HTTP_ERROR",
                                message=f"Fetch returned HTTP {response.status_code}.",
                            )

                        raw, truncated_bytes = _read_capped(response, max_bytes)
                        final_url = str(response.url)
                        encoding = response.encoding or "utf-8"
                except httpx.HTTPError as exc:
                    raise WebResearchError(
                        code="WEB_FETCH_TRANSPORT_ERROR",
                        message=f"Fetch request failed: {exc}",
                    ) from exc

                text = raw.decode(encoding, errors="replace")
                extracted = _extract_main_text(text, final_url)
                truncated_chars = len(extracted) > max_chars
                content = extracted[:max_chars]
                return {
                    "url": final_url,
                    "title": _extract_title(text),
                    "content": content,
                    "byte_size": len(raw),
                    "truncated": bool(truncated_bytes or truncated_chars),
                    "char_count": len(content),
                }

    # Unreachable: the loop returns or raises.
    raise WebResearchError(
        code="WEB_FETCH_TOO_MANY_REDIRECTS",
        message="Exceeded the maximum number of redirects.",
    )


def _read_capped(response: httpx.Response, max_bytes: int) -> tuple[bytes, bool]:
    chunks: list[bytes] = []
    total = 0
    truncated = False
    for chunk in response.iter_bytes():
        chunks.append(chunk)
        total += len(chunk)
        if total >= max_bytes:
            truncated = True
            break
    body = b"".join(chunks)
    if len(body) > max_bytes:
        body = body[:max_bytes]
    return body, truncated


def _extract_title(html: str) -> str:
    import re

    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title[:300]
