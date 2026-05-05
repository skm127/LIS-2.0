"""
LIS Vector Memory — Semantic search powered by embeddings.

Augments the existing FTS5 keyword search with vector similarity search
for contextually-aware memory recall. Uses sentence-transformers for
local, free, fast embeddings and ChromaDB for vector storage.

Architecture:
    1. Every conversation turn gets embedded and stored in ChromaDB
    2. On recall, user query is embedded and nearest neighbors are returned
    3. Results are merged with FTS5 results for comprehensive context

Usage:
    from vector_memory import VectorMemory
    
    vmem = VectorMemory()
    vmem.store("I prefer dark mode in all apps", metadata={"type": "preference"})
    results = vmem.search("what theme does the user like?", top_k=5)
"""

import logging
import time
import hashlib
from pathlib import Path
from typing import Optional

log = logging.getLogger("lis.vector_memory")

DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"


class VectorMemory:
    """Semantic vector memory with local embeddings and ChromaDB storage."""

    def __init__(self, persist_dir: str = None):
        self._persist_dir = persist_dir or str(CHROMA_DIR)
        self._collection = None
        self._embed_model = None
        self._initialized = False
        self._init_error: Optional[str] = None

    def _lazy_init(self) -> bool:
        """Lazy initialization — only load heavy models when first needed."""
        if self._initialized:
            return self._collection is not None
        self._initialized = True

        try:
            import chromadb
            from chromadb.config import Settings

            # Create persistent ChromaDB client
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=self._persist_dir,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = client.get_or_create_collection(
                name="lis_memory",
                metadata={"hnsw:space": "cosine"},
            )
            log.info(f"VectorMemory initialized. {self._collection.count()} vectors stored.")
            return True
        except ImportError as e:
            self._init_error = f"Missing dependency: {e}. Run: pip install chromadb sentence-transformers"
            log.warning(f"VectorMemory disabled: {self._init_error}")
            return False
        except Exception as e:
            self._init_error = str(e)
            log.warning(f"VectorMemory init failed: {e}")
            return False

    def _get_embedder(self):
        """Lazy-load the sentence transformer model."""
        if self._embed_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                # all-MiniLM-L6-v2: 384 dims, ~80MB, very fast
                self._embed_model = SentenceTransformer("all-MiniLM-L6-v2")
                log.info("Sentence transformer loaded: all-MiniLM-L6-v2")
            except ImportError:
                log.warning("sentence-transformers not installed. Using ChromaDB default embeddings.")
                return None
        return self._embed_model

    def _embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a text string."""
        model = self._get_embedder()
        if model is None:
            return None  # ChromaDB will use its default embedder
        try:
            embedding = model.encode(text, normalize_embeddings=True)
            return embedding.tolist()
        except Exception as e:
            log.warning(f"Embedding failed: {e}")
            return None

    def _make_id(self, text: str) -> str:
        """Generate a deterministic ID from text to avoid duplicates."""
        return hashlib.md5(text.encode()).hexdigest()[:16]

    # ═══════════════════════════════════════════════════════════════════
    # Public API
    # ═══════════════════════════════════════════════════════════════════

    def store(
        self,
        text: str,
        metadata: Optional[dict] = None,
        doc_id: Optional[str] = None,
    ) -> bool:
        """Store a text with its embedding in vector memory.
        
        Args:
            text: The text to store (conversation turn, memory, fact, etc.)
            metadata: Optional metadata dict (type, timestamp, role, etc.)
            doc_id: Optional custom ID. Auto-generated from text hash if not provided.
        
        Returns:
            True if stored successfully, False otherwise.
        """
        if not self._lazy_init():
            return False

        if not text or len(text.strip()) < 3:
            return False

        doc_id = doc_id or self._make_id(text)
        meta = metadata or {}
        meta.setdefault("timestamp", time.time())
        meta.setdefault("type", "general")

        # Ensure all metadata values are strings/ints/floats (ChromaDB requirement)
        clean_meta = {}
        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                clean_meta[k] = v
            else:
                clean_meta[k] = str(v)

        try:
            embedding = self._embed(text)
            if embedding:
                self._collection.upsert(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[text],
                    metadatas=[clean_meta],
                )
            else:
                # Let ChromaDB handle embedding with its default model
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[text],
                    metadatas=[clean_meta],
                )
            return True
        except Exception as e:
            log.warning(f"Vector store failed: {e}")
            return False

    def search(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[dict] = None,
        min_score: float = 0.3,
    ) -> list[dict]:
        """Semantic search — find memories similar to the query.
        
        Args:
            query: Natural language query
            top_k: Number of results to return
            where: Optional ChromaDB filter dict (e.g., {"type": "preference"})
            min_score: Minimum cosine similarity threshold (0-1, higher = more relevant)
        
        Returns:
            List of {"text": str, "score": float, "metadata": dict}
        """
        if not self._lazy_init():
            return []

        if not query or len(query.strip()) < 2:
            return []

        try:
            embedding = self._embed(query)
            kwargs = {"n_results": top_k}
            if embedding:
                kwargs["query_embeddings"] = [embedding]
            else:
                kwargs["query_texts"] = [query]
            if where:
                kwargs["where"] = where

            results = self._collection.query(**kwargs)

            # Parse results
            items = []
            if results and results["documents"]:
                docs = results["documents"][0]
                distances = results["distances"][0] if results.get("distances") else [0] * len(docs)
                metadatas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)

                for doc, dist, meta in zip(docs, distances, metadatas):
                    # ChromaDB returns distance, convert to similarity score
                    # For cosine: similarity = 1 - distance
                    score = max(0, 1 - dist)
                    if score >= min_score:
                        items.append({
                            "text": doc,
                            "score": round(score, 3),
                            "metadata": meta,
                        })

            return items
        except Exception as e:
            log.warning(f"Vector search failed: {e}")
            return []

    def store_conversation_turn(
        self, role: str, content: str, turn_number: int = 0
    ) -> bool:
        """Store a conversation turn with appropriate metadata."""
        return self.store(
            text=content,
            metadata={
                "type": "conversation",
                "role": role,
                "turn": turn_number,
                "timestamp": time.time(),
            },
        )

    def store_memory(self, content: str, importance: str = "normal") -> bool:
        """Store an explicit memory/fact about the user."""
        return self.store(
            text=content,
            metadata={
                "type": "memory",
                "importance": importance,
                "timestamp": time.time(),
            },
        )

    def store_preference(self, content: str) -> bool:
        """Store a user preference."""
        return self.store(
            text=content,
            metadata={
                "type": "preference",
                "timestamp": time.time(),
            },
        )

    def search_conversations(self, query: str, top_k: int = 5) -> list[dict]:
        """Search only conversation history."""
        return self.search(query, top_k=top_k, where={"type": "conversation"})

    def search_memories(self, query: str, top_k: int = 5) -> list[dict]:
        """Search only stored memories/facts."""
        return self.search(query, top_k=top_k, where={"type": "memory"})

    def search_preferences(self, query: str, top_k: int = 5) -> list[dict]:
        """Search user preferences."""
        return self.search(query, top_k=top_k, where={"type": "preference"})

    def build_context(self, query: str, max_items: int = 8) -> str:
        """Build a formatted context string from semantic search results.
        
        This is designed to be injected into the LLM system prompt alongside
        the existing FTS5-based memory context.
        """
        results = self.search(query, top_k=max_items, min_score=0.35)
        if not results:
            return ""

        lines = ["SEMANTIC MEMORY (related past context):"]
        for r in results:
            meta = r["metadata"]
            type_tag = meta.get("type", "general")
            role = meta.get("role", "")
            score_pct = int(r["score"] * 100)

            if role:
                lines.append(f"  [{type_tag}/{role}] ({score_pct}%) {r['text'][:200]}")
            else:
                lines.append(f"  [{type_tag}] ({score_pct}%) {r['text'][:200]}")

        return "\n".join(lines)

    def get_stats(self) -> dict:
        """Get vector memory statistics."""
        if not self._lazy_init():
            return {"initialized": False, "error": self._init_error}

        try:
            count = self._collection.count()
            return {
                "initialized": True,
                "total_vectors": count,
                "persist_dir": self._persist_dir,
            }
        except Exception as e:
            return {"initialized": True, "error": str(e)}

    def clear(self) -> bool:
        """Clear all vectors. Use with caution."""
        if not self._lazy_init():
            return False
        try:
            # Delete and recreate collection
            import chromadb
            client = chromadb.PersistentClient(path=self._persist_dir)
            client.delete_collection("lis_memory")
            self._collection = client.create_collection(
                name="lis_memory",
                metadata={"hnsw:space": "cosine"},
            )
            log.info("Vector memory cleared.")
            return True
        except Exception as e:
            log.error(f"Vector memory clear failed: {e}")
            return False
