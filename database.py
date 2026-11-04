from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./mastermind.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    password = Column(String)
    status = Column(String, default="Active")

def init_db():
    Base.metadata.create_all(bind=engine)