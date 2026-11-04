from fastapi import FastAPI, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
import shutil
import os
import uuid

# database.py से इम्पोर्ट करें
from database import engine, SessionLocal, Base, Application, init_db

# टेबल पहले से मौजूद नहीं है तो क्रिएट करें
Base.metadata.create_all(bind=engine)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "mastermind_storage"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# फाइलों और स्टोरेज के लिए mount
app.mount("/storage", StaticFiles(directory=UPLOAD_DIR), name="storage")

# Dependency डेटाबेस सेशन के लिए
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 1. मुख्य होमपेज लोड करने के लिए
@app.get("/")
def serve_home():
    return FileResponse("HOME.html")

# 2. फाइल अपलोड एपीआई
@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    customer_name: str = Form(...),
    service_name: str = Form(...),
    mobile: str = Form("Not Provided"),
    description: str = Form(""),
    db: Session = Depends(get_db)
):
    try:
        unique_id = str(uuid.uuid4())
        file_ext = os.path.splitext(file.filename)[1]
        unique_filename = f"{unique_id}{file_ext}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_url = f"https://master-mind-portal.onrender.com/storage/{unique_filename}"
        
        # डेटाबेस में सेव करें
        new_application = Application(
            customer_name=customer_name,
            service_name=service_name,
            mobile=mobile,
            description=description,
            file_url=file_url,
            unique_id=unique_id
        )
        db.add(new_application)
        db.commit()
        db.refresh(new_application)
        
        return {
            "status": "success",
            "unique_id": unique_id,
            "filename": file.filename,
            "file_url": file_url,
            "message": "File and data successfully saved!"
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}

# 3. स्मार्ट कैच-ऑल रूट: सभी images, folders (banking, GST, treveling) और .html pages को automatically serve करेगा
@app.get("/{file_path:path}")
def serve_files_and_pages(file_path: str):
    if ".." in file_path:
        return JSONResponse(status_code=400, content={"message": "Invalid path"})
    
    # Agar file direct maujood hai (jaise caste.png, banking/aeps.png, login.html)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
        
    # Agar .html lagana bhul gaye hon
    html_path = f"{file_path}.html"
    if os.path.exists(html_path) and os.path.isfile(html_path):
        return FileResponse(html_path)
        
    return JSONResponse(status_code=404, content={"message": "File not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)