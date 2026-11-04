import numpy as np
from typing import List
from app.config import settings

class EmbeddingService:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
        return cls._instance

    def _load_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
            except Exception as e:
                # Fallback to local transformers AutoModel or deterministic embedding if offline/mock
                print(f"[Embedder] SentenceTransformers load warning: {e}. Using numpy fallback.")
                self._model = None

    def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generates embedding vectors for a list of text strings."""
        if not texts:
            return []

        self._load_model()
        if self._model is not None:
            embeddings = self._model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        else:
            # Fallback embedding generator (384 dimensions normalized)
            return [self._fallback_embedding(t) for t in texts]

    def generate_embedding(self, text: str) -> List[float]:
        """Generates single embedding vector for a text string."""
        return self.generate_embeddings([text])[0]

    @property
    def is_model_loaded(self) -> bool:
        """True when the real SentenceTransformer model is in use (not the fallback)."""
        self._load_model()
        return self._model is not None

    def _fallback_embedding(self, text: str) -> List[float]:
        """Generates a deterministic 384-dimensional vector based on hash of text."""
        import hashlib
        seed = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16) % (2**32)
        np.random.seed(seed)
        vec = np.random.randn(settings.EMBEDDING_DIMENSION)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

embedder = EmbeddingService()
