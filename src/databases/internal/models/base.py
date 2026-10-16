from sqlalchemy.orm import declarative_base

Base = declarative_base()


def init_db(engine=None):
    from src.databases.internal.store import initialize_schema
    initialize_schema(engine=engine)
