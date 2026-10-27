from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.databases.internal.index_state import get_or_create_index_state
from src.databases.internal.models import KnowledgeIndexState


def test_index_state_is_isolated_per_source_type():
    engine = create_engine("sqlite://")
    KnowledgeIndexState.__table__.create(engine)
    session = sessionmaker(bind=engine)()

    faq_state = get_or_create_index_state(session, "faq")
    document_state = get_or_create_index_state(session, "document")
    faq_state.active_version = 7
    faq_state.next_version = 8
    session.commit()

    reloaded_faq = get_or_create_index_state(session, "faq")
    reloaded_document = get_or_create_index_state(session, "document")

    assert reloaded_faq.active_version == 7
    assert reloaded_faq.next_version == 8
    assert reloaded_document.active_version == 0
    assert reloaded_document.next_version == 1
    session.close()
