import hashlib
import hmac
import json
import os
import re
import base64
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import Application, Base, PortalRecord, SessionLocal, StoredFile, User, engine

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "mastermind_storage"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

RECORD_CATEGORIES = {"cscApplications", "bankingApplications", "gstApplications", "travelApplications", "instantPrintQueue", "userIssuedDocs"}
AUTH_SECRET = os.getenv("PORTAL_AUTH_SECRET") or os.urandom(32).hex()
SESSION_MAX_AGE = 60 * 60 * 24


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310_000).hex()
    return f"pbkdf2_sha256${salt}${digest}"


def password_matches(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        _, salt, expected = stored.split("$", 2)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 310_000).hex()
        return hmac.compare_digest(actual, expected)
    return password == stored  # Existing accounts are upgraded to a hash after a successful login.


def public_user(user: User):
    return {"id": user.id, "name": user.name, "mobile": user.mobile, "email": user.email, "status": user.status or "Active"}


def record_json(record: PortalRecord):
    payload = json.loads(record.payload)
    return {**payload, "id": record.id, "category": record.category, "status": record.status}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def issue_session(principal: dict) -> str:
    payload = {**principal, "exp": int(time.time()) + SESSION_MAX_AGE}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(AUTH_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def get_principal(request: Request):
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ") or request.cookies.get("portal_session", "")
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(AUTH_SECRET.encode(), encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if payload.get("exp", 0) < time.time():
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Please sign in again.") from exc


def require_admin(request: Request):
    principal = get_principal(request)
    if principal.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return principal


def session_response(data: dict, principal: dict, request: Request):
    response = JSONResponse(data)
    response.set_cookie("portal_session", issue_session(principal), httponly=True,
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https", samesite="lax",
                        max_age=SESSION_MAX_AGE, path="/")
    return response


def storage_names(value):
    """Collect this service's database and legacy-storage file references."""
    found = {"database": set(), "legacy": set()}
    if isinstance(value, dict):
        for item in value.values():
            nested = storage_names(item)
            found["database"].update(nested["database"])
            found["legacy"].update(nested["legacy"])
    elif isinstance(value, list):
        for item in value:
            nested = storage_names(item)
            found["database"].update(nested["database"])
            found["legacy"].update(nested["legacy"])
    elif isinstance(value, str):
        parsed = urlparse(value)
        database_match = re.fullmatch(r"/api/files/([A-Za-z0-9-]+)", parsed.path)
        legacy_match = re.fullmatch(r"/storage/([A-Za-z0-9_.-]+)", parsed.path)
        if database_match:
            found["database"].add(database_match.group(1))
        if legacy_match:
            found["legacy"].add(legacy_match.group(1))
    return found


def delete_record_files(record: PortalRecord, db: Session):
    payload = json.loads(record.payload)
    urls = storage_names(payload)
    for file_id in urls["database"]:
        db.query(StoredFile).filter(StoredFile.id == file_id).delete(synchronize_session=False)
        db.query(Application).filter(Application.file_url.like(f"%/api/files/{file_id}")).delete(synchronize_session=False)
    for filename in urls["legacy"]:
        path = UPLOAD_DIR / filename
        if path.is_file() and path.parent.resolve() == UPLOAD_DIR.resolve():
            path.unlink(missing_ok=True)
        # Remove matching metadata rows left by older versions of /api/upload.
        db.query(Application).filter(Application.file_url.like(f"%/storage/{filename}")).delete(synchronize_session=False)


@app.get("/")
def serve_home():
    return FileResponse(BASE_DIR / "HOME.html")


@app.post("/api/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    customer_name: str = Form("Anonymous Customer"),
    service_name: str = Form("Quick Upload"),
    mobile: str = Form("Not Provided"),
    description: str = Form(""),
    db: Session = Depends(get_db),
):
    original_name = Path(file.filename or "upload").name
    extension = Path(original_name).suffix[:20]
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{extension}"
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File size exceeds the 20 MB limit.")
        file_url = f"{str(request.base_url).rstrip('/')}/api/files/{unique_id}"
        # Keep legacy upload metadata for backward compatibility. New app submissions
        # are stored as one PortalRecord and own their file references.
        stored_file = StoredFile(id=unique_id, filename=original_name,
                                 content_type=file.content_type or "application/octet-stream", content=content)
        row = Application(customer_name=customer_name, service_name=service_name, mobile=mobile,
                          description=description, file_url=file_url, unique_id=unique_id)
        db.add_all([stored_file, row])
        db.commit()
        return {"status": "success", "unique_id": unique_id, "filename": original_name,
                "file_url": file_url, "message": "File uploaded successfully."}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="File upload failed") from exc


@app.get("/api/applications")
def get_uploaded_files(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    rows = db.query(Application).order_by(Application.id.desc()).all()
    return {"status": "success", "data": [{"id": row.id, "customer_name": row.customer_name,
            "service_name": row.service_name, "mobile": row.mobile, "description": row.description,
            "file_url": row.file_url, "unique_id": row.unique_id, "status": row.status} for row in rows]}


@app.get("/api/files/{file_id}")
def get_stored_file(file_id: str, request: Request, db: Session = Depends(get_db)):
    principal = get_principal(request)
    row = db.query(StoredFile).filter(StoredFile.id == file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    if principal.get("role") != "admin":
        allowed = db.query(Application).filter(Application.unique_id == file_id,
                                                Application.mobile == principal.get("mobile")).first()
        if not allowed:
            raise HTTPException(status_code=403, detail="You cannot access this file.")
    safe_name = row.filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    return Response(content=row.content, media_type=row.content_type,
                     headers={"Content-Disposition": f'inline; filename="{safe_name}"'})


@app.get("/storage/{filename}")
def get_legacy_file(filename: str, request: Request, db: Session = Depends(get_db)):
    if Path(filename).name != filename:
        raise HTTPException(status_code=404, detail="File not found.")
    principal = get_principal(request)
    row = db.query(Application).filter(Application.file_url.like(f"%/storage/{filename}")).first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    if principal.get("role") != "admin" and row.mobile != principal.get("mobile"):
        raise HTTPException(status_code=403, detail="You cannot access this file.")
    path = (UPLOAD_DIR / filename).resolve()
    if not path.is_file() or path.parent != UPLOAD_DIR.resolve():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(path)


class UserCreate(BaseModel):
    name: str
    mobile: str
    email: str
    password: str


class LoginRequest(BaseModel):
    mobile: str
    password: str


class PasswordReset(BaseModel):
    mobile: str
    email: str
    password: str


@app.post("/api/signup", status_code=201)
def register_user(user: UserCreate, db: Session = Depends(get_db)):
    mobile = user.mobile.strip()
    email = user.email.strip().lower()
    name = user.name.strip()
    if not re.fullmatch(r"[0-9]{10}", mobile) or not name or not email or not user.password:
        raise HTTPException(status_code=400, detail="Enter a valid name, email, mobile, and password.")
    if db.query(User).filter(User.mobile == mobile).first():
        raise HTTPException(status_code=409, detail="Mobile number already registered.")
    row = User(name=name, mobile=mobile, email=email, password=hash_password(user.password), status="Active")
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not register this mobile number.") from exc
    db.refresh(row)
    return {"status": "success", "message": "User registered successfully!", "user": public_user(row)}


@app.post("/api/login")
def login_user(credentials: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == credentials.mobile.strip()).first()
    if not user or not password_matches(credentials.password, user.password or ""):
        raise HTTPException(status_code=401, detail="Incorrect mobile number or password.")
    if user.status == "Blocked":
        raise HTTPException(status_code=403, detail="This account is blocked. Please contact the administrator.")
    if not user.password.startswith("pbkdf2_sha256$"):
        user.password = hash_password(credentials.password)
        db.commit()
    safe_user = public_user(user)
    return session_response({"status": "success", "user": safe_user},
                           {"role": "user", "id": user.id, "mobile": user.mobile}, request)


class AdminLogin(BaseModel):
    mobile: str
    password: str


@app.post("/api/admin/login")
def login_admin(credentials: AdminLogin, request: Request):
    configured = [(os.getenv(f"ADMIN_MOBILE_{index}"), os.getenv(f"ADMIN_PASSWORD_{index}")) for index in (1, 2)]
    if not any(mobile and password for mobile, password in configured):
        raise HTTPException(status_code=503, detail="Admin credentials are not configured on the server.")
    valid = any(mobile and password and hmac.compare_digest(credentials.mobile, mobile)
                and hmac.compare_digest(credentials.password, password) for mobile, password in configured)
    if not valid:
        raise HTTPException(status_code=401, detail="Incorrect administrator credentials.")
    return session_response({"status": "success", "role": "admin"},
                           {"role": "admin", "mobile": credentials.mobile}, request)


@app.post("/api/logout")
def logout():
    response = JSONResponse({"status": "success"})
    response.delete_cookie("portal_session", path="/")
    return response


@app.post("/api/password-reset")
def reset_password(request: PasswordReset, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.mobile == request.mobile.strip(), User.email == request.email.strip().lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Mobile and email do not match an account.")
    user.password = hash_password(request.password)
    db.commit()
    return {"status": "success", "message": "Password updated successfully."}


@app.get("/api/users")
def get_all_users(db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    return {"status": "success", "data": [public_user(user) for user in db.query(User).order_by(User.id.desc()).all()]}


class UserStatusUpdate(BaseModel):
    status: str


@app.patch("/api/users/{user_id}")
def update_user_status(user_id: int, request: UserStatusUpdate, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    if request.status not in {"Active", "Blocked"}:
        raise HTTPException(status_code=400, detail="Status must be Active or Blocked.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.status = request.status
    db.commit()
    return {"status": "success", "user": public_user(user)}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    db.delete(user)
    db.commit()
    return {"status": "success"}


class RecordCreate(BaseModel):
    category: str
    payload: dict


class RecordStatusUpdate(BaseModel):
    status: str


@app.get("/api/records")
def get_records(request: Request, category: str | None = None, db: Session = Depends(get_db)):
    query = db.query(PortalRecord)
    if category:
        if category not in RECORD_CATEGORIES:
            raise HTTPException(status_code=400, detail="Unknown record category.")
        query = query.filter(PortalRecord.category == category)
    principal = get_principal(request)
    rows = query.order_by(PortalRecord.id.desc()).all()
    if principal.get("role") == "admin":
        data = [record_json(row) for row in rows]
    elif category == "userIssuedDocs" and principal.get("role") == "user":
        data = [record_json(row) for row in rows if json.loads(row.payload).get("targetMobile") == principal.get("mobile")]
    else:
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return {"status": "success", "data": data}


@app.post("/api/records", status_code=201)
def create_record(request: RecordCreate, http_request: Request, db: Session = Depends(get_db)):
    if request.category not in RECORD_CATEGORIES:
        raise HTTPException(status_code=400, detail="Unknown record category.")
    if request.category == "userIssuedDocs":
        if get_principal(http_request).get("role") != "admin":
            raise HTTPException(status_code=403, detail="Sign in as an administrator to issue documents.")
    row = PortalRecord(category=request.category, payload=json.dumps(request.payload),
                       status=request.payload.get("status", "Pending"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"status": "success", "record": record_json(row)}


@app.patch("/api/records/{record_id}")
def update_record(record_id: int, request: RecordStatusUpdate, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    if request.status not in {"Pending", "Completed"}:
        raise HTTPException(status_code=400, detail="Unknown application status.")
    row = db.query(PortalRecord).filter(PortalRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found.")
    row.status = request.status
    db.commit()
    return {"status": "success", "record": record_json(row)}


@app.delete("/api/records/{record_id}")
def delete_record(record_id: int, db: Session = Depends(get_db), _admin: dict = Depends(require_admin)):
    row = db.query(PortalRecord).filter(PortalRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Record not found.")
    try:
        delete_record_files(row, db)
        db.delete(row)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Record and file cleanup failed.") from exc
    return {"status": "success"}


@app.get("/{file_path:path}")
def serve_files_and_pages(file_path: str):
    if ".." in file_path:
        return JSONResponse(status_code=400, content={"message": "Invalid path"})
    candidate = (BASE_DIR / file_path).resolve()
    if candidate.is_file() and candidate.is_relative_to(BASE_DIR):
        return FileResponse(candidate)
    html_candidate = (BASE_DIR / f"{file_path}.html").resolve()
    if html_candidate.is_file() and html_candidate.is_relative_to(BASE_DIR):
        return FileResponse(html_candidate)
    return JSONResponse(status_code=404, content={"message": "File not found"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
