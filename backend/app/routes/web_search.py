from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.schemas.web_search import LegalCitation, WebSearchRequest, WebSearchResponse
from app.services.llm_service import llm_service
from app.services.web_search import SearXNGUnavailable, WebSearchError, web_search_service

router = APIRouter(prefix="/web-search", tags=["Web Search"])

@router.get("/health", response_model=Dict[str, Any])
def web_search_health():
    """
    Reports whether the self-hosted SearXNG instance and the local models are
    usable.  Useful for diagnosing a deployment before running real searches.
    """
    return {
        "enabled": settings.WEB_SEARCH_ENABLED,
        **web_search_service.health(),
    }

@router.post("", response_model=WebSearchResponse)
def web_search(request: WebSearchRequest):
    """
    Live legal web search backed by a self-hosted SearXNG instance.

    Results are retrieved, extracted and verified before they are returned, and
    every citation points at text that was actually fetched.  Failures are
    reported honestly - no source is ever invented.
    """
    if not settings.WEB_SEARCH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Web search is disabled on this deployment (WEB_SEARCH_ENABLED=false).",
        )

    try:
        result = web_search_service.search(
            query=request.query,
            top_k=request.top_k,
            include_secondary=request.include_secondary,
            jurisdiction=request.jurisdiction,
            allowed_domains=request.domains,
        )
    except SearXNGUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Search backend unavailable: {exc}",
        ) from exc
    except WebSearchError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    citations = [LegalCitation(**c) for c in result.get("citations", [])]
    primary = [c for c in citations if c.source_tier in ("primary", "official")]
    secondary = [c for c in citations if c.source_tier == "secondary"]

    answer = llm_service.generate_web_legal_answer(
        query=request.query, grounded_context=result.get("grounded_context", "")
    )
    if not answer:
        # No LLM configured (or synthesis failed): surface the grounded
        # passages themselves rather than an ungrounded answer.
        answer = result.get("grounded_context", "")

    return WebSearchResponse(
        query=result["query"],
        answer=answer,
        citations=citations,
        primary_sources=primary,
        secondary_sources=secondary,
        grounded_context=result.get("grounded_context", ""),
        degraded=bool(result.get("degraded")),
        message=result.get("message"),
        diagnostics=result.get("diagnostics", {}),
    )
