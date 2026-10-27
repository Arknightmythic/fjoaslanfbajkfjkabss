"""Knowledge ingestion and retrieval services, imported lazily to avoid cycles."""

__all__ = ["Ingestor", "clean_markdown", "KnowledgeRetriever"]


def __getattr__(name):
    if name == "Ingestor":
        from src.knowledge.ingestor import Ingestor

        return Ingestor
    if name == "clean_markdown":
        from src.knowledge.parser import clean_markdown

        return clean_markdown
    if name == "KnowledgeRetriever":
        from src.knowledge.retriever import KnowledgeRetriever

        return KnowledgeRetriever
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
