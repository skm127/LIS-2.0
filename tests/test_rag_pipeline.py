import pytest
from rag_pipeline import RAGPipeline, chunk_text_semantic

def test_chunk_text_semantic():
    text = "This is a short test sentence. " * 50
    chunks = chunk_text_semantic(text, chunk_size=20, chunk_overlap=5, min_chunk_size=10)
    assert len(chunks) > 1
    assert "test sentence" in chunks[0]["text"]

def test_rag_pipeline_init():
    rag = RAGPipeline()
    assert rag is not None
    assert hasattr(rag, 'query')
    assert hasattr(rag, 'ingest_text')
