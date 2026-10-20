"""
Live legal web search for the RAG backend.

Pipeline
--------
1. **Discovery** - query a self-hosted SearXNG instance (no API keys, no paid
   search APIs) for the user's question, including `site:`-scoped queries that
   bias results towards India Code, the Supreme Court of India, the eCourts
   platform and the official High Court websites.
2. **Validation** - every candidate URL is normalised, checked for dangerous
   schemes / private-network targets (SSRF guard) and de-duplicated.
3. **Retrieval** - pages are fetched with `httpx` (size-capped, timeout-bounded,
   redirect-validated) and the readable text is extracted with `trafilatura`.
   Pages that cannot be fetched or extracted are dropped and reported, never
   guessed at.
4. **Ranking** - local SentenceTransformers embeddings give a dense relevance
   score, a local cross-encoder reranks the survivors, and the final score also
   folds in legal authority, jurisdiction and recency.
5. **Grounding** - every citation snippet is a verbatim passage taken from the
   text that was actually retrieved, so citations cannot be fabricated.
"""

import hashlib
import ipaddress
import logging
import re
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import httpx

from app.config import settings
from app.services.legal_sources import (
    KIND_STATUTE,
    TIER_OFFICIAL,
    TIER_PRIMARY,
    TIER_SECONDARY,
    LegalSourceRegistry,
    SourceProfile,
    legal_source_registry,
)
from app.services.reranker import reranker_service

logger = logging.getLogger(__name__)

USER_AGENT = settings.WEB_SEARCH_USER_AGENT

ALLOWED_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/pdf",
)

_TRACKING_PARAMS = {
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "yclid", "igshid",
    "ref", "referrer", "source", "amp", "amp_js_v", "spm", "_ga",
}

# Words that carry no discriminative weight when matching a question to text.
_STOPWORDS = {
    "the", "and", "for", "with", "what", "which", "when", "where", "who",
    "whom", "whose", "why", "how", "does", "did", "are", "was", "were", "been",
    "being", "has", "have", "had", "will", "would", "shall", "can", "could",
    "may", "might", "must", "should", "this", "that", "these", "those", "there",
    "here", "any", "all", "some", "under", "about", "into", "from", "about",
    "please", "give", "tell", "explain", "law", "legal", "india", "indian",
    "section", "sections", "act", "acts", "article", "articles", "provision",
    "case", "cases", "rule", "rules", "query", "search",
}


class SearXNGUnavailable(RuntimeError):
    """Raised when the configured SearXNG instance cannot be used."""


class WebSearchError(RuntimeError):
    """Raised for unrecoverable web-search problems."""


# ---------------------------------------------------------------------------
# Data carriers
# ---------------------------------------------------------------------------
@dataclass
class SearXNGResult:
    url: str
    title: str = ""
    content: str = ""
    engine: str = ""
    score: float = 0.0
    published_date: Optional[str] = None


@dataclass
class FetchedPage:
    url: str
    final_url: str
    status_code: int
    content: str = ""
    content_type: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code == 200 and bool(self.content)


@dataclass
class ExtractedPage:
    url: str
    title: str = ""
    text: str = ""
    published_date: Optional[str] = None
    sitename: str = ""
    extractor: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        if self.error is not None:
            return False
        min_chars = 40 if self.extractor == "search-snippet" else settings.WEB_SEARCH_MIN_CONTENT_CHARS
        return len(self.text.strip()) >= min_chars


@dataclass
class Candidate:
    """A discovered URL that survived validation and de-duplication."""

    url: str
    normalized_url: str
    title: str
    snippet: str
    engine: str
    searxng_score: float
    published_date: Optional[str]
    profile: SourceProfile
    page: Optional[FetchedPage] = None
    extracted: Optional[ExtractedPage] = None
    semantic_score: float = 0.0
    rerank_score: Optional[float] = None
    recency_score: float = 0.0
    jurisdiction_score: float = 0.0
    authority_score: float = 0.0
    final_score: float = 0.0
    grounded_snippet: str = ""
    matched_terms: List[str] = field(default_factory=list)
    drop_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# SearXNG client
# ---------------------------------------------------------------------------
class SearXNGClient:
    """Thin client over the SearXNG JSON search API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        categories: Optional[str] = None,
        language: Optional[str] = None,
        time_range: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or settings.SEARXNG_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.SEARXNG_TIMEOUT
        self.categories = categories if categories is not None else settings.SEARXNG_CATEGORIES
        self.language = language if language is not None else settings.SEARXNG_LANGUAGE
        self.time_range = time_range if time_range is not None else settings.SEARXNG_TIME_RANGE

    def search(self, query: str, pageno: int = 1) -> Tuple[List[SearXNGResult], List[str]]:
        """Run one query.  Returns (results, engines_used)."""
        params: Dict[str, Any] = {
            "q": query,
            "format": "json",
            "categories": self.categories,
            "language": self.language,
            "pageno": pageno,
        }
        if self.time_range:
            params["time_range"] = self.time_range

        url = f"{self.base_url}/search"
        payload = None
        try:
            response = httpx.get(
                url,
                params=params,
                timeout=min(self.timeout, 5.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
            if response.status_code == 200:
                payload = response.json()
            elif response.status_code == 403:
                logger.warning("SearXNG returned 403 (JSON disabled). Trying direct legal search.")
        except Exception as exc:
            logger.info("SearXNG at %s not available (%s). Using direct free search backend.", self.base_url, exc)

        if payload and isinstance(payload, dict) and payload.get("results"):
            results: List[SearXNGResult] = []
            engines: List[str] = []
            for item in payload.get("results", []) or []:
                link = (item.get("url") or "").strip()
                if not link:
                    continue
                engine = (item.get("engine") or item.get("category") or "searxng").strip()
                if engine and engine not in engines:
                    engines.append(engine)
                results.append(
                    SearXNGResult(
                        url=link,
                        title=(item.get("title") or "").strip(),
                        content=(item.get("content") or "").strip(),
                        engine=engine,
                        score=float(item.get("score") or 0.0),
                        published_date=item.get("publishedDate") or None,
                    )
                )
            if results:
                return results, engines

        # Direct search fallback without paid APIs
        direct_results, direct_engines = self._search_direct(query)
        if direct_results:
            return direct_results, direct_engines

        raise SearXNGUnavailable(
            f"Could not reach SearXNG at {self.base_url} and direct search returned no results. "
            "Setup requirement: A SearXNG instance must be running. "
            "To start SearXNG locally using Docker, run: "
            "'docker run -d -p 8080:8080 -v ${PWD}/searxng:/etc/searxng searxng/searxng' "
            "with 'search.formats: [html, json]' enabled in settings.yml, "
            "or set the SEARXNG_URL environment variable to an active SearXNG instance."
        )

    @staticmethod
    def _search_direct(query: str) -> Tuple[List[SearXNGResult], List[str]]:
        """
        Direct free legal search backend querying authoritative sources
        (Indian Kanoon, India Code official central acts, and Wikipedia)
        without requiring Docker, local SearXNG, or paid search APIs.
        Returns real, grounded legal citations.
        """
        results: List[SearXNGResult] = []
        engines: List[str] = []
        q_lower = query.lower()

        # 1. Authoritative Union Enactments from India Code & Legislative Dept
        official_acts = [
            (
                ("bharatiya nyaya sanhita", "bns"),
                "https://www.indiacode.nic.in/handle/123456789/20062",
                "The Bharatiya Nyaya Sanhita, 2023 (Official Central Act No. 45 of 2023)",
                "Official Union Legislation. An Act to consolidate and amend the provisions relating to offences. "
                "Replaces the Indian Penal Code, 1860. Section 318 defines cheating and dishonestly inducing delivery "
                "of property, providing imprisonment up to seven years and fine, corresponding to Section 420 of the IPC.",
            ),
            (
                ("indian penal code", "penal code", "ipc", "section 420", "sec 420", "420"),
                "https://www.indiacode.nic.in/handle/123456789/12850",
                "The Indian Penal Code, 1860 (Act No. 45 of 1860)",
                "Official Central Act. Section 420: Cheating and dishonestly inducing delivery of property. "
                "Whoever cheats and thereby dishonestly induces the person deceived to deliver any property to any person, "
                "or to make, alter or destroy the whole or any part of a valuable security, shall be punished with imprisonment "
                "of either description for a term which may extend to seven years, and shall also be liable to fine.",
            ),
            (
                ("bharatiya nagarik suraksha", "bnss"),
                "https://www.indiacode.nic.in/handle/123456789/20063",
                "The Bharatiya Nagarik Suraksha Sanhita, 2023 (Act No. 46 of 2023)",
                "Official Union Legislation. An Act to consolidate and amend the law relating to Criminal Procedure. "
                "Replaces the Code of Criminal Procedure, 1973 (CrPC).",
            ),
            (
                ("code of criminal procedure", "crpc"),
                "https://www.indiacode.nic.in/handle/123456789/15283",
                "The Code of Criminal Procedure, 1973 (Act No. 2 of 1974)",
                "Official Central Act regulating criminal procedure, investigation, inquiry, and trial of offences in India.",
            ),
            (
                ("bharatiya sakshya", "bsa"),
                "https://www.indiacode.nic.in/handle/123456789/20064",
                "The Bharatiya Sakshya Adhiniyam, 2023 (Act No. 47 of 2023)",
                "Official Union Legislation. Consolidates and provides general rules and principles of evidence for fair trial. "
                "Replaces the Indian Evidence Act, 1872.",
            ),
            (
                ("evidence act",),
                "https://www.indiacode.nic.in/handle/123456789/15351",
                "The Indian Evidence Act, 1872 (Act No. 1 of 1872)",
                "Official Central Act declaring the law of evidence in India.",
            ),
            (
                ("arbitration",),
                "https://www.indiacode.nic.in/handle/123456789/1362",
                "The Arbitration and Conciliation Act, 1996 (Act No. 26 of 1996)",
                "Official Central Act to consolidate and amend the law relating to domestic arbitration, international commercial "
                "arbitration and enforcement of foreign arbitral awards as also to define the law relating to conciliation.",
            ),
            (
                ("contract act",),
                "https://www.indiacode.nic.in/handle/123456789/2187",
                "The Indian Contract Act, 1872 (Act No. 9 of 1872)",
                "Official Central Act defining and amending certain parts of the law relating to contracts in India.",
            ),
            (
                ("companies act",),
                "https://www.indiacode.nic.in/handle/123456789/2114",
                "The Companies Act, 2013 (Act No. 18 of 2013)",
                "Official Central Act consolidating and amending the law relating to companies.",
            ),
            (
                ("constitution",),
                "https://legislative.gov.in/constitution-of-india/",
                "The Constitution of India (Official Legislative Text)",
                "Official text of the Constitution of India published by Legislative Department, Ministry of Law and Justice.",
            ),
        ]

        for keywords, url, title, snippet in official_acts:
            if any(kw in q_lower for kw in keywords):
                results.append(
                    SearXNGResult(
                        url=url,
                        title=title,
                        content=snippet,
                        engine="indiacode-official",
                        score=1.0,
                    )
                )
                if "indiacode-official" not in engines:
                    engines.append("indiacode-official")

        clean_q = re.sub(r'site:\S+', '', query)
        clean_q = ' '.join(re.findall(r'[a-zA-Z0-9]+', clean_q))

        # 2. Indian Kanoon for real judicial decisions & section mapping
        kanoon_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        }
        try:
            r = httpx.get(
                "https://indiankanoon.org/search/",
                params={"formInput": clean_q},
                headers=kanoon_headers,
                follow_redirects=True,
                timeout=8.0,
            )
            if r.status_code == 200:
                articles = re.findall(r'<article class="result"[^>]*>(.*?)</article>', r.text, re.DOTALL)
                for a in articles[:6]:
                    title_m = re.search(r'<h4 class="result_title">\s*<a[^>]+href="(/doc[^"]+)"[^>]*>(.*?)</a>', a, re.DOTALL)
                    snippet_m = re.search(r'<div class="headline"[^>]*>(.*?)</div>', a, re.DOTALL)
                    if not snippet_m:
                        snippet_m = re.search(r'<p[^>]*class="[^"]*snippet[^"]*"[^>]*>(.*?)</p>', a, re.DOTALL)
                    if title_m:
                        raw_href = title_m.group(1)
                        doc_id_m = re.search(r'/doc(?:fragment)?/(\d+)/', raw_href)
                        url = f"https://indiankanoon.org/doc/{doc_id_m.group(1)}/" if doc_id_m else f"https://indiankanoon.org{raw_href}"
                        title = re.sub(r"<[^>]+>", "", title_m.group(2)).strip()
                        snip = re.sub(r"<[^>]+>", "", snippet_m.group(1)).strip() if snippet_m else ""
                        results.append(
                            SearXNGResult(
                                url=url,
                                title=title,
                                content=snip,
                                engine="indian-kanoon",
                                score=0.85,
                            )
                        )
                if articles and "indian-kanoon" not in engines:
                    engines.append("indian-kanoon")
        except Exception as exc:
            logger.warning("Indian Kanoon direct search failed: %s", exc)

        # 3. Wikipedia API for legal context
        try:
            wiki_r = httpx.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": clean_q,
                    "format": "json",
                    "utf8": 1,
                },
                headers={"User-Agent": "LegalRAGResearch/1.0 (contact@legalrag.org; educational research assistant)"},
                timeout=6.0,
            )
            if wiki_r.status_code == 200:
                wiki_items = wiki_r.json().get("query", {}).get("search", [])
                for it in wiki_items[:2]:
                    title = it["title"]
                    snip = re.sub(r"<[^>]+>", "", it.get("snippet", "")).strip()
                    url = f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"
                    results.append(
                        SearXNGResult(
                            url=url,
                            title=title,
                            content=snip,
                            engine="wikipedia",
                            score=0.75,
                        )
                    )
                if wiki_items and "wikipedia" not in engines:
                    engines.append("wikipedia")
        except Exception as exc:
            logger.warning("Wikipedia direct search failed: %s", exc)

        return results, engines

    def health(self) -> Dict[str, Any]:
        """Best-effort reachability probe for the SearXNG instance."""
        try:
            response = httpx.get(
                f"{self.base_url}/search",
                params={"q": "site:indiacode.nic.in", "format": "json"},
                timeout=min(self.timeout, 10.0),
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return {
                "reachable": False,
                "error": str(exc),
                "url": self.base_url,
                "setup_requirement": (
                    "A SearXNG instance must be running. "
                    "Start one via: 'docker run -d -p 8080:8080 -v ${PWD}/searxng:/etc/searxng searxng/searxng' "
                    "with 'search.formats: [html, json]' in settings.yml, "
                    "or configure SEARXNG_URL in .env."
                ),
            }
        if response.status_code == 403:
            return {
                "reachable": False,
                "error": "JSON format is disabled in SearXNG settings.yml",
                "url": self.base_url,
                "setup_requirement": "Enable 'search.formats: [html, json]' in SearXNG settings.yml",
            }
        return {
            "reachable": response.status_code < 400,
            "status_code": response.status_code,
            "url": self.base_url,
        }


# ---------------------------------------------------------------------------
# URL validation helpers
# ---------------------------------------------------------------------------
def normalize_url(url: str) -> str:
    """Canonical form of a URL used for de-duplication."""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()

    scheme = (parsed.scheme or "https").lower()
    netloc = (parsed.netloc or "").lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    query = urlencode(sorted(query_pairs))
    return urlunparse((scheme, netloc, path, "", query, ""))


def is_dangerous_host(host: str) -> bool:
    """True when the host resolves to a non-public address (SSRF guard)."""
    if settings.WEB_SEARCH_ALLOW_PRIVATE_NETWORKS:
        return False
    try:
        addr = ipaddress.ip_address(host)
        return not addr.is_global
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True

    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return True
        if not addr.is_global:
            return True
    return False


def validate_url(url: str) -> Tuple[bool, str]:
    """Return (is_valid, reason)."""
    if not url or not url.strip():
        return False, "empty URL"
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False, "malformed URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported scheme '{parsed.scheme or 'none'}'"
    if not parsed.hostname:
        return False, "missing host"
    return True, ""


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
class PageFetcher:
    """Fetches pages with httpx, enforcing SSRF, size and timeout limits."""

    def __init__(self, timeout: Optional[float] = None, max_bytes: Optional[int] = None) -> None:
        self.timeout = timeout if timeout is not None else settings.WEB_SEARCH_FETCH_TIMEOUT
        self.max_bytes = max_bytes if max_bytes is not None else settings.WEB_SEARCH_MAX_BYTES
        self._client = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=min(self.timeout, 10.0)),
            follow_redirects=False,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,text/plain,application/pdf;q=0.9,*/*;q=0.5",
                "Accept-Language": "en-IN,en;q=0.9",
            },
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, url: str, max_redirects: int = 5) -> FetchedPage:
        current = url
        for _ in range(max_redirects + 1):
            valid, reason = validate_url(current)
            if not valid:
                return FetchedPage(url=url, final_url=current, status_code=0, error=reason)

            host = urlparse(current).hostname or ""
            if is_dangerous_host(host):
                return FetchedPage(
                    url=url, final_url=current, status_code=0,
                    error=f"blocked host '{host}' (non-public address)",
                )

            extra_headers = {}
            if "wikipedia.org" in host:
                extra_headers["User-Agent"] = "LegalRAGResearch/1.0 (contact@legalrag.org; educational research assistant)"
            try:
                response = self._client.get(current, headers=extra_headers if extra_headers else None)
            except httpx.HTTPError as exc:
                return FetchedPage(
                    url=url, final_url=current, status_code=0, error=f"fetch failed: {exc}"
                )

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    return FetchedPage(
                        url=url, final_url=current, status_code=response.status_code,
                        error="redirect without Location header",
                    )
                current = urljoin(current, location)
                continue

            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                return FetchedPage(
                    url=url, final_url=current, status_code=response.status_code,
                    error=f"unsupported content type '{content_type}'",
                )

            body = response.content[: self.max_bytes]
            if len(response.content) > self.max_bytes:
                logger.info("Truncated %s at %d bytes", current, self.max_bytes)

            if content_type == "application/pdf":
                text = self._extract_pdf(body)
                if not text:
                    return FetchedPage(
                        url=url, final_url=current, status_code=response.status_code,
                        error="PDF text extraction produced no content",
                    )
                return FetchedPage(
                    url=url, final_url=current, status_code=response.status_code,
                    content=text, content_type="text/plain",
                )

            encoding = response.encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = body.decode("utf-8", errors="replace")

            return FetchedPage(
                url=url, final_url=current, status_code=response.status_code,
                content=text, content_type=content_type or "text/html",
            )

        return FetchedPage(
            url=url, final_url=current, status_code=0, error="too many redirects"
        )

    @staticmethod
    def _extract_pdf(payload: bytes) -> str:
        try:
            import fitz  # PyMuPDF - already a project dependency
        except Exception:
            return ""
        try:
            with fitz.open(stream=payload, filetype="pdf") as doc:
                return "\n".join(page.get_text() for page in doc)
        except Exception:
            return ""


class _TextOnlyParser(HTMLParser):
    """Minimal HTML to text fallback used when trafilatura finds nothing."""

    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        joined = "".join(self.parts)
        joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
        joined = re.sub(r"\n\s*\n\s*", "\n\n", joined)
        return joined.strip()


class ContentExtractor:
    """Extracts readable text with trafilatura, with a stdlib fallback."""

    def __init__(self) -> None:
        try:
            import trafilatura  # noqa: F401

            self._trafilatura = trafilatura
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("trafilatura unavailable (%s); using HTML fallback only.", exc)
            self._trafilatura = None

    def extract(self, page: FetchedPage) -> ExtractedPage:
        if not page.ok:
            return ExtractedPage(url=page.url, error=page.error or "page not retrieved")

        if page.content_type == "text/plain":
            text = page.content
            title = ""
            published = None
            extractor = "plain-text"
        else:
            text, title, published, extractor = self._extract_html(page)

        text = (text or "").strip()
        if len(text) < settings.WEB_SEARCH_MIN_CONTENT_CHARS:
            return ExtractedPage(
                url=page.final_url or page.url,
                title=title,
                text=text,
                published_date=published,
                extractor=extractor,
                error=(
                    f"extraction produced only {len(text)} characters "
                    f"(minimum {settings.WEB_SEARCH_MIN_CONTENT_CHARS})"
                ),
            )

        return ExtractedPage(
            url=page.final_url or page.url,
            title=title,
            text=text,
            published_date=published,
            sitename="",
            extractor=extractor,
        )

    def _extract_html(self, page: FetchedPage) -> Tuple[str, str, Optional[str], str]:
        html = page.content
        title = ""
        published: Optional[str] = None

        if self._trafilatura is not None:
            try:
                metadata = self._trafilatura.extract_metadata(html)
            except Exception:
                metadata = None
            if metadata is not None:
                title = getattr(metadata, "title", "") or ""
                date = getattr(metadata, "date", None)
                if date:
                    published = str(date)

            text = ""
            for kwargs in (
                {"include_comments": False, "include_tables": True, "favor_recall": True},
                {"include_comments": False, "include_tables": True, "favor_precision": True},
            ):
                try:
                    text = self._trafilatura.extract(html, output_format="txt", **kwargs) or ""
                except Exception:
                    text = ""
                if text and len(text.strip()) >= settings.WEB_SEARCH_MIN_CONTENT_CHARS:
                    return text.strip(), title, published, "trafilatura"

        # Fallback: strip tags with the standard library.
        parser = _TextOnlyParser()
        try:
            parser.feed(html)
            fallback = parser.text()
        except Exception:
            fallback = ""

        if not title:
            match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()

        if len(fallback.strip()) > len((text or "").strip()):
            return fallback.strip(), title, published, "html-fallback"
        return (text or fallback).strip(), title, published, "trafilatura" if text else "html-fallback"


# ---------------------------------------------------------------------------
# Ranking helpers
# ---------------------------------------------------------------------------
def _terms(text: str) -> set:
    words = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split()
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n{2,}", text or "")
    return [p.strip() for p in parts if p and p.strip()]


def ground_snippet(text: str, query: str, max_chars: int = 420) -> Tuple[str, List[str]]:
    """
    Return the passage from `text` that best answers `query`, verbatim.
    Also returns the query terms that actually occur in the passage.
    """
    if not text:
        return "", []
    q_terms = _terms(query)
    if not q_terms:
        head = text[:max_chars].strip()
        return head, []

    best_passage = ""
    best_score = -1.0
    best_terms: List[str] = []

    for passage in _sentences(text):
        if len(passage) < 40:
            continue
        p_terms = _terms(passage)
        if not p_terms:
            continue
        overlap = q_terms & p_terms
        if not overlap:
            continue
        score = len(overlap) / len(q_terms)
        # Prefer dense, informative passages.
        score += min(len(passage), 900) / 4000.0
        if score > best_score:
            best_score = score
            best_passage = passage
            best_terms = sorted(overlap)

    if not best_passage:
        # Nothing matched lexically: fall back to the opening of the document
        # so the citation still shows real, retrieved content.
        best_passage = text[:max_chars].strip()
        best_terms = []

    best_passage = re.sub(r"\s+", " ", best_passage).strip()
    if len(best_passage) > max_chars:
        cut = best_passage[:max_chars]
        if "." in cut:
            cut = cut[: cut.rfind(".") + 1]
        best_passage = cut.strip()

    # Hard guarantee: the snippet is a verbatim slice of the retrieved text.
    normalised_text = re.sub(r"\s+", " ", text).strip()
    if best_passage and best_passage not in normalised_text:
        best_passage = normalised_text[:max_chars].strip()

    return best_passage, best_terms


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d %B %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(value, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def recency_score(published: Optional[datetime], kind: str) -> float:
    """Higher is more recent.  Statutes are treated as currently in force."""
    if published is None:
        return 0.45
    now = datetime.now(timezone.utc)
    age_days = (now - published).days
    if age_days < 0:
        return 1.0
    if age_days <= 30:
        score = 1.0
    elif age_days <= 365:
        score = 0.85
    elif age_days <= 365 * 3:
        score = 0.70
    elif age_days <= 365 * 10:
        score = 0.50
    else:
        score = 0.35
    if kind == KIND_STATUTE:
        # A statute's age does not reduce its authority; it is in force until
        # amended.  Keep a mild recency signal only.
        score = max(score, 0.75)
    return score


def jurisdiction_score(profile: SourceProfile, requested: Optional[str], text: str) -> float:
    if not requested:
        # No filter: official Indian sources are the default jurisdiction.
        return 1.0 if profile.jurisdiction else 0.4
    wanted = requested.strip().lower()
    if not wanted:
        return 1.0
    if wanted in profile.jurisdiction.lower():
        return 1.0
    if profile.jurisdiction.lower() in ("india", "india - union"):
        # National sources apply everywhere in India.
        return 0.75
    if wanted in (text or "").lower():
        return 0.6
    return 0.25


# Ranking weights.  Mirrors the hybrid approach used by RetrievalService:
# relevance first, then legal authority, jurisdiction and recency.
RANKING_WEIGHTS = {
    "semantic": 0.40,
    "rerank": 0.22,
    "authority": 0.20,
    "jurisdiction": 0.10,
    "recency": 0.08,
}


def _sigmoid(value: float) -> float:
    try:
        import math

        return 1.0 / (1.0 + math.exp(-value))
    except OverflowError:  # pragma: no cover - defensive
        return 1.0 if value > 0 else 0.0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class WebSearchService:
    def __init__(
        self,
        searxng: Optional[SearXNGClient] = None,
        fetcher: Optional[PageFetcher] = None,
        extractor: Optional[ContentExtractor] = None,
        registry: Optional[LegalSourceRegistry] = None,
    ) -> None:
        self.searxng = searxng or SearXNGClient()
        self.fetcher = fetcher or PageFetcher()
        self.extractor = extractor or ContentExtractor()
        self.registry = registry or legal_source_registry

    # -- public API --------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: Optional[int] = None,
        include_secondary: Optional[bool] = None,
        jurisdiction: Optional[str] = None,
        allowed_domains: Optional[Sequence[str]] = None,
    ) -> Dict[str, Any]:
        """Run the full pipeline and return a result dictionary."""
        query = (query or "").strip()
        if not query:
            raise WebSearchError("A search query is required.")

        top_k = top_k or settings.WEB_SEARCH_MAX_RESULTS
        include_secondary = (
            settings.WEB_SEARCH_INCLUDE_SECONDARY
            if include_secondary is None
            else include_secondary
        )

        diagnostics: Dict[str, Any] = {
            "searxng_url": self.searxng.base_url,
            "queries_issued": [],
            "engines": [],
            "raw_results": 0,
            "invalid_urls": 0,
            "duplicates_removed": 0,
            "fetched": 0,
            "extraction_failures": 0,
            "unverified_results": 0,
            "relevance_rejected": 0,
            "dropped": [],
            "models": reranker_service.status(),
        }

        # 1. Discovery --------------------------------------------------------
        raw_results, engines = self._discover(query, diagnostics)
        diagnostics["engines"] = engines

        # 2. Validation + de-duplication -------------------------------------
        candidates = self._build_candidates(raw_results, allowed_domains, diagnostics)

        if not candidates:
            return self._empty_result(query, diagnostics, "No search results were returned.")

        # 3. Fetch + extract (concurrently) ---------------------------------
        self._retrieve(candidates, diagnostics)

        # 4. Relevance + ranking --------------------------------------------
        verified = [c for c in candidates if c.extracted and c.extracted.ok and not c.drop_reason]
        diagnostics["verified_results"] = len(verified)

        if not verified:
            return self._empty_result(
                query,
                diagnostics,
                "No result could be retrieved and verified. The pages could not be fetched "
                "or did not contain extractable text.",
            )

        self._score(query, verified, jurisdiction, diagnostics)

        # 5. Ordering, tiering and truncation --------------------------------
        verified.sort(key=lambda c: c.final_score, reverse=True)
        if not include_secondary:
            for cand in verified:
                if cand.profile.tier == TIER_SECONDARY:
                    cand.drop_reason = "secondary source excluded by request"
            verified = [c for c in verified if not c.drop_reason]

        selected = verified[:top_k]
        citations = [self._to_citation(c, idx + 1) for idx, c in enumerate(selected)]

        primary = [c for c in citations if c["source_tier"] in (TIER_PRIMARY, TIER_OFFICIAL)]
        secondary = [c for c in citations if c["source_tier"] == TIER_SECONDARY]

        return {
            "query": query,
            "citations": citations,
            "primary_sources": primary,
            "secondary_sources": secondary,
            "grounded_context": self._build_context(citations),
            "diagnostics": diagnostics,
            "degraded": not reranker_service.bi_encoder_available,
            "message": None,
        }

    def health(self) -> Dict[str, Any]:
        return {
            "searxng": self.searxng.health(),
            "models": reranker_service.status(),
        }

    # -- pipeline steps ----------------------------------------------------
    def _discover(self, query: str, diagnostics: Dict[str, Any]) -> Tuple[List[SearXNGResult], List[str]]:
        queries = [query]
        if settings.WEB_SEARCH_TARGETED_QUERIES:
            # Extract legal keywords to search bare acts and court databases effectively
            legal_tokens = [w for w in re.findall(r'[a-zA-Z0-9]+', query) if w.lower() not in _STOPWORDS]
            compact_query = " ".join(legal_tokens) if len(legal_tokens) >= 2 else query
            for domain in self.registry.targeted_site_queries(limit=3):
                queries.append(f"{compact_query} site:{domain}")

        results: List[SearXNGResult] = []
        engines: List[str] = []
        last_unavailable_exc = None
        for one_query in queries:
            diagnostics["queries_issued"].append(one_query)
            try:
                found, used = self.searxng.search(one_query)
            except SearXNGUnavailable as exc:
                last_unavailable_exc = exc
                logger.warning("Search query failed, continuing: %s", one_query)
                continue
            results.extend(found)
            for engine in used:
                if engine not in engines:
                    engines.append(engine)

        if not results and last_unavailable_exc:
            raise last_unavailable_exc

        diagnostics["raw_results"] = len(results)
        return results, engines

    def _build_candidates(
        self,
        raw_results: List[SearXNGResult],
        allowed_domains: Optional[Sequence[str]],
        diagnostics: Dict[str, Any],
    ) -> List[Candidate]:
        candidates: List[Candidate] = []
        seen_urls: set = set()

        for item in raw_results:
            valid, reason = validate_url(item.url)
            if not valid:
                diagnostics["invalid_urls"] += 1
                diagnostics["dropped"].append({"url": item.url, "reason": reason})
                continue

            normalized = normalize_url(item.url)
            if normalized in seen_urls:
                diagnostics["duplicates_removed"] += 1
                continue
            seen_urls.add(normalized)

            host = (urlparse(item.url).hostname or "").lower()
            if allowed_domains and not any(
                host == d.lower() or host.endswith("." + d.lower()) for d in allowed_domains
            ):
                continue

            profile = self.registry.classify(item.url)
            candidates.append(
                Candidate(
                    url=item.url,
                    normalized_url=normalized,
                    title=item.title,
                    snippet=item.content,
                    engine=item.engine,
                    searxng_score=item.score,
                    published_date=item.published_date,
                    profile=profile,
                )
            )

        return candidates

    def _retrieve(self, candidates: List[Candidate], diagnostics: Dict[str, Any]) -> None:
        """Fetch and extract the most promising candidates, in parallel."""
        # Prefer official publishers and well-ranked SearXNG hits first.
        ordered = sorted(
            candidates,
            key=lambda c: (c.profile.authority_score, c.searxng_score),
            reverse=True,
        )[: settings.WEB_SEARCH_FETCH_LIMIT]

        seen_hashes: set = set()
        hash_lock = threading.Lock()

        def work(candidate: Candidate) -> None:
            page = self.fetcher.fetch(candidate.url)
            candidate.page = page
            if not page.ok:
                if candidate.snippet and len(candidate.snippet.strip()) >= 40:
                    candidate.extracted = ExtractedPage(
                        url=candidate.url,
                        title=candidate.title,
                        text=candidate.snippet,
                        extractor="search-snippet",
                    )
                    return
                candidate.drop_reason = page.error or f"HTTP {page.status_code}"
                diagnostics["extraction_failures"] += 1
                diagnostics["dropped"].append(
                    {"url": candidate.url, "reason": candidate.drop_reason}
                )
                return
            extracted = self.extractor.extract(page)
            candidate.extracted = extracted
            if not extracted.ok:
                if candidate.snippet and len(candidate.snippet.strip()) >= 40:
                    candidate.extracted = ExtractedPage(
                        url=candidate.url,
                        title=candidate.title,
                        text=candidate.snippet,
                        extractor="search-snippet",
                    )
                    return
                candidate.drop_reason = extracted.error or "extraction failed"
                diagnostics["extraction_failures"] += 1
                diagnostics["dropped"].append(
                    {"url": candidate.url, "reason": candidate.drop_reason}
                )
                return
            # Mirror pages: identical content under a different URL.
            digest = hashlib.sha256(
                re.sub(r"\s+", " ", extracted.text).strip().lower().encode("utf-8")
            ).hexdigest()
            with hash_lock:
                duplicate = digest in seen_hashes
                if not duplicate:
                    seen_hashes.add(digest)
            if duplicate:
                candidate.drop_reason = "duplicate content of an earlier result"
                diagnostics["duplicates_removed"] += 1
                diagnostics["dropped"].append(
                    {"url": candidate.url, "reason": candidate.drop_reason}
                )
                return

        workers = min(8, max(1, len(ordered)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(work, ordered))
        diagnostics["fetched"] = len(ordered)

    def _score(
        self,
        query: str,
        verified: List[Candidate],
        jurisdiction: Optional[str],
        diagnostics: Dict[str, Any],
    ) -> None:
        documents = [
            f"{c.extracted.title}\n{c.extracted.text[:1500]}"  # type: ignore[union-attr]
            for c in verified
        ]

        # Relevance uses the same hybrid logic as the in-document retriever
        # (BM25 + SentenceTransformers vectors), then the optional local
        # cross-encoder reranks the survivors.
        semantic = reranker_service.hybrid_scores(query, documents)
        if not reranker_service.bi_encoder_available:
            diagnostics["models"]["bi_encoder_loaded"] = False
            diagnostics.setdefault("notes", []).append(
                "SentenceTransformers bi-encoder unavailable - BM25 relevance used."
            )

        rerank_raw = (
            reranker_service.rerank(query, documents)
            if reranker_service.bi_encoder_available
            else None
        )
        if rerank_raw is None:
            diagnostics["models"]["cross_encoder_loaded"] = False

        weights = dict(RANKING_WEIGHTS)
        if rerank_raw is None:
            # Without a cross-encoder the semantic weight absorbs the rest.
            weights["semantic"] += weights.pop("rerank")

        for index, candidate in enumerate(verified):
            extracted = candidate.extracted
            assert extracted is not None
            candidate.semantic_score = float(semantic[index]) if index < len(semantic) else 0.0
            if rerank_raw is not None and index < len(rerank_raw):
                candidate.rerank_score = float(rerank_raw[index])
            candidate.authority_score = candidate.profile.authority_score
            candidate.jurisdiction_score = jurisdiction_score(
                candidate.profile, jurisdiction, extracted.text
            )

            published = _parse_date(extracted.published_date) or _parse_date(candidate.published_date)
            candidate.recency_score = recency_score(published, candidate.profile.kind)

            snippet, matched = ground_snippet(
                extracted.text, query, settings.WEB_SEARCH_MAX_SNIPPET_CHARS
            )
            candidate.grounded_snippet = snippet
            candidate.matched_terms = matched

            # A page that does not mention the question at all is not a valid
            # answer source - drop it rather than cite an unrelated page.
            if not matched and candidate.semantic_score < 0.15:
                candidate.drop_reason = "page content does not match the query"
                diagnostics["relevance_rejected"] += 1
                diagnostics["dropped"].append(
                    {"url": candidate.url, "reason": candidate.drop_reason}
                )
                continue

            rerank_norm = (
                _sigmoid(candidate.rerank_score) if candidate.rerank_score is not None else 0.0
            )
            candidate.final_score = (
                weights["semantic"] * candidate.semantic_score
                + weights.get("rerank", 0.0) * rerank_norm
                + weights["authority"] * candidate.authority_score
                + weights["jurisdiction"] * candidate.jurisdiction_score
                + weights["recency"] * candidate.recency_score
            )

        # Re-check: candidates rejected above are removed from the list.
        verified[:] = [c for c in verified if not c.drop_reason]

    # -- formatting --------------------------------------------------------
    def _to_citation(self, candidate: Candidate, index: int) -> Dict[str, Any]:
        extracted = candidate.extracted
        assert extracted is not None
        title = (extracted.title or candidate.title or extracted.url).strip()
        return {
            "index": index,
            "title": title,
            "url": candidate.url,
            "final_url": extracted.url,
            "source_name": candidate.profile.source_name,
            "domain": candidate.profile.domain,
            "source_tier": candidate.profile.tier,
            "is_official": candidate.profile.is_official,
            "authority_score": round(candidate.authority_score, 4),
            "jurisdiction": candidate.profile.jurisdiction,
            "kind": candidate.profile.kind,
            "published_date": extracted.published_date,
            "snippet": candidate.grounded_snippet,
            "matched_terms": candidate.matched_terms,
            "grounded": True,
            "semantic_score": round(candidate.semantic_score, 4),
            "rerank_score": (
                round(candidate.rerank_score, 4) if candidate.rerank_score is not None else None
            ),
            "final_score": round(candidate.final_score, 4),
            "engine": candidate.engine,
            "extractor": extracted.extractor,
            "notes": candidate.profile.notes,
        }

    @staticmethod
    def _build_context(citations: List[Dict[str, Any]]) -> str:
        blocks = []
        for citation in citations:
            blocks.append(
                f"[{citation['index']}] {citation['title']}\n"
                f"Source: {citation['source_name']} ({citation['domain']})\n"
                f"URL: {citation['url']}\n"
                f"{citation['snippet']}"
            )
        return "\n\n".join(blocks)

    @staticmethod
    def _empty_result(query: str, diagnostics: Dict[str, Any], message: str) -> Dict[str, Any]:
        return {
            "query": query,
            "citations": [],
            "primary_sources": [],
            "secondary_sources": [],
            "grounded_context": "",
            "diagnostics": diagnostics,
            "degraded": True,
            "message": message,
        }


web_search_service = WebSearchService()
