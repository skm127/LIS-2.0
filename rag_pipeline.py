"""
LIS RAG Pipeline — Unified Retrieval-Augmented Generation system.

Provides a single orchestrator for:
  1. Document INGESTION (files, URLs, raw text)
  2. Smart CHUNKING (semantic boundaries, overlap, metadata)
  3. EMBEDDING (sentence-transformers, batched)
  4. STORAGE (ChromaDB with typed collections)
  5. RETRIEVAL (hybrid: FTS5 keyword + vector similarity)
  6. RERANKING (Reciprocal Rank Fusion)
  7. CONTEXT BUILDING (formatted, attributed, LLM-ready)

Usage:
    from rag_pipeline import RAGPipeline

    rag = RAGPipeline()
    rag.ingest_file("my_doc.pdf")
    context = rag.build_augmented_context("What does the doc say about X?")
    # → inject `context` into LLM system prompt
"""

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger("lis.rag")

DATA_DIR = Path(__file__).parent / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"

# Default chunking parameters
DEFAULT_CHUNK_SIZE = 400       # words per chunk
DEFAULT_CHUNK_OVERLAP = 50     # word overlap between chunks
MIN_CHUNK_SIZE = 30            # minimum words to store a chunk


# ═══════════════════════════════════════════════════════════════════
# Data Models
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ChunkMetadata:
    """Metadata attached to each text chunk."""
    source: str = ""            # file path, URL, or "conversation"
    source_type: str = ""       # "file", "url", "text", "conversation"
    filename: str = ""
    chunk_index: int = 0
    total_chunks: int = 0
    page_number: int = 0        # for PDFs
    section_title: str = ""     # detected section header
    content_type: str = "document"  # "document", "conversation", "memory", "preference"
    ingested_at: float = 0.0

    def to_dict(self) -> dict:
        """Convert to ChromaDB-compatible metadata dict (only str/int/float/bool)."""
        return {
            "source": self.source,
            "source_type": self.source_type,
            "filename": self.filename,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "page_number": self.page_number,
            "section_title": self.section_title,
            "type": self.content_type,
            "ingested_at": self.ingested_at or time.time(),
        }


@dataclass
class RetrievalResult:
    """A single retrieval result with source attribution."""
    text: str
    score: float
    source: str = ""
    source_type: str = ""       # "vector", "fts", "hybrid"
    metadata: dict = field(default_factory=dict)
    retrieval_method: str = ""  # which search found this

    def __repr__(self) -> str:
        return f"RetrievalResult(score={self.score:.3f}, source={self.source!r}, text={self.text[:60]!r}...)"


@dataclass
class RAGContext:
    """Formatted context ready for LLM injection."""
    formatted_text: str         # The context string to inject
    results: list[RetrievalResult] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    total_results: int = 0
    search_time_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════
# Chunking
# ═══════════════════════════════════════════════════════════════════

def _detect_section_boundaries(text: str) -> list[int]:
    """Detect section/paragraph boundaries in text.

    Returns character positions where semantic boundaries occur.
    """
    boundaries = []
    # Markdown headers
    for m in re.finditer(r'^#{1,6}\s+', text, re.MULTILINE):
        boundaries.append(m.start())
    # Double newlines (paragraph breaks)
    for m in re.finditer(r'\n\s*\n', text):
        boundaries.append(m.start())
    # Numbered list items at start of line (new section)
    for m in re.finditer(r'^\d+\.\s', text, re.MULTILINE):
        boundaries.append(m.start())
    return sorted(set(boundaries))


def chunk_text_semantic(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    min_chunk_size: int = MIN_CHUNK_SIZE,
) -> list[dict]:
    """Split text into semantically-aware chunks with overlap.

    Tries to break at paragraph/section boundaries when possible,
    falls back to word-count splitting with overlap.

    Returns:
        List of {"text": str, "section_title": str, "start_char": int}
    """
    if not text or not text.strip():
        return []

    words = text.split()
    if len(words) <= chunk_size:
        return [{"text": text.strip(), "section_title": "", "start_char": 0}]

    boundaries = _detect_section_boundaries(text)
    chunks = []
    current_pos = 0
    current_section = ""

    # Detect current section title from headers
    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)

    max_iterations = len(text) // max(min_chunk_size, 1) + 10
    iteration = 0
    while current_pos < len(text):
        iteration += 1
        if iteration > max_iterations: break
        # Find the end of this chunk
        chunk_words = text[current_pos:].split()
        if len(chunk_words) <= chunk_size:
            chunk_text_str = text[current_pos:].strip()
            if len(chunk_text_str.split()) >= min_chunk_size:
                chunks.append({
                    "text": chunk_text_str,
                    "section_title": current_section,
                    "start_char": current_pos,
                })
            break

        # Take chunk_size words
        target_end = current_pos
        word_count = 0
        for i, char in enumerate(text[current_pos:]):
            if char in (' ', '\n', '\t'):
                word_count += 1
                if word_count >= chunk_size:
                    target_end = current_pos + i
                    break
        else:
            target_end = len(text)

        # Try to break at a semantic boundary near the target
        best_boundary = None
        search_start = max(current_pos, target_end - 200)
        search_end = min(len(text), target_end + 200)
        for b in boundaries:
            if search_start <= b <= search_end:
                if best_boundary is None or abs(b - target_end) < abs(best_boundary - target_end):
                    best_boundary = b

        if best_boundary is not None:
            end_pos = best_boundary
        else:
            end_pos = target_end

        chunk_text_str = text[current_pos:end_pos].strip()
        if len(chunk_text_str.split()) >= min_chunk_size:
            # Detect section title from any header in this chunk
            header_match = header_pattern.search(chunk_text_str)
            if header_match:
                current_section = header_match.group(2).strip()

            chunks.append({
                "text": chunk_text_str,
                "section_title": current_section,
                "start_char": current_pos,
            })

        # Move forward with overlap
        overlap_chars = 0
        word_count = 0
        for i in range(end_pos - 1, current_pos, -1):
            if text[i] in (' ', '\n', '\t'):
                word_count += 1
                if word_count >= chunk_overlap:
                    overlap_chars = end_pos - i
                    break

        previous_pos = current_pos
        current_pos = end_pos - overlap_chars
        if current_pos <= previous_pos:
            current_pos = end_pos  # Force forward progress

    return chunks


# ═══════════════════════════════════════════════════════════════════
# File Parsing
# ═══════════════════════════════════════════════════════════════════

def extract_text_from_file(filepath: str) -> tuple[str, dict]:
    """Extract text from a file based on its extension.

    Returns:
        (text, metadata_dict) where metadata has file-specific info
    """
    path = Path(filepath)
    ext = path.suffix.lower()
    metadata = {"filename": path.name, "source": str(path)}

    if ext == ".pdf":
        text = _extract_pdf(filepath)
        metadata["source_type"] = "pdf"
    elif ext == ".docx":
        text = _extract_docx(filepath)
        metadata["source_type"] = "docx"
    elif ext in (".html", ".htm"):
        text = _extract_html_file(filepath)
        metadata["source_type"] = "html"
    elif ext in (".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
                 ".csv", ".log", ".cfg", ".ini", ".toml", ".xml", ".rst"):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="latin-1")
        metadata["source_type"] = "text"
    else:
        log.warning(f"Unsupported file type: {ext}")
        return "", metadata

    return text, metadata


def _extract_pdf(filepath: str) -> str:
    """Extract text from PDF file."""
    try:
        import PyPDF2
        text_parts = []
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"[Page {i+1}]\n{page_text}")
        return "\n\n".join(text_parts)
    except ImportError:
        log.warning("PyPDF2 not installed. Run: pip install PyPDF2")
        return ""
    except Exception as e:
        log.error(f"PDF extraction failed for {filepath}: {e}")
        return ""


def _extract_docx(filepath: str) -> str:
    """Extract text from DOCX file."""
    try:
        from docx import Document
        doc = Document(filepath)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except ImportError:
        log.warning("python-docx not installed. Run: pip install python-docx")
        return ""
    except Exception as e:
        log.error(f"DOCX extraction failed for {filepath}: {e}")
        return ""


def _extract_html_file(filepath: str) -> str:
    """Extract text from HTML file."""
    try:
        from bs4 import BeautifulSoup
        with open(filepath, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
        # Remove script/style elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        return soup.get_text(separator='\n', strip=True)
    except ImportError:
        log.warning("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        # Fallback: strip HTML tags with regex
        with open(filepath, 'r', encoding='utf-8') as f:
            html = f.read()
        return re.sub(r'<[^>]+>', ' ', html)
    except Exception as e:
        log.error(f"HTML extraction failed for {filepath}: {e}")
        return ""


async def extract_text_from_url(url: str) -> tuple[str, dict]:
    """Fetch and extract text from a URL.

    Returns:
        (text, metadata_dict)
    """
    metadata = {"source": url, "source_type": "url", "filename": url.split("/")[-1] or url}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 LIS-Bot"})
            if resp.status_code != 200:
                log.warning(f"URL fetch failed: {resp.status_code} for {url}")
                return "", metadata

            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
                        tag.decompose()
                    # Try to get the main content
                    main = soup.find('main') or soup.find('article') or soup.find('body')
                    text = main.get_text(separator='\n', strip=True) if main else soup.get_text(separator='\n', strip=True)
                except ImportError:
                    text = re.sub(r'<[^>]+>', ' ', resp.text)
            else:
                text = resp.text

            return text, metadata
    except Exception as e:
        log.error(f"URL extraction failed for {url}: {e}")
        return "", metadata


# ═══════════════════════════════════════════════════════════════════
# RAG Pipeline
# ═══════════════════════════════════════════════════════════════════

class RAGPipeline:
    """Unified RAG orchestrator for LIS.

    Coordinates ingestion, chunking, embedding, storage, retrieval,
    reranking, and context generation.
    """

    def __init__(self, vector_memory=None, memory_module=None):
        """Initialize the RAG pipeline.

        Args:
            vector_memory: VectorMemory instance (lazy-created if None)
            memory_module: The memory module for FTS5 access (lazy-imported if None)
        """
        self._vmem = vector_memory
        self._memory = memory_module
        self._ingestion_log: list[dict] = []  # Track what's been ingested

    def _get_vmem(self):
        """Lazy-load VectorMemory."""
        if self._vmem is None:
            from vector_memory import VectorMemory
            self._vmem = VectorMemory()
        return self._vmem

    def _get_memory(self):
        """Lazy-load memory module."""
        if self._memory is None:
            import memory as _mem
            self._memory = _mem
        return self._memory

    # ═══════════════════════════════════════════════════════════════
    # Ingestion
    # ═══════════════════════════════════════════════════════════════

    def ingest_file(self, filepath: str) -> dict:
        """Ingest a file into the RAG pipeline.

        Extracts text, chunks it semantically, embeds, and stores in ChromaDB.

        Args:
            filepath: Path to the file to ingest

        Returns:
            {"success": bool, "chunks": int, "source": str, "error": str}
        """
        filepath = str(Path(filepath).resolve())

        # Check if already ingested (by source path)
        vmem = self._get_vmem()
        existing = vmem.get_all_sources()
        if filepath in existing:
            log.info(f"File already indexed, re-indexing: {filepath}")
            vmem.delete_by_source(filepath)

        # Extract text
        text, file_meta = extract_text_from_file(filepath)
        if not text or len(text.strip()) < 20:
            return {"success": False, "chunks": 0, "source": filepath,
                    "error": "No text extracted or file too short"}

        # Chunk
        chunks = chunk_text_semantic(text)
        if not chunks:
            return {"success": False, "chunks": 0, "source": filepath,
                    "error": "Chunking produced no results"}

        # Store each chunk
        stored = 0
        for i, chunk in enumerate(chunks):
            meta = ChunkMetadata(
                source=filepath,
                source_type=file_meta.get("source_type", "file"),
                filename=file_meta.get("filename", ""),
                chunk_index=i,
                total_chunks=len(chunks),
                section_title=chunk.get("section_title", ""),
                content_type="document",
                ingested_at=time.time(),
            )
            # Generate a unique ID based on source + chunk index
            doc_id = hashlib.sha256(
                f"{filepath}::chunk::{i}".encode()
            ).hexdigest()[:24]

            success = vmem.store(
                text=chunk["text"],
                metadata=meta.to_dict(),
                doc_id=doc_id,
            )
            if success:
                stored += 1

        self._ingestion_log.append({
            "source": filepath,
            "type": "file",
            "chunks": stored,
            "timestamp": time.time(),
        })

        log.info(f"Ingested {filepath}: {stored}/{len(chunks)} chunks stored")
        return {"success": True, "chunks": stored, "source": filepath, "error": ""}

    async def ingest_url(self, url: str) -> dict:
        """Ingest a web page into the RAG pipeline.

        Args:
            url: URL to fetch and ingest

        Returns:
            {"success": bool, "chunks": int, "source": str, "error": str}
        """
        text, url_meta = await extract_text_from_url(url)
        if not text or len(text.strip()) < 20:
            return {"success": False, "chunks": 0, "source": url,
                    "error": "No text extracted from URL"}

        # Chunk
        chunks = chunk_text_semantic(text)
        if not chunks:
            return {"success": False, "chunks": 0, "source": url,
                    "error": "Chunking produced no results"}

        # Store
        vmem = self._get_vmem()
        stored = 0
        for i, chunk in enumerate(chunks):
            meta = ChunkMetadata(
                source=url,
                source_type="url",
                filename=url_meta.get("filename", url),
                chunk_index=i,
                total_chunks=len(chunks),
                section_title=chunk.get("section_title", ""),
                content_type="document",
                ingested_at=time.time(),
            )
            doc_id = hashlib.sha256(
                f"{url}::chunk::{i}".encode()
            ).hexdigest()[:24]

            success = vmem.store(
                text=chunk["text"],
                metadata=meta.to_dict(),
                doc_id=doc_id,
            )
            if success:
                stored += 1

        self._ingestion_log.append({
            "source": url,
            "type": "url",
            "chunks": stored,
            "timestamp": time.time(),
        })

        log.info(f"Ingested URL {url}: {stored}/{len(chunks)} chunks stored")
        return {"success": True, "chunks": stored, "source": url, "error": ""}

    def ingest_text(self, text: str, source: str = "direct_input",
                    content_type: str = "document") -> dict:
        """Ingest raw text into the RAG pipeline.

        Args:
            text: Text content to ingest
            source: Source identifier
            content_type: Type tag ("document", "note", "knowledge")

        Returns:
            {"success": bool, "chunks": int, "source": str, "error": str}
        """
        if not text or len(text.strip()) < 10:
            return {"success": False, "chunks": 0, "source": source,
                    "error": "Text too short"}

        chunks = chunk_text_semantic(text)
        vmem = self._get_vmem()
        stored = 0
        for i, chunk in enumerate(chunks):
            meta = ChunkMetadata(
                source=source,
                source_type="text",
                chunk_index=i,
                total_chunks=len(chunks),
                section_title=chunk.get("section_title", ""),
                content_type=content_type,
                ingested_at=time.time(),
            )
            doc_id = hashlib.sha256(
                f"{source}::chunk::{i}::{text[:50]}".encode()
            ).hexdigest()[:24]

            success = vmem.store(
                text=chunk["text"],
                metadata=meta.to_dict(),
                doc_id=doc_id,
            )
            if success:
                stored += 1

        return {"success": True, "chunks": stored, "source": source, "error": ""}

    def ingest_directory(self, directory_path: str,
                         extensions: list[str] = None) -> dict:
        """Ingest all supported files in a directory (recursive).

        Args:
            directory_path: Path to directory to scan
            extensions: File extensions to include (default: common text/doc types)

        Returns:
            {"success": bool, "files_indexed": int, "total_chunks": int, "errors": list}
        """
        if extensions is None:
            extensions = ['.txt', '.md', '.py', '.json', '.csv', '.pdf', '.docx',
                          '.html', '.htm', '.yaml', '.yml', '.rst']

        ignore_dirs = {'.git', '__pycache__', 'node_modules', 'venv', '.venv',
                       '.gemini', 'dist', '.pytest_cache', 'chroma_db'}

        files_indexed = 0
        total_chunks = 0
        errors = []

        for root, dirs, files in os.walk(directory_path):
            # Skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]

            for filename in files:
                ext = Path(filename).suffix.lower()
                if ext not in extensions:
                    continue

                filepath = os.path.join(root, filename)
                try:
                    result = self.ingest_file(filepath)
                    if result["success"]:
                        files_indexed += 1
                        total_chunks += result["chunks"]
                    elif result.get("error"):
                        errors.append(f"{filename}: {result['error']}")
                except Exception as e:
                    errors.append(f"{filename}: {str(e)}")
                    log.error(f"Failed to ingest {filepath}: {e}")

        log.info(f"Directory ingestion complete: {files_indexed} files, {total_chunks} chunks")
        return {
            "success": files_indexed > 0,
            "files_indexed": files_indexed,
            "total_chunks": total_chunks,
            "errors": errors[:20],  # Cap error list
        }

    # ═══════════════════════════════════════════════════════════════
    # Retrieval (Hybrid Search)
    # ═══════════════════════════════════════════════════════════════

    def query(
        self,
        question: str,
        top_k: int = 8,
        content_type: Optional[str] = None,
        min_score: float = 0.25,
        use_hybrid: bool = True,
    ) -> list[RetrievalResult]:
        """Retrieve relevant context using hybrid search.

        Combines:
        1. Vector similarity search (ChromaDB, cosine distance)
        2. FTS5 keyword search (SQLite full-text)
        3. Reciprocal Rank Fusion (RRF) to merge rankings

        Args:
            question: Natural language query
            top_k: Number of results to return
            content_type: Optional filter ("document", "conversation", "memory")
            min_score: Minimum relevance threshold
            use_hybrid: If True, use hybrid search. If False, vector-only.

        Returns:
            Sorted list of RetrievalResult
        """
        start = time.time()
        vmem = self._get_vmem()

        if not question or len(question.strip()) < 2:
            return []

        K = 60  # RRF constant
        scored: dict[str, dict] = {}

        # 1. Vector similarity search
        where_filter = {"type": content_type} if content_type else None
        vector_results = vmem.search(
            query=question,
            top_k=top_k * 2,  # Fetch more for fusion
            where=where_filter,
            min_score=0.2,  # Lower threshold — RRF will filter
        )

        for rank, r in enumerate(vector_results):
            text_key = r["text"][:200]
            rrf_score = 0.6 / (K + rank + 1)
            scored[text_key] = {
                "text": r["text"],
                "score": rrf_score,
                "metadata": r.get("metadata", {}),
                "source": r.get("metadata", {}).get("source", ""),
                "methods": ["vector"],
                "vector_score": r.get("score", 0),
            }

        # 2. FTS5 keyword search (if hybrid enabled)
        if use_hybrid:
            try:
                mem = self._get_memory()
                fts_results = mem.recall(question, limit=top_k * 2)
                for rank, r in enumerate(fts_results):
                    text_key = r.get("content", "")[:200]
                    rrf_score = 0.4 / (K + rank + 1)

                    if text_key in scored:
                        scored[text_key]["score"] += rrf_score
                        scored[text_key]["methods"].append("fts")
                    else:
                        scored[text_key] = {
                            "text": r.get("content", ""),
                            "score": rrf_score,
                            "metadata": {"type": r.get("type", "memory")},
                            "source": r.get("source", "fts5"),
                            "methods": ["fts"],
                            "vector_score": 0,
                        }
            except Exception as e:
                log.debug(f"FTS search skipped: {e}")

        # 3. Sort by combined RRF score
        results = sorted(scored.values(), key=lambda x: x["score"], reverse=True)

        elapsed = (time.time() - start) * 1000  # ms
        log.debug(f"RAG query took {elapsed:.1f}ms, found {len(results)} results")

        # 4. Convert to RetrievalResult
        return [
            RetrievalResult(
                text=r["text"],
                score=round(r["score"], 4),
                source=r.get("source", ""),
                source_type="+".join(r["methods"]),
                metadata=r.get("metadata", {}),
                retrieval_method="hybrid" if len(r["methods"]) > 1 else r["methods"][0],
            )
            for r in results[:top_k]
        ]

    # ═══════════════════════════════════════════════════════════════
    # Context Building (LLM-ready output)
    # ═══════════════════════════════════════════════════════════════

    def build_augmented_context(
        self,
        user_query: str,
        max_items: int = 6,
        max_chars: int = 2000,
        include_sources: bool = True,
    ) -> RAGContext:
        """Build formatted context for LLM injection with source attribution.

        This is the main entry point for augmenting LLM prompts with
        retrieved knowledge.

        Args:
            user_query: The user's question/request
            max_items: Maximum number of context items
            max_chars: Maximum total characters in context
            include_sources: Whether to show source attribution

        Returns:
            RAGContext with formatted text and metadata
        """
        start = time.time()
        results = self.query(user_query, top_k=max_items)

        if not results:
            return RAGContext(
                formatted_text="",
                results=[],
                sources_used=[],
                total_results=0,
                search_time_ms=0,
            )

        lines = ["RAG CONTEXT (relevant retrieved knowledge):"]
        sources_used = set()
        total_chars = 0

        for r in results:
            # Source attribution tag
            source_tag = ""
            if include_sources and r.source:
                source_name = Path(r.source).name if "/" in r.source or "\\" in r.source else r.source
                source_tag = f" [from: {source_name}]"
                sources_used.add(r.source)

            # Method tag
            method_tag = f"({r.retrieval_method})" if r.retrieval_method else ""

            # Truncate text if needed
            text = r.text[:300] if len(r.text) > 300 else r.text
            text = text.replace("\n", " ").strip()

            line = f"  • {method_tag} {text}{source_tag}"
            if total_chars + len(line) > max_chars:
                break
            lines.append(line)
            total_chars += len(line)

        elapsed = (time.time() - start) * 1000

        return RAGContext(
            formatted_text="\n".join(lines),
            results=results,
            sources_used=sorted(sources_used),
            total_results=len(results),
            search_time_ms=round(elapsed, 1),
        )

    # ═══════════════════════════════════════════════════════════════
    # Management
    # ═══════════════════════════════════════════════════════════════

    def get_sources(self) -> list[str]:
        """List all indexed document sources."""
        return self._get_vmem().get_all_sources()

    def delete_source(self, source_path: str) -> int:
        """Remove all chunks from a source. Returns count deleted."""
        return self._get_vmem().delete_by_source(source_path)

    def get_stats(self) -> dict:
        """Get RAG pipeline statistics."""
        vmem_stats = self._get_vmem().get_stats()
        return {
            "vector_memory": vmem_stats,
            "sources_indexed": len(self.get_sources()),
            "ingestion_log": self._ingestion_log[-10:],  # Last 10
        }

    def clear_all(self) -> bool:
        """Clear all RAG data. Use with caution."""
        return self._get_vmem().clear()

    def already_has(self, content_hash: str) -> bool:
        """Check if a chunk with this content hash already exists."""
        return self._get_vmem().already_has(content_hash)

    def delete_by_domain(self, domain: str) -> int:
        """Delete all vectors matching a specific source domain."""
        return self._get_vmem().delete_by_domain(domain)

    def add(self, chunk: dict) -> bool:
        """Add a single pre-chunked dictionary to the vector store.
        chunk must have 'text' and 'metadata'.
        """
        doc_id = chunk.get("doc_id")
        return self._get_vmem().store(
            text=chunk["text"],
            metadata=chunk.get("metadata", {}),
            doc_id=doc_id
        )
