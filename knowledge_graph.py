import networkx as nx
import logging
from pathlib import Path
import json

log = logging.getLogger("lis.graph")

class KnowledgeGraph:
    """LIS 4.0 Procedural Memory Palace."""
    def __init__(self, db_path: str = "lis_graph.json"):
        self.db_path = Path(db_path)
        self.graph = nx.DiGraph()
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                data = json.loads(self.db_path.read_text())
                self.graph = nx.node_link_graph(data)
                log.info(f"Loaded Knowledge Graph with {len(self.graph.nodes)} nodes.")
            except Exception as e:
                log.error(f"Failed to load Knowledge Graph: {e}")

    def _save(self):
        try:
            data = nx.node_link_data(self.graph)
            self.db_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            log.error(f"Failed to save Knowledge Graph: {e}")

    def add_relation(self, subject: str, predicate: str, obj: str):
        """Add a relationship e.g., ('User', 'likes', 'Coffee')"""
        subject = subject.lower().strip()
        obj = obj.lower().strip()
        
        if not self.graph.has_node(subject):
            self.graph.add_node(subject)
        if not self.graph.has_node(obj):
            self.graph.add_node(obj)
            
        self.graph.add_edge(subject, obj, relation=predicate)
        self._save()

    def query(self, entity: str) -> list[str]:
        """Find all relationships for an entity."""
        entity = entity.lower().strip()
        if not self.graph.has_node(entity):
            return []
            
        results = []
        for successor in self.graph.successors(entity):
            rel = self.graph.edges[entity, successor]['relation']
            results.append(f"{entity} {rel} {successor}")
            
        for predecessor in self.graph.predecessors(entity):
            rel = self.graph.edges[predecessor, entity]['relation']
            results.append(f"{predecessor} {rel} {entity}")
            
        return results

# Global instance
kg = KnowledgeGraph()
