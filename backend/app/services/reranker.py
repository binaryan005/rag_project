"""
Local semantic relevance scoring for the web-search pipeline.

Two free, fully local models are used:

* ``sentence-transformers`` bi-encoder (the same model the rest of the RAG
  pipeline already uses) for dense query/document similarity.
* A ``CrossEncoder`` reranker for a second, sharper relevance pass.

Both degrade gracefully: if the model files are not available (no network on
first run, no torch, ...) the service reports ``available = False`` and the
caller falls back to lexical scoring instead of failing the request.  Nothing
here ever requires an API key.
"""

import logging
import math
import threading
from typing import List, Optional, Sequence

from rank_bm25 import BM25Okapi

from app.config import settings
from app.services.embedder import embedder
from app.services.retrieval import tokenize_text

logger = logging.getLogger(__name__)


class RerankerService:
    """Dense similarity + cross-encoder reranking, with safe fallbacks."""

    def __init__(self) -> None:
        self._cross_encoder = None
        self._cross_encoder_loaded = False
        self._load_attempted = False
        self._lock = threading.Lock()

    # -- status ------------------------------------------------------------
    @property
    def cross_encoder_available(self) -> bool:
        """True only if the cross-encoder model actually loaded."""
        if not settings.RERANKER_ENABLED:
            return False
        if not self._load_attempted:
            self._ensure_cross_encoder()
        return self._cross_encoder_loaded

    @property
    def bi_encoder_available(self) -> bool:
        """True if the shared SentenceTransformer bi-encoder is loaded."""
        return bool(getattr(embedder, "is_model_loaded", False))

    def status(self) -> dict:
        return {
            "cross_encoder_loaded": self.cross_encoder_available,
            "cross_encoder_model": settings.RERANKER_MODEL_NAME,
            "bi_encoder_loaded": self.bi_encoder_available,
            "bi_encoder_model": settings.EMBEDDING_MODEL_NAME,
        }

    # -- scoring -----------------------------------------------------------
    def semantic_scores(self, query: str, documents: Sequence[str]) -> List[float]:
        """
        Cosine similarity between the query and each document, scaled to 0..1.
        Falls back to a lexical overlap score when the bi-encoder is missing.
        """
        if not documents:
            return []

        try:
            q_vec = embedder.generate_embedding(query)
            d_vecs = embedder.generate_embeddings(list(documents))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Semantic scoring failed, using lexical fallback: %s", exc)
            return self.lexical_scores(query, documents)

        scores: List[float] = []
        for d_vec in d_vecs:
            scores.append(self._cosine(q_vec, d_vec))
        return scores

    def lexical_scores(self, query: str, documents: Sequence[str]) -> List[float]:
        """Query-term overlap fallback, always available."""
        q_terms = self._terms(query)
        scores: List[float] = []
        for doc in documents:
            d_terms = self._terms(doc)
            if not q_terms or not d_terms:
                scores.append(0.0)
                continue
            overlap = len(q_terms & d_terms)
            scores.append(overlap / len(q_terms))
        return scores

    def hybrid_scores(self, query: str, documents: Sequence[str]) -> List[float]:
        """
        Hybrid relevance score in [0, 1].

        Reuses the scoring approach of ``RetrievalService.hybrid_search``:
        70% vector similarity + 30% BM25, both min-max normalised.  When the
        SentenceTransformers bi-encoder is unavailable the vector half is
        dropped and BM25 alone is used, so the score stays meaningful.
        """
        if not documents:
            return []

        tokenized_corpus = [tokenize_text(doc) for doc in documents]
        if any(tokenized_corpus):
            bm25 = BM25Okapi(tokenized_corpus)
            bm25_raw = bm25.get_scores(tokenize_text(query))
            bm25_scores = [float(s) for s in bm25_raw]
        else:
            bm25_scores = [0.0] * len(documents)

        if self.bi_encoder_available:
            vector_scores = self.semantic_scores(query, documents)
            weight_vector, weight_bm25 = 0.7, 0.3
        else:
            vector_scores = [0.0] * len(documents)
            weight_vector, weight_bm25 = 0.0, 1.0

        norm_v = self._min_max(vector_scores)
        norm_b = self._min_max(bm25_scores)
        return [
            weight_vector * nv + weight_bm25 * nb for nv, nb in zip(norm_v, norm_b)
        ]

    @staticmethod
    def _min_max(values: Sequence[float]) -> List[float]:
        if not values:
            return []
        lo = min(values)
        hi = max(values)
        span = hi - lo
        if span <= 0:
            return [0.0 for _ in values]
        return [(v - lo) / span for v in values]

    def rerank(self, query: str, documents: Sequence[str]) -> Optional[List[float]]:
        """
        Cross-encoder relevance scores.  Returns ``None`` when the model is
        unavailable so the caller can distinguish "not scored" from "scored 0".
        """
        if not documents:
            return []
        model = self._ensure_cross_encoder()
        if model is None:
            return None
        try:
            pairs = [(query, doc) for doc in documents]
            raw = model.predict(pairs)
            return [float(s) for s in raw]
        except Exception as exc:
            logger.warning("Cross-encoder rerank failed: %s", exc)
            return None

    # -- internals ---------------------------------------------------------
    def _ensure_cross_encoder(self):
        if self._load_attempted:
            return self._cross_encoder
        with self._lock:
            if self._load_attempted:
                return self._cross_encoder
            self._load_attempted = True
            if not settings.RERANKER_ENABLED:
                return None
            try:
                from sentence_transformers import CrossEncoder

                self._cross_encoder = CrossEncoder(settings.RERANKER_MODEL_NAME)
                self._cross_encoder_loaded = True
                logger.info("Cross-encoder reranker loaded: %s", settings.RERANKER_MODEL_NAME)
            except Exception as exc:
                self._cross_encoder = None
                self._cross_encoder_loaded = False
                logger.warning(
                    "Cross-encoder reranker unavailable (%s). "
                    "Falling back to embedding + lexical scoring.", exc
                )
            return self._cross_encoder

    @staticmethod
    def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = 0.0
        na = 0.0
        nb = 0.0
        for x, y in zip(a, b):
            dot += x * y
            na += x * x
            nb += y * y
        if na <= 0 or nb <= 0:
            return 0.0
        sim = dot / (math.sqrt(na) * math.sqrt(nb))
        # Cosine lives in [-1, 1]; map to [0, 1] so it can be blended.
        return max(0.0, min(1.0, (sim + 1.0) / 2.0))

    @staticmethod
    def _terms(text: str) -> set:
        import re

        words = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split()
        return {w for w in words if len(w) > 2}


reranker_service = RerankerService()
