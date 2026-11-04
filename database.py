from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./mastermind_portal.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String)
    service_name = Column(String)
    mobile = Column(String)
    description = Column(String)
    file_url = Column(String)
    unique_id = Column(String)

def init_db():
    Base.metadata.create_all(bind=engine)