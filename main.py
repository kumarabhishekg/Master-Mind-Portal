import os, re, uuid, hmac, hashlib, secrets, time, shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from database import engine, SessionLocal, Base, Application, User, IssuedDocument, PrintQueue

Base.metadata.create_all(bind=engine)
app = FastAPI()
# Same-origin deployment is expected. Do not enable wildcard credentialed CORS.
allowed_origins = [x.strip() for x in os.getenv("ALLOWED_ORIGINS", "").split(",") if x.strip()]
if allowed_origins:
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "mastermind_storage"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# Files are no longer exposed as a public static directory.
COOKIE_NAME = "__Host-mm_session"
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
SESSION_SECONDS = 60 * 60 * 8
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + salt.hex() + "$" + derived.hex()

def provision_admin_from_environment():
    mobile = os.getenv("ADMIN_MOBILE", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    name = os.getenv("ADMIN_NAME", "Portal Administrator").strip() or "Portal Administrator"
    if not mobile and not password: return
    if not re.fullmatch(r"[0-9]{10}", mobile) or len(password) < 14:
        raise RuntimeError("Set ADMIN_MOBILE to 10 digits and ADMIN_PASSWORD to at least 14 characters")
    db = SessionLocal()
    try:
        account = db.query(User).filter(User.mobile == mobile).first()
        if account is None:
            db.add(User(name=name, mobile=mobile, email="", password=hash_password(password),
                        status="Active", role="admin"))
        else:
            # Only the explicitly configured administrator account is promoted/reset here.
            account.role = "admin"
            account.status = "Active"
            account.password = hash_password(password)
        db.commit()
    finally:
        db.close()

def verify_password(password: str, stored: str) -> tuple[bool, bool]:
    if stored.startswith("scrypt$"):
        try:
            _, salt_hex, hash_hex = stored.split("$", 2)
            candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
            return hmac.compare_digest(candidate.hex(), hash_hex), False
        except Exception: return False, False
    # One-time legacy plaintext compatibility; successful login upgrades the hash.
    return hmac.compare_digest(password, stored), True

provision_admin_from_environment()

def make_session(user: User) -> str:
    if not SESSION_SECRET:
        raise HTTPException(503, "Server authentication is not configured")
    payload = f"{user.id}.{int(time.time()) + SESSION_SECONDS}.{secrets.token_urlsafe(24)}"
    sig = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(COOKIE_NAME, "")
    try:
        user_id, expiry, nonce, signature = token.split(".", 3)
        payload = ".".join((user_id, expiry, nonce))
        expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not SESSION_SECRET or not hmac.compare_digest(signature, expected) or int(expiry) < int(time.time()):
            raise ValueError()
        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or user.status == "Blocked": raise ValueError()
        return user
    except Exception:
        raise HTTPException(401, "Login required")

def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin": raise HTTPException(403, "Admin access required")
    return user

@app.get("/")
def serve_home(): return FileResponse("HOME.html")

class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    mobile: str = Field(pattern=r"^[0-9]{10}$")
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)

class LoginInput(BaseModel):
    mobile: str = Field(pattern=r"^[0-9]{10}$")
    password: str = Field(min_length=1, max_length=128)

@app.post("/api/signup")
def register_user(user: UserCreate, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.mobile == user.mobile).first():
        raise HTTPException(409, "Mobile number already registered")
    new_user = User(name=user.name.strip(), mobile=user.mobile, email=str(user.email).lower(),
                    password=hash_password(user.password), status="Active", role="user")
    db.add(new_user); db.commit()
    return {"status": "success", "message": "User registered successfully"}

@app.post("/api/auth/login")
def login(data: LoginInput, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == data.mobile).first()
    if not user or user.status == "Blocked":
        raise HTTPException(401, "Invalid mobile number or password")
    valid, legacy = verify_password(data.password, user.password or "")
    if not valid: raise HTTPException(401, "Invalid mobile number or password")
    if legacy:
        user.password = hash_password(data.password); db.commit()
    token = make_session(user)
    response.set_cookie(COOKIE_NAME, token, httponly=True, secure=True, samesite="lax",
                        path="/", max_age=SESSION_SECONDS)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "success", "user": {"name": user.name, "mobile": user.mobile, "role": user.role}}

@app.get("/api/auth/me")
def who_am_i(user: User = Depends(current_user)):
    return {"status": "success", "user": {"name": user.name, "mobile": user.mobile, "role": user.role}}

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return {"status": "success"}

@app.get("/api/documents")
def list_my_documents(user: User = Depends(current_user), db: Session = Depends(get_db)):
    docs = db.query(IssuedDocument).filter(IssuedDocument.target_mobile == user.mobile).order_by(IssuedDocument.id.desc()).all()
    return {"status":"success","data":[{"id":d.id,"title":d.title,"fileName":d.file_name,
            "fileUrl":d.file_url,"date":d.created_at} for d in docs]}

@app.post("/api/admin/documents")
async def issue_document(mobile: str = Form(...), title: str = Form(...), file: UploadFile = File(...),
                         _: User = Depends(admin_user), db: Session = Depends(get_db)):
    target_user = db.query(User).filter(User.mobile == mobile).first()
    if not target_user: raise HTTPException(404, "Target user not found")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS or file.content_type not in {"application/pdf","image/jpeg","image/png"}:
        raise HTTPException(415, "Only PDF, JPG and PNG files are allowed")
    unique_id = str(uuid.uuid4()); target = UPLOAD_DIR / (unique_id + suffix)
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES: raise HTTPException(413, "File exceeds 10 MB limit")
                out.write(chunk)
        with target.open("rb") as check: signature = check.read(8)
        valid = (suffix == ".pdf" and signature.startswith(b"%PDF-")) or (suffix in {".jpg",".jpeg"} and signature.startswith(bytes([255,216,255]))) or (suffix == ".png" and signature.startswith(bytes([137,80,78,71,13,10,26,10])))
        if not valid: raise HTTPException(415, "File content does not match its extension")
        doc = IssuedDocument(target_mobile=mobile, title=title[:120], file_name=Path(file.filename).name[:180],
                             file_url=f"/api/files/{unique_id}", created_at=time.strftime("%Y-%m-%d"))
        db.add(doc); db.commit()
        return {"status":"success","data":{"id":doc.id,"fileUrl":doc.file_url}}
    except Exception:
        target.unlink(missing_ok=True); db.rollback(); raise

@app.post("/api/auth/password-reset")
def password_reset_disabled():
    raise HTTPException(501, "Password reset is disabled until email/mobile ownership verification is configured")

@app.get("/api/users")
def get_all_users(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id.desc()).all()
    return {"status": "success", "data": [{"id":u.id,"name":u.name,"mobile":u.mobile,
            "email":u.email,"status":u.status,"role":u.role} for u in users]}

@app.patch("/api/users/{user_id}/status")
def update_user_status(user_id: int, status: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if status not in {"Active", "Blocked"}: raise HTTPException(400, "Invalid status")
    user = db.query(User).filter(User.id == user_id).first()
    if not user: raise HTTPException(404, "User not found")
    user.status = status; db.commit()
    return {"status":"success"}

@app.patch("/api/applications/{application_id}")
def update_application(application_id: int, status: str, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if status not in {"Pending", "In Progress", "Completed", "Rejected"}:
        raise HTTPException(400, "Invalid application status")
    record = db.query(Application).filter(Application.id == application_id).first()
    if not record: raise HTTPException(404, "Application not found")
    record.status = status
    db.commit()
    return {"status": "success"}

@app.delete("/api/applications/{application_id}")
def delete_application(application_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    record = db.query(Application).filter(Application.id == application_id).first()
    if not record: raise HTTPException(404, "Application not found")
    db.delete(record)
    db.commit()
    return {"status": "success"}

@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, actor: User = Depends(admin_user), db: Session = Depends(get_db)):
    target = db.query(User).filter(User.id == user_id).first()
    if not target: raise HTTPException(404, "User not found")
    if target.id == actor.id: raise HTTPException(400, "You cannot delete your own admin account")
    if target.role == "admin": raise HTTPException(403, "Deleting another administrator is disabled")
    db.delete(target)
    db.commit()
    return {"status": "success"}

@app.get("/api/applications")
def get_all_applications(_: User = Depends(admin_user), db: Session = Depends(get_db)):
    apps = db.query(Application).order_by(Application.id.desc()).all()
    return {"status":"success","data":[{"id":a.id,"customer_name":a.customer_name,"service_name":a.service_name,
            "mobile":a.mobile,"description":a.description,"file_url":a.file_url,"unique_id":a.unique_id,
            "status":a.status} for a in apps]}



class InquiryCreate(BaseModel):
    service: str = Field(min_length=1, max_length=120)

@app.post("/api/inquiries")
def create_inquiry(data: InquiryCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = Application(customer_name=user.name, service_name="Coming Soon Inquiry", mobile=user.mobile,
        description=("Requested service: " + data.service.strip())[:1000], status="Pending")
    db.add(record); db.commit()
    return {"status":"success"}

class PrintQueueCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=100)
    print_type: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=1000)
    application_ids: list[int] = Field(min_length=1, max_length=20)

@app.post("/api/print-queue")
def create_print_queue(data: PrintQueueCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    apps = db.query(Application).filter(Application.id.in_(data.application_ids)).all()
    if len(apps) != len(set(data.application_ids)) or any(a.mobile != user.mobile for a in apps):
        raise HTTPException(400, "Invalid uploaded file selection")
    item = PrintQueue(owner_mobile=user.mobile, customer_name=data.customer_name.strip(),
        print_type=data.print_type, description=data.description.strip(),
        application_ids=",".join(str(a.id) for a in apps), status="Pending",
        created_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    db.add(item); db.commit(); db.refresh(item)
    return {"status":"success","data":{"id":item.id}}

def serialize_print_queue(item: PrintQueue, db: Session):
    ids = [int(x) for x in item.application_ids.split(",") if x.isdigit()]
    apps = db.query(Application).filter(Application.id.in_(ids)).all() if ids else []
    files = [{"id":a.id,"name":(list(UPLOAD_DIR.glob(a.unique_id + ".*"))[0].name if list(UPLOAD_DIR.glob(a.unique_id + ".*")) else Path(a.file_url).name),"url":a.file_url,"unique_id":a.unique_id}
             for a in apps]
    return {"id":item.id,"customer_name":item.customer_name,"print_type":item.print_type,
        "description":item.description,"status":item.status,"created_at":item.created_at,"files":files}

@app.get("/api/print-queue")
def list_print_queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(PrintQueue)
    if user.role != "admin": query = query.filter(PrintQueue.owner_mobile == user.mobile)
    items = query.order_by(PrintQueue.id.desc()).all()
    return {"status":"success","data":[serialize_print_queue(x, db) for x in items]}

@app.get("/api/print-queue/{queue_id}")
def get_print_queue(queue_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.query(PrintQueue).filter(PrintQueue.id == queue_id).first()
    if not item: raise HTTPException(404, "Print request not found")
    if user.role != "admin" and item.owner_mobile != user.mobile: raise HTTPException(403, "Access denied")
    return {"status":"success","data":serialize_print_queue(item, db)}

@app.delete("/api/print-queue/{queue_id}")
def delete_print_queue(queue_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    item = db.query(PrintQueue).filter(PrintQueue.id == queue_id).first()
    if not item: raise HTTPException(404, "Print request not found")
    db.delete(item); db.commit()
    return {"status":"success"}
@app.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...),
    customer_name: str = Form(""), service_name: str = Form(""), mobile: str = Form(""),
    description: str = Form(""), user: User = Depends(current_user), db: Session = Depends(get_db)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS: raise HTTPException(415, "Only PDF, JPG and PNG files are allowed")
    if file.content_type not in {"application/pdf","image/jpeg","image/png"}:
        raise HTTPException(415, "Unsupported file type")
    unique_id = str(uuid.uuid4()); target = UPLOAD_DIR / (unique_id + suffix)
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES: raise HTTPException(413, "File exceeds 10 MB limit")
                out.write(chunk)
        with target.open("rb") as check:
            signature = check.read(8)
        valid = (suffix == ".pdf" and signature.startswith(b"%PDF-")) or (suffix in {".jpg",".jpeg"} and signature.startswith(bytes([255,216,255]))) or (suffix == ".png" and signature.startswith(bytes([137,80,78,71,13,10,26,10])))
        if not valid: raise HTTPException(415, "File content does not match its extension")
        record = Application(customer_name=(customer_name or user.name)[:100],
            service_name=(service_name or "Upload")[:100], mobile=user.mobile,
            description=description[:1000], file_url=f"/api/files/{unique_id}", unique_id=unique_id)
        db.add(record); db.commit()
        return {"status":"success","id":record.id,"unique_id":unique_id,"file_url":record.file_url}
    except Exception:
        target.unlink(missing_ok=True); db.rollback(); raise

@app.get("/api/files/{unique_id}")
def download_file(unique_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.query(Application).filter(Application.unique_id == unique_id).first()
    issued = db.query(IssuedDocument).filter(IssuedDocument.file_url == f"/api/files/{unique_id}").first()
    if not record and not issued: raise HTTPException(404, "File not found")
    owner_mobile = record.mobile if record else issued.target_mobile
    if user.role != "admin" and owner_mobile != user.mobile: raise HTTPException(403, "Access denied")
    matches = list(UPLOAD_DIR.glob(unique_id + ".*"))
    if not matches: raise HTTPException(404, "File not found")
    return FileResponse(matches[0], filename=matches[0].name)

@app.get("/{file_path:path}")
def serve_files_and_pages(file_path: str, request: Request, db: Session = Depends(get_db)):
    # Protect dashboards at the server; hiding links in the browser is not access control.
    if file_path == "admin.html":
        actor = current_user(request, db)
        if actor.role != "admin": raise HTTPException(403, "Admin access required")
    if file_path == "H login.html":
        current_user(request, db)
    # Only serve HTML pages and known static assets; never expose Python, DB, config or arbitrary files.
    candidate = Path(file_path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() in {".py",".db",".sqlite",".env",".json",".txt",".pem",".key"}:
        raise HTTPException(404, "Not found")
    if candidate.suffix.lower() == ".html" and candidate.is_file(): return FileResponse(candidate)
    if not candidate.suffix and Path(file_path + ".html").is_file(): return FileResponse(file_path + ".html")
    if candidate.suffix.lower() in {".png",".jpg",".jpeg",".svg",".css",".js",".ico",".webp"} and candidate.is_file():
        return FileResponse(candidate)
    raise HTTPException(404, "Not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
