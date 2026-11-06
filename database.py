import os
from sqlalchemy import create_engine, Column, Integer, String, Text, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

def normalize_database_url(url: str) -> str:
    # Neon/Render dashboards commonly provide postgres:// or postgresql:// URLs.
    # This project installs psycopg v3, so select its SQLAlchemy dialect explicitly.
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./mastermind.db"))
if os.getenv("REQUIRE_EXTERNAL_DATABASE", "false").lower() == "true" and (not DATABASE_URL or DATABASE_URL.startswith("sqlite")):
    raise RuntimeError("Free hosting requires an external PostgreSQL DATABASE_URL; local SQLite is ephemeral and unsafe.")
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


class PrintQueue(Base):
    __tablename__ = "print_queue"
    id = Column(Integer, primary_key=True, index=True)
    owner_mobile = Column(String, index=True, nullable=False)
    customer_name = Column(String, nullable=False)
    print_type = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    application_ids = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Pending")
    created_at = Column(String, nullable=False)


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    id = Column(Integer, primary_key=True, index=True)
    owner_mobile = Column(String, index=True, nullable=False)
    customer_name = Column(String, nullable=False)
    service_name = Column(String, nullable=False)
    description = Column(String, nullable=False, default="")
    form_data = Column(Text, nullable=False, default="{}")
    application_ids = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="Pending")
    created_at = Column(String, nullable=False)
