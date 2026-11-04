"""
Tests for the Legal RAG web-search feature.

Verifies:
1. Handling of empty search results without hallucinating citations or URLs.
2. Prevention of fabricated URLs, titles, or snippets.
3. Separation and prioritization of official Indian sources (India Code, SCI, eCourts) vs secondary sources.
4. Basic error handling and exact setup requirement reporting when SearXNG is unavailable.
"""

import pytest
from app.services.legal_sources import TIER_PRIMARY, TIER_SECONDARY, legal_source_registry
from app.services.web_search import (
    Candidate,
    ExtractedPage,
    FetchedPage,
    SearXNGClient,
    SearXNGResult,
    SearXNGUnavailable,
    WebSearchError,
    WebSearchService,
)


class MockSearXNGClient:
    """Mock SearXNG client returning configurable search results."""

    def __init__(self, results=None, raise_exc=None):
        self.results = results if results is not None else []
        self.raise_exc = raise_exc
        self.base_url = "http://localhost:8080"

    def search(self, query: str, pageno: int = 1):
        if self.raise_exc:
            raise self.raise_exc
        return list(self.results), ["google", "duckduckgo"]

    def health(self):
        if self.raise_exc:
            return {"reachable": False, "error": str(self.raise_exc), "url": self.base_url}
        return {"reachable": True, "status_code": 200, "url": self.base_url}


class MockPageFetcher:
    """Mock page fetcher returning canned real-world page content."""

    def __init__(self, pages=None):
        self.pages = pages or {}

    def fetch(self, url: str, max_redirects: int = 5):
        if url in self.pages:
            return self.pages[url]
        return FetchedPage(
            url=url,
            final_url=url,
            status_code=200,
            content=(
                f"<html><body><h1>Official Record for {url}</h1>"
                f"<p>Section 420 in The Indian Penal Code deals with cheating and dishonestly "
                f"inducing delivery of property under Indian Law for {url}. A person committing cheating shall be punished "
                f"with imprisonment of either description for a term which may extend to seven years, and shall also "
                f"be liable to fine. The Arbitration and Conciliation Act 1996 defines arbitration agreement and disputes "
                f"governed under Central Act statutory provisions across all courts in India. Source url: {url}</p></body></html>"
            ),
            content_type="text/html",
        )


def test_empty_results_no_fabrication():
    """
    Test that when search returns no results, the service returns empty lists
    and NEVER invents or fabricates dummy URLs, titles, snippets, or citations.
    """
    mock_searxng = MockSearXNGClient(results=[])
    service = WebSearchService(searxng=mock_searxng)

    result = service.search("arbitration act section 34")

    assert result["citations"] == []
    assert result["primary_sources"] == []
    assert result["secondary_sources"] == []
    assert result["grounded_context"] == ""
    assert result["message"] is not None
    assert "No search results were returned" in result["message"]
    # Verify no URLs were fabricated
    for k in ("citations", "primary_sources", "secondary_sources"):
        assert len(result[k]) == 0


def test_real_results_grounding_and_no_fabricated_urls():
    """
    Test that search results only display actual URLs returned by search,
    and snippets are grounded in the retrieved content.
    """
    real_url = "https://indiacode.nic.in/handle/123456789/2263"
    real_results = [
        SearXNGResult(
            url=real_url,
            title="Section 420 in The Indian Penal Code",
            content="Cheating and dishonestly inducing delivery of property",
            engine="google",
            score=0.9,
        )
    ]
    mock_searxng = MockSearXNGClient(results=real_results)
    service = WebSearchService(searxng=mock_searxng, fetcher=MockPageFetcher())

    result = service.search("cheating dishonestly inducing property")

    assert len(result["citations"]) == 1
    citation = result["citations"][0]
    # Verify the URL is exactly the real returned URL, not fabricated
    assert citation["url"] == real_url
    assert citation["source_tier"] == TIER_PRIMARY
    assert citation["is_official"] is True
    assert citation["grounded"] is True
    # The snippet must be a verbatim passage from the retrieved content
    assert "420" in citation["snippet"] or "cheating" in citation["snippet"].lower()


def test_official_sources_prioritized_and_secondary_separated():
    """
    Test that official Indian legal sources (India Code, Supreme Court, eCourts)
    are prioritized as primary/official, while secondary aggregators (Indian Kanoon)
    are separated into secondary_sources.
    """
    results = [
        SearXNGResult(
            url="https://indiankanoon.org/doc/123456/",
            title="State vs accused on Indian Kanoon",
            content="Case analysis and commentary",
            engine="google",
            score=0.8,
        ),
        SearXNGResult(
            url="https://indiacode.nic.in/handle/123456789/1362",
            title="The Arbitration and Conciliation Act, 1996",
            content="Official Central Act legislation",
            engine="google",
            score=0.8,
        ),
    ]
    mock_searxng = MockSearXNGClient(results=results)
    service = WebSearchService(searxng=mock_searxng, fetcher=MockPageFetcher())

    result = service.search("arbitration act 1996")

    assert len(result["primary_sources"]) >= 1
    assert result["primary_sources"][0]["domain"] == "indiacode.nic.in"
    assert result["primary_sources"][0]["is_official"] is True

    assert len(result["secondary_sources"]) >= 1
    assert result["secondary_sources"][0]["domain"] == "indiankanoon.org"
    assert result["secondary_sources"][0]["source_tier"] == TIER_SECONDARY
    assert result["secondary_sources"][0]["is_official"] is False


def test_searxng_unavailable_reports_setup_requirement():
    """
    Test that when SearXNG is unavailable, the exact setup requirement is reported
    instead of pretending search succeeded.
    """
    unavail_err = SearXNGUnavailable(
        "Could not reach SearXNG at http://localhost:8080: Connection refused. "
        "Setup requirement: A SearXNG instance must be running. "
        "To start SearXNG locally using Docker, run: "
        "'docker run -d -p 8080:8080 -v ${PWD}/searxng:/etc/searxng searxng/searxng' "
        "with 'search.formats: [html, json]' enabled in settings.yml, "
        "or set the SEARXNG_URL environment variable to an active SearXNG instance."
    )
    mock_searxng = MockSearXNGClient(raise_exc=unavail_err)
    service = WebSearchService(searxng=mock_searxng)

    with pytest.raises(SearXNGUnavailable) as exc_info:
        service.search("contract dispute act")

    error_msg = str(exc_info.value)
    assert "Setup requirement" in error_msg
    assert "docker run -d -p 8080:8080" in error_msg
    assert "SEARXNG_URL" in error_msg


def test_empty_query_raises_error():
    """Test validation on blank query."""
    service = WebSearchService()
    with pytest.raises(WebSearchError) as exc_info:
        service.search("   ")
    assert "search query is required" in str(exc_info.value)
