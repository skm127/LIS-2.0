from skills import Skill, SkillResult, registry
import asyncio
import logging
import time
import json
import difflib
import subprocess
import re
import memory
from typing import Optional, List, Dict, Callable, Any

log = logging.getLogger("LIS.plugins")

class LocalDocumentSearchSkill(Skill):
    name = "search_documents"
    description = "Semantically search the user's local documents, PDFs, and codebases for specific information."

    async def execute(self, query: str, **kwargs) -> SkillResult:
        try:
            from vector_memory import VectorMemory
            vmem = VectorMemory()
            results = vmem.search(query, top_k=5)
            
            if not results:
                return SkillResult(False, "No relevant documents found.")
                
            # Format results
            snippets = []
            for r in results:
                meta = r.get("metadata", {})
                source = meta.get("filename", "Unknown Document")
                score = r.get("score", 0)
                # Ensure the text is brief to not overflow context
                text = r.get("text", "")[:500]
                snippets.append(f"Source [{source}] (Relevance {int(score*100)}%):\n{text}...")
                
            combined = "\n\n".join(snippets)
            return SkillResult(True, f"Found relevant information in local documents:\n{combined}")
        except Exception as e:
            return SkillResult(False, f"Document search failed: {e}")
registry.register(LocalDocumentSearchSkill())

class KnowledgeGraphSkill(Skill):
    """
    Maps entities to a procedural knowledge graph or queries it.
    action: 'add' or 'query'
    """
    name = "knowledge_graph"
    description = "Adds or queries relationships in the memory palace. Actions: 'add', 'query'. Provide subject, predicate, obj for 'add'. Provide entity for 'query'."

    async def execute(self, action: str, subject: str = "", predicate: str = "", obj: str = "", entity: str = "", **kwargs) -> SkillResult:
        try:
            from knowledge_graph import get_kg
            kg = get_kg()
            
            if action == "add":
                if not (subject and predicate and obj):
                    return SkillResult(False, "Missing subject, predicate, or object for adding to graph.")
                kg.add_relation(subject, predicate, obj)
                return SkillResult(True, f"Added relationship: {subject} {predicate} {obj}")
                
            elif action == "query":
                if not entity:
                    return SkillResult(False, "Missing entity to query.")
                results = kg.query(entity)
                if not results:
                    return SkillResult(False, f"I don't know anything about {entity}.")
                return SkillResult(True, f"Knowledge about {entity}:\n" + "\n".join(results))
                
            return SkillResult(False, "Invalid action. Use 'add' or 'query'.")
        except ImportError:
            return SkillResult(False, "knowledge_graph.py module not found or networkx missing.")
        except Exception as e:
            return SkillResult(False, f"Knowledge Graph operation failed: {e}")
registry.register(KnowledgeGraphSkill())

