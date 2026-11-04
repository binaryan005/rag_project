from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class WebSearchRequest(BaseModel):
    """Request payload for the legal web-search endpoint."""
    query: str = Field(..., min_length=2, max_length=500, description="Legal question or search phrase")
    top_k: int = Field(default=8, ge=1, le=25, description="Maximum number of citations to return")
    include_secondary: bool = Field(
        default=True,
        description="Include secondary sources (Indian Kanoon, legal commentary) in the results",
    )
    jurisdiction: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Optional jurisdiction filter, e.g. 'Karnataka' or 'Supreme Court'",
    )
    domains: Optional[List[str]] = Field(
        default=None,
        description="Optional allow-list of domains to restrict discovery to",
    )

class LegalCitation(BaseModel):
    """A single verified source, grounded in text actually retrieved."""
    index: int
    title: str
    url: str
    final_url: Optional[str] = None
    source_name: str
    domain: str
    source_tier: str = Field(..., description="primary | official | secondary | other")
    is_official: bool = False
    authority_score: float = 0.0
    jurisdiction: str = ""
    kind: str = "other"
    published_date: Optional[str] = None
    snippet: str = Field(default="", description="Verbatim passage from the retrieved page")
    matched_terms: List[str] = []
    grounded: bool = True
    semantic_score: float = 0.0
    rerank_score: Optional[float] = None
    final_score: float = 0.0
    engine: str = ""
    extractor: str = ""
    notes: str = ""

class WebSearchResponse(BaseModel):
    query: str
    answer: str = Field(default="", description="Grounded answer; empty when synthesis is unavailable")
    citations: List[LegalCitation] = []
    primary_sources: List[LegalCitation] = Field(
        default=[], description="Statute / judgment publishers and official government bodies"
    )
    secondary_sources: List[LegalCitation] = Field(
        default=[], description="Commentary and aggregator sources, listed separately"
    )
    grounded_context: str = ""
    degraded: bool = False
    message: Optional[str] = None
    diagnostics: Dict[str, Any] = {}
