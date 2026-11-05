import os

from sqlalchemy import Column, Integer, LargeBinary, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mastermind.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine_options = {"pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite:"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Application(Base):
    """Legacy upload metadata; kept so existing installations remain readable."""

    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, index=True)
    service_name = Column(String, index=True)
    mobile = Column(String, index=True)
    description = Column(String)
    file_url = Column(String)
    unique_id = Column(String, unique=True, index=True)
    status = Column(String, default="Pending")


class PortalRecord(Base):
    """A server-side record for every submitted service/print request."""

    __tablename__ = "portal_records"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True, nullable=False)
    payload = Column(Text, nullable=False)
    status = Column(String, default="Pending", nullable=False)


class StoredFile(Base):
    __tablename__ = "stored_files"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=False)
    content = Column(LargeBinary, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    mobile = Column(String, unique=True, index=True)
    email = Column(String, index=True)
    password = Column(String)
    status = Column(String, default="Active")


def init_db():
    Base.metadata.create_all(bind=engine)
