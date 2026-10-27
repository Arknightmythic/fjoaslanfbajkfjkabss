from sqlalchemy.orm import Session

from src.databases.internal.models import KnowledgeIndexState
from src.knowledge.source_types import normalize_source_type


def get_or_create_index_state(
    session: Session,
    source_type: str,
    *,
    for_update: bool = False,
) -> KnowledgeIndexState:
    """Return the version pointer for a source type, creating it on first use."""
    resolved = normalize_source_type(source_type)
    state = session.get(KnowledgeIndexState, resolved, with_for_update=for_update)
    if state is None:
        state = KnowledgeIndexState(source_type=resolved)
        session.add(state)
        session.flush()
    return state
