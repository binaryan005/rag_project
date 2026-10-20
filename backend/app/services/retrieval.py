from sqlalchemy.orm import Session
from app.models.chunk import Chunk
from app.services.embedder import embedder
from rank_bm25 import BM25Okapi
import re

def tokenize_text(text: str):
    """Basic lowercase and alphanumeric tokenization for BM25.

    Shared with the web-search ranker so both pipelines score text the same way.
    """
    return [word.lower() for word in re.findall(r'\b\w+\b', text)]

class RetrievalService:
    def hybrid_search(self, db: Session, document_id: str, query: str, top_k: int = 5):
        """
        Performs a hybrid search combining pgvector cosine similarity and BM25 exact keyword matching.
        """
        # 1. Fetch all chunks for the given document
        chunks = db.query(Chunk).filter(Chunk.document_id == document_id).all()
        if not chunks:
            return []

        # 2. Vector search scoring
        query_embedding = embedder.generate_embedding(query)
        
        from app.config import settings
        import numpy as np
        
        if db.bind.dialect.name == "postgresql":
            # Calculate cosine distance in the database (pgvector)
            vector_results = db.query(
                Chunk, 
                Chunk.embedding.cosine_distance(query_embedding).label("distance")
            ).filter(Chunk.document_id == document_id).all()
            vector_scores = {res.Chunk.id: (1.0 - float(res.distance)) for res in vector_results}
        else:
            # Fallback for SQLite testing (in-memory distance calculation)
            vector_scores = {}
            q_emb = np.array(query_embedding)
            q_norm = np.linalg.norm(q_emb)
            for chunk in chunks:
                if chunk.embedding:
                    c_emb = np.array(chunk.embedding)
                    c_norm = np.linalg.norm(c_emb)
                    if q_norm > 0 and c_norm > 0:
                        cos_sim = np.dot(q_emb, c_emb) / (q_norm * c_norm)
                    else:
                        cos_sim = 0.0
                    vector_scores[chunk.id] = float(cos_sim)
                else:
                    vector_scores[chunk.id] = 0.0


        # 3. BM25 scoring
        tokenized_corpus = [self._tokenize(chunk.text) for chunk in chunks]
        tokenized_query = self._tokenize(query)
        bm25 = BM25Okapi(tokenized_corpus)
        bm25_raw_scores = bm25.get_scores(tokenized_query)
        
        bm25_scores = {chunk.id: float(score) for chunk, score in zip(chunks, bm25_raw_scores)}
        
        # 4. Normalize and Combine (Min-Max normalization)
        min_v = min(vector_scores.values()) if vector_scores else 0
        max_v = max(vector_scores.values()) if vector_scores else 1
        range_v = max_v - min_v if max_v > min_v else 1
        
        min_b = min(bm25_scores.values()) if bm25_scores else 0
        max_b = max(bm25_scores.values()) if bm25_scores else 1
        range_b = max_b - min_b if max_b > min_b else 1

        hybrid_scores = []
        for chunk in chunks:
            norm_v = (vector_scores[chunk.id] - min_v) / range_v
            norm_b = (bm25_scores[chunk.id] - min_b) / range_b
            
            # Weighting: 70% semantic vector, 30% exact keyword match
            combined_score = 0.7 * norm_v + 0.3 * norm_b
            hybrid_scores.append((combined_score, chunk))
            
        print("\n===== RETRIEVAL DEBUG =====")
        print(f"QUERY: {query}")


        for score, chunk in sorted(hybrid_scores, key=lambda x: x[0], reverse=True)[:top_k]:
            print(f"\nSCORE: {score:.4f}")
            print(f"CHUNK ID: {chunk.id}")
            print(f"PAGE: {chunk.page_number}")
            print(f"TEXT: {chunk.text[:500]}")


        print("===========================\n")


        hybrid_scores.sort(key=lambda x: x[0], reverse=True)
        return [chunk for score, chunk in hybrid_scores[:top_k]]
        
    def _tokenize(self, text: str):
        # Basic lowercase and alphanumeric tokenization for BM25
        return tokenize_text(text)

retrieval_service = RetrievalService()
