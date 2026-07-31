"""
LIS Autonomous Learner Vector Store

Provides a dedicated persistent vector database (ChromaDB) for knowledge
ingested by the background autonomous learner. 
Strictly separates learner knowledge from live assistant context to prevent
colliding or polluting the main memory databases.
"""

import logging
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import chromadb
    from chromadb.config import Settings
except ImportError:
    chromadb = None

log = logging.getLogger("lis.learner_store")

DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = DATA_DIR / "learner_chroma_db"
COLLECTION_NAME = "learner_knowledge"

class LearnerVectorStore:
    def __init__(self):
        self._client = None
        self._collection = None
        
        if not chromadb:
            log.error("chromadb is not installed. Autonomous Learner store disabled.")
            return
            
        try:
            DATA_DIR.mkdir(exist_ok=True, parents=True)
            self._client = chromadb.PersistentClient(
                path=str(CHROMA_DIR),
                settings=Settings(anonymized_telemetry=False)
            )
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            log.info(f"Learner vector store initialized at {CHROMA_DIR}")
        except Exception as e:
            log.error(f"Failed to initialize Learner Vector Store: {e}")

    def is_ready(self) -> bool:
        return self._collection is not None

    def prune_old_documents(self, max_docs: int = 2000, incoming_docs_count: int = 1):
        """
        Ensures the vector store never exceeds `max_docs` size mid-ingest.
        Should be called BEFORE adding `incoming_docs_count` new documents.
        """
        if not self.is_ready():
            return
            
        try:
            count = self._collection.count()
            target_count = max_docs - incoming_docs_count
            
            if count <= target_count:
                return # We have space
                
            num_to_delete = count - target_count
            log.info(f"Pruning {num_to_delete} old documents to stay under {max_docs} max docs limit.")
            
            # Fetch all documents to sort by ingested_at
            # Note: ChromaDB doesn't have native sorted queries, so we must fetch metadata
            all_docs = self._collection.get(include=["metadatas"])
            if not all_docs or not all_docs["ids"]:
                return
                
            docs = []
            for i, doc_id in enumerate(all_docs["ids"]):
                meta = all_docs["metadatas"][i] or {}
                ingested_at = meta.get("ingested_at", 0)
                docs.append((doc_id, ingested_at))
                
            # Sort by ingested_at ascending (oldest first)
            docs.sort(key=lambda x: x[1])
            
            # Delete the oldest num_to_delete
            ids_to_delete = [d[0] for d in docs[:num_to_delete]]
            if ids_to_delete:
                self._collection.delete(ids=ids_to_delete)
                log.info(f"Successfully deleted {len(ids_to_delete)} old documents.")
                
        except Exception as e:
            log.error(f"Failed to prune old documents: {e}")

    def add_documents(self, texts: List[str], metadatas: List[Dict[str, Any]], ids: List[str], max_docs: int = 2000):
        """Add new knowledge chunks to the vector store."""
        if not self.is_ready() or not texts:
            return False
            
        # Prune first to ensure we don't exceed max_docs
        self.prune_old_documents(max_docs=max_docs, incoming_docs_count=len(texts))
        
        try:
            # Clean metadatas (Chroma requires str, int, float, bool)
            clean_metadatas = []
            for m in metadatas:
                clean_m = {}
                for k, v in m.items():
                    if isinstance(v, (str, int, float, bool)):
                        clean_m[k] = v
                    else:
                        clean_m[k] = str(v)
                clean_metadatas.append(clean_m)

            self._collection.add(
                documents=texts,
                metadatas=clean_metadatas,
                ids=ids
            )
            log.info(f"Added {len(texts)} chunks to learner store.")
            return True
        except Exception as e:
            log.error(f"Failed to add documents to learner store: {e}")
            return False

    def get_recent_topics(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return a list of recently learned topics/URLs for the UI."""
        if not self.is_ready():
            return []
            
        try:
            results = self._collection.get(include=["metadatas"])
            if not results or not results["metadatas"]:
                return []
                
            # Deduplicate by source_url and topic
            unique_sources = {}
            for meta in results["metadatas"]:
                if not meta:
                    continue
                url = meta.get("source_url", "")
                topic = meta.get("topic", "")
                ingested = meta.get("ingested_at", 0)
                
                key = f"{topic}::{url}"
                if key not in unique_sources or unique_sources[key]["ingested_at"] < ingested:
                    unique_sources[key] = {
                        "topic": topic,
                        "url": url,
                        "ingested_at": ingested
                    }
                    
            # Sort by ingested_at descending
            sorted_sources = sorted(unique_sources.values(), key=lambda x: x["ingested_at"], reverse=True)
            return sorted_sources[:limit]
            
        except Exception as e:
            log.error(f"Failed to get recent topics: {e}")
            return []

    def get_all_learned_topics(self) -> List[str]:
        """Return just a list of topics already researched to avoid duplication."""
        if not self.is_ready():
            return []
        try:
            results = self._collection.get(include=["metadatas"])
            if not results or not results["metadatas"]:
                return []
            topics = set()
            for meta in results["metadatas"]:
                if meta and "topic" in meta:
                    topics.add(meta["topic"].lower())
            return list(topics)
        except Exception:
            return []

    def delete_by_url(self, url: str) -> bool:
        """Delete all chunks originating from a specific URL."""
        if not self.is_ready():
            return False
            
        try:
            self._collection.delete(where={"source_url": url})
            log.info(f"Deleted all knowledge chunks for URL: {url}")
            return True
        except Exception as e:
            log.error(f"Failed to delete by URL: {e}")
            return False
            
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search the learned knowledge."""
        if not self.is_ready():
            return []
            
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=limit,
                include=["documents", "metadatas", "distances"]
            )
            
            if not results["documents"] or not results["documents"][0]:
                return []
                
            hits = []
            for i in range(len(results["documents"][0])):
                doc = results["documents"][0][i]
                meta = results["metadatas"][0][i] if results["metadatas"] else {}
                dist = results["distances"][0][i] if results["distances"] else 0.0
                
                hits.append({
                    "text": doc,
                    "metadata": meta,
                    "score": 1.0 - min(dist, 1.0)
                })
            return hits
        except Exception as e:
            log.error(f"Search failed on learner store: {e}")
            return []
