from sqlmodel import create_engine, Session

DATABASE_URL = "sqlite:///./inventory.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def get_session():
    with Session(engine) as session:
        yield session
