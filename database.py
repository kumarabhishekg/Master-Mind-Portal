import os
from sqlalchemy import create_engine, Column, Integer, String, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mastermind.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, index=True)
    service_name = Column(String, index=True)
    mobile = Column(String, index=True)
    description = Column(String)
    file_url = Column(String)
    unique_id = Column(String, unique=True, index=True)
    status = Column(String, default="Pending")

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    mobile = Column(String, unique=True, index=True)
    email = Column(String, index=True)
    password = Column(String)  # Existing column retained; now stores scrypt hashes only.
    status = Column(String, default="Active")
    role = Column(String, nullable=False, default="user")

def init_db():
    Base.metadata.create_all(bind=engine)
    # Safe additive migration for existing SQLite databases.
    if DATABASE_URL.startswith("sqlite"):
        columns = {c["name"] for c in inspect(engine).get_columns("users")}
        if "role" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR NOT NULL DEFAULT 'user'"))

init_db()

class IssuedDocument(Base):
    __tablename__ = "issued_documents"
    id = Column(Integer, primary_key=True, index=True)
    target_mobile = Column(String, index=True, nullable=False)
    title = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_url = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
