from sqlalchemy.orm import declarative_base

Base = declarative_base()


def init_db(engine=None):
    if engine is None:
        from src.databases.internal.config import engine as default_engine

        engine = default_engine
    Base.metadata.create_all(bind=engine)
