from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from apps.api import web_research
from apps.api.web_research import (
    BochaSearchProvider,
    SearchResult,
    WebResearchError,
    _normalize_bocha_results,
    _normalize_tavily_results,
    fetch_page,
    is_blocked_ip,
    normalize_fetch_url,
    resolve_public_ips,
    search_web,
)


def _settings(**overrides):
    base = dict(
        web_fetch_max_bytes=2_097_152,
        web_fetch_max_chars=20_000,
        web_fetch_timeout_seconds=15.0,
        web_search_max_results=8,
        web_search_provider="bocha",
        web_search_api_key="test-key",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Provider normalization
# ---------------------------------------------------------------------------


def test_normalize_bocha_results_maps_fields_and_respects_top_k():
    payload = {
        "data": {
            "webPages": {
                "value": [
                    {
                        "name": "EV sales 2026",
                        "url": "https://example.com/a",
                        "summary": "China EV sales rose.",
                        "datePublished": "2026-01-01",
                    },
                    {"title": "No name", "url": "https://example.com/b", "snippet": "x"},
                    {"url": "https://example.com/c", "summary": "third"},
                ]
            }
        }
    }
    results = _normalize_bocha_results(payload, top_k=2)
    assert len(results) == 2
    assert results[0] == SearchResult(
        title="EV sales 2026",
        url="https://example.com/a",
        snippet="China EV sales rose.",
        published_at="2026-01-01",
    )
    assert results[1].title == "No name"
    assert results[1].published_at is None
    assert results[0].to_dict()["published_at"] == "2026-01-01"
    assert "published_at" not in results[1].to_dict()


def test_normalize_tavily_results_uses_content_as_snippet():
    payload = {
        "results": [
            {
                "title": "Tavily hit",
                "url": "https://example.org/x",
                "content": "body text",
                "published_date": "2025-12-31",
            },
            {"url": "https://example.org/y", "content": "second"},
        ]
    }
    results = _normalize_tavily_results(payload, top_k=8)
    assert [r.url for r in results] == ["https://example.org/x", "https://example.org/y"]
    assert results[0].snippet == "body text"
    assert results[0].published_at == "2025-12-31"
    # missing title falls back to url
    assert results[1].title == "https://example.org/y"


def test_search_web_truncates_to_top_k_and_uses_provider():
    provider = SimpleNamespace(
        name="fake",
        search=lambda query, top_k: [
            SearchResult(title=f"r{i}", url=f"https://e/{i}", snippet="s")
            for i in range(10)
        ],
    )
    results = search_web("q", top_k=3, settings=_settings(), provider=provider)
    assert len(results) == 3
    assert all(isinstance(r, SearchResult) for r in results)


def test_bocha_provider_maps_transport_error_to_structured_failure(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(web_research.httpx, "post", _raise)
    provider = BochaSearchProvider(api_key="key", timeout=5.0)
    with pytest.raises(WebResearchError) as exc:
        provider.search("q", 5)
    assert exc.value.code == "WEB_SEARCH_PROVIDER_ERROR"


def test_bocha_provider_requires_api_key():
    provider = BochaSearchProvider(api_key="  ", timeout=5.0)
    with pytest.raises(WebResearchError) as exc:
        provider.search("q", 5)
    assert exc.value.code == "WEB_SEARCH_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# SSRF: per-network rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",  # cloud metadata
        "192.168.1.10",
        "172.16.4.4",
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "not-an-ip",
    ],
)
def test_is_blocked_ip_rejects_non_public(ip):
    assert is_blocked_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"])
def test_is_blocked_ip_allows_public(ip):
    assert is_blocked_ip(ip) is False


def test_ipv4_mapped_ipv6_private_is_blocked():
    assert is_blocked_ip("::ffff:10.0.0.1") is True


def test_normalize_fetch_url_upgrades_http_to_https():
    assert normalize_fetch_url("http://example.com/page").startswith("https://example.com/page")


def test_normalize_fetch_url_rejects_non_http_scheme():
    with pytest.raises(WebResearchError) as exc:
        normalize_fetch_url("ftp://example.com/x")
    assert exc.value.code == "WEB_FETCH_SCHEME_BLOCKED"


def test_normalize_fetch_url_requires_host():
    with pytest.raises(WebResearchError) as exc:
        normalize_fetch_url("https:///nohost")
    assert exc.value.code == "WEB_FETCH_INVALID_URL"


def test_resolve_public_ips_rejects_private_resolution(monkeypatch):
    def _fake_getaddrinfo(host, port, *args, **kwargs):
        return [(2, 1, 6, "", ("10.1.2.3", port))]

    monkeypatch.setattr(web_research.socket, "getaddrinfo", _fake_getaddrinfo)
    with pytest.raises(WebResearchError) as exc:
        resolve_public_ips("internal.example.com", 443)
    assert exc.value.code == "WEB_FETCH_BLOCKED"


# ---------------------------------------------------------------------------
# fetch_page: SSRF, redirects, truncation
# ---------------------------------------------------------------------------


def _patch_dns(monkeypatch, mapping):
    """mapping: host -> ip string. Missing hosts resolve to a public IP."""

    def _fake_getaddrinfo(host, port, *args, **kwargs):
        ip = mapping.get(host, "93.184.216.34")
        return [(2, 1, 6, "", (ip, port))]

    monkeypatch.setattr(web_research.socket, "getaddrinfo", _fake_getaddrinfo)


def test_fetch_page_blocks_private_before_any_request(monkeypatch):
    _patch_dns(monkeypatch, {"internal.local": "10.0.0.9"})
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, text="secret")

    with pytest.raises(WebResearchError) as exc:
        fetch_page(
            "https://internal.local/admin",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code == "WEB_FETCH_BLOCKED"
    assert called["n"] == 0  # no outbound request was made


def test_fetch_page_blocks_redirect_escape_to_private(monkeypatch):
    _patch_dns(monkeypatch, {"public.example.com": "93.184.216.34", "evil.internal": "127.0.0.1"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "https://evil.internal/creds"})
        return httpx.Response(200, text="LEAKED")

    with pytest.raises(WebResearchError) as exc:
        fetch_page(
            "https://public.example.com/start",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code == "WEB_FETCH_BLOCKED"


def test_fetch_page_rejects_too_many_redirects(monkeypatch):
    _patch_dns(monkeypatch, {})

    def handler(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params.get("n", "0"))
        return httpx.Response(302, headers={"location": f"https://example.com/next?n={n + 1}"})

    with pytest.raises(WebResearchError) as exc:
        fetch_page(
            "https://example.com/start?n=0",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code == "WEB_FETCH_TOO_MANY_REDIRECTS"


def test_fetch_page_extracts_and_char_truncates(monkeypatch):
    _patch_dns(monkeypatch, {})
    body = "<html><head><title>Report</title></head><body><p>" + ("A" * 500) + "</p></body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    result = fetch_page(
        "https://example.com/report",
        settings=_settings(web_fetch_max_chars=100),
        transport=httpx.MockTransport(handler),
    )
    assert result["title"] == "Report"
    assert result["char_count"] == 100
    assert result["truncated"] is True
    assert result["url"].startswith("https://example.com/report")


def test_fetch_page_flags_byte_truncation(monkeypatch):
    _patch_dns(monkeypatch, {})
    big = "<html><body>" + ("x" * 5000) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=big, headers={"content-type": "text/html"})

    result = fetch_page(
        "https://example.com/big",
        settings=_settings(web_fetch_max_bytes=1000, web_fetch_max_chars=20000),
        transport=httpx.MockTransport(handler),
    )
    assert result["truncated"] is True
    assert result["byte_size"] <= 1000


def test_fetch_page_http_error_is_structured(monkeypatch):
    _patch_dns(monkeypatch, {})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(WebResearchError) as exc:
        fetch_page(
            "https://example.com/x",
            settings=_settings(),
            transport=httpx.MockTransport(handler),
        )
    assert exc.value.code == "WEB_FETCH_HTTP_ERROR"
