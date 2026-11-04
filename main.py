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

# फाइलों और स्टोरेज के लिए माunt
app.mount("/storage", StaticFiles(directory=UPLOAD_DIR), name="storage")

# अगर आपके प्रोजेक्ट में images या assets का फोल्डर है, तो फोटो लोड होने के लिए इन्हें माउंट करें
if os.path.exists("images"):
    app.mount("/images", StaticFiles(directory="images"), name="images")
if os.path.exists("assets"):
    app.mount("/assets", StaticFiles(directory="assets"), name="assets")

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

# 2. सभी HTML पेजेस (जैसे login.html आदि) को आटोमेटिक खोलने के लिए Dynamic Route
@app.get("/{page_name}.html")
def serve_html_pages(page_name: str):
    file_path = f"{page_name}.html"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return JSONResponse(status_code=404, content={"message": "Page not found"})

# 3. फाइल अपलोड एपीआई
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)