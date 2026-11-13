"""Master Mind Portal API: Firestore database + private Google Drive documents.
All Google credentials are loaded from the server environment; never from frontend files.
"""
import os, re, uuid, json, io
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional
from functools import lru_cache

from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel, EmailStr, Field
import bcrypt

BASE_DIR = Path(__file__).resolve().parent
def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise HTTPException(400, "Password must be at most 72 UTF-8 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")

def verify_password(password: str, encoded: str) -> bool:
    try:
        raw = password.encode("utf-8")
        if len(raw) > 72: return False
        return bcrypt.checkpw(raw, encoded.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return False
app = FastAPI(title="Master Mind Portal API", version="3.0.0-gcp")

SESSION_SECRET = os.getenv("SESSION_SECRET", "")
if not SESSION_SECRET or SESSION_SECRET.startswith("REPLACE_") or len(SESSION_SECRET) < 32:
    raise RuntimeError("Set SESSION_SECRET to a random secret of at least 32 characters")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax", https_only=os.getenv("COOKIE_SECURE", "true").lower() == "true", max_age=60*60*24*7)
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Content-Type"])

# Google Cloud Firestore is the only database; there is no local database fallback.
@lru_cache(maxsize=1)
def get_firestore():
    try:
        from google.cloud import firestore
        raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if raw:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_info(json.loads(raw))
            project = os.getenv("GOOGLE_CLOUD_PROJECT") or json.loads(raw).get("project_id")
            return firestore.Client(project=project, credentials=credentials)
        # On GCP, use attached service identity / Application Default Credentials.
        return firestore.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    except Exception as exc:
        raise HTTPException(503, "Google Cloud Firestore is not configured") from exc

def db_dep():
    return get_firestore()

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def clean_user(doc):
    d = doc.to_dict() or {}
    return {"id": doc.id, "name": d.get("name", ""), "mobile": d.get("mobile", doc.id), "email": d.get("email", ""), "status": d.get("status", "Active"), "role": d.get("role", "user"), "created_at": d.get("created_at", "")}

class SignupIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    mobile: str = Field(pattern=r"^\d{10}$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
class LoginIn(BaseModel):
    mobile: str = Field(pattern=r"^\d{10}$")
    password: str = Field(min_length=1, max_length=72)
class StatusIn(BaseModel):
    status: str = Field(pattern=r"^(Pending|In Progress|Approved|Rejected|Completed|Issued)$")
class ApplicationIn(BaseModel):
    status: str = Field(pattern=r"^(Pending|In Progress|Approved|Rejected|Completed|Issued)$")
    admin_note: str = Field(default="", max_length=2000)


def current_user(request: Request, db=Depends(db_dep)):
    mobile = request.session.get("mobile")
    if not mobile: raise HTTPException(401, "Please login")
    snap = db.collection("users").document(mobile).get()
    if not snap.exists: request.session.clear(); raise HTTPException(401, "Account unavailable")
    user = snap.to_dict() or {}
    if user.get("status", "Active") != "Active": request.session.clear(); raise HTTPException(401, "Account unavailable")
    user["id"] = mobile
    return user

def admin_user(user=Depends(current_user)):
    if user.get("role") != "admin": raise HTTPException(403, "Admin access required")
    return user

@app.on_event("startup")
def ensure_admin():
    mobile = os.getenv("ADMIN_MOBILE", "").strip(); password = os.getenv("ADMIN_PASSWORD", "")
    # Admin bootstrap is optional until the Google Cloud environment is configured.
    if not mobile and not password: return
    if not re.fullmatch(r"\d{10}", mobile) or len(password) < 12 or password.startswith("REPLACE_"):
        raise RuntimeError("Set a real ADMIN_MOBILE (10 digits) and unique ADMIN_PASSWORD (at least 12 chars)")
    db = get_firestore(); ref = db.collection("users").document(mobile); snap = ref.get()
    payload = {"name": os.getenv("ADMIN_NAME", "Master Mind Administrator"), "mobile": mobile, "email": os.getenv("ADMIN_EMAIL", "admin@example.invalid"), "password_hash": hash_password(password), "role": "admin", "status": "Active", "created_at": (snap.to_dict() or {}).get("created_at", now_iso())}
    ref.set(payload, merge=True)

@app.get("/api/health")
def health(db=Depends(db_dep)):
    try:
        # A server-side read confirms Firestore connectivity and permissions.
        list(db.collection("_healthcheck").limit(1).stream())
        folder = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
        if folder:
            drive_client().files().get(fileId=folder, fields="id,name,mimeType").execute()
            storage = "google-drive"
        else:
            storage = "not-configured"
        return {"status": "ok", "database": "google-cloud-firestore", "storage": storage}
    except Exception as exc: raise HTTPException(503, "Google Cloud Firestore connection failed") from exc

@app.post("/api/signup")
def signup(data: SignupIn, db=Depends(db_dep)):
    ref = db.collection("users").document(data.mobile)
    if ref.get().exists: raise HTTPException(409, "Mobile number already registered")
    ref.create({"name": data.name.strip(), "mobile": data.mobile, "email": str(data.email).lower(), "password_hash": hash_password(data.password), "role": "user", "status": "Active", "created_at": now_iso()})
    return {"status": "success", "message": "Registration successful"}

@app.post("/api/login")
def login(data: LoginIn, request: Request, db=Depends(db_dep)):
    snap = db.collection("users").document(data.mobile).get(); u = snap.to_dict() if snap.exists else None
    if not u or not verify_password(data.password, u.get("password_hash", "")): raise HTTPException(401, "Invalid mobile number or password")
    if u.get("status", "Active") != "Active": raise HTTPException(403, "Account is blocked. Contact administrator.")
    request.session.clear(); request.session["mobile"] = data.mobile
    return {"status": "success", "user": clean_user(snap)}

@app.post("/api/logout")
def logout(request: Request): request.session.clear(); return {"status": "success"}
@app.get("/api/me")
def me(user=Depends(current_user)): return {"status": "success", "user": {k:v for k,v in user.items() if k != "password_hash"}}

@app.get("/api/users")
def users(_=Depends(admin_user), db=Depends(db_dep)):
    rows = db.collection("users").stream(); return {"status":"success", "data":[clean_user(x) for x in rows]}
@app.patch("/api/users/{user_id}/status")
def set_user_status(user_id: str, status: str, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("users").document(user_id); snap=ref.get()
    if not snap.exists or (snap.to_dict() or {}).get("role") == "admin": raise HTTPException(404,"User not found")
    if status not in ("Active","Blocked"): raise HTTPException(400,"Invalid status")
    ref.update({"status":status}); return {"status":"success"}
@app.delete("/api/users/{user_id}")
def delete_user(user_id: str, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("users").document(user_id); snap=ref.get()
    if not snap.exists or (snap.to_dict() or {}).get("role") == "admin": raise HTTPException(404,"User not found")
    ref.delete(); return {"status":"success"}

# Private Drive storage: service account must have access to the chosen Drive folder.
def drive_client():
    raw=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        creds=service_account.Credentials.from_service_account_info(json.loads(raw), scopes=["https://www.googleapis.com/auth/drive"])
    else:
        from googleapiclient.discovery import build
        import google.auth
        creds,_=google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)

def drive_upload(data: bytes, filename: str, content_type: str):
    folder=os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    if not folder: raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID is required; no local storage fallback is enabled")
    from googleapiclient.http import MediaIoBaseUpload
    service=drive_client(); media=MediaIoBaseUpload(io.BytesIO(data), mimetype=content_type or "application/octet-stream", resumable=True)
    created=service.files().create(body={"name":filename,"parents":[folder]}, media_body=media, fields="id,name,mimeType").execute()
    return created["id"]

@app.post("/api/upload")
async def upload_file(file: UploadFile=File(...), customer_name: str=Form(...), service_name: str=Form(...), mobile: str=Form(...), description: str=Form(""), user=Depends(current_user), db=Depends(db_dep)):
    if not re.fullmatch(r"\d{10}", mobile): raise HTTPException(400, "Invalid contact mobile")
    if not file.filename or len(file.filename)>255: raise HTTPException(400,"Invalid filename")
    allowed_ext = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".txt"}
    if Path(file.filename).suffix.lower() not in allowed_ext: raise HTTPException(415, "File type not allowed")
    if len(customer_name)>160 or len(service_name)>180 or len(description)>2000: raise HTTPException(400, "Form field too long")
    if not os.getenv("GOOGLE_DRIVE_FOLDER_ID"): raise HTTPException(503,"Google Drive folder is not configured")
    data=await file.read(15*1024*1024+1)
    if not data: raise HTTPException(400, "Uploaded file is empty")
    if len(data)>15*1024*1024: raise HTTPException(413,"Maximum upload size is 15 MB")
    uid=str(uuid.uuid4()); safe_name=f"{uid}{Path(file.filename).suffix.lower()}"
    try:
        drive_id=drive_upload(data,safe_name,file.content_type or "application/octet-stream")
        item={"unique_id":uid,"customer_name":customer_name.strip(),"service_name":service_name.strip(),"mobile":mobile,"owner_mobile":user["mobile"],"description":description,"file_url":f"/api/files/{uid}","drive_file_id":drive_id,"status":"Pending","admin_note":"","created_at":now_iso()}
        db.collection("documents").document(uid).set(item)
        return {"status":"success","unique_id":uid,"file_url":item["file_url"],"message":"Application saved"}
    except Exception as exc: raise HTTPException(500,"Upload failed. Verify Drive API, folder sharing and service-account permissions.") from exc

@app.get("/api/files/{unique_id}")
def get_drive_file(unique_id: str, user=Depends(current_user), db=Depends(db_dep)):
    snap=db.collection("documents").document(unique_id).get()
    if not snap.exists: raise HTTPException(404,"File not found")
    record=snap.to_dict() or {}
    if user.get("role")!="admin" and record.get("owner_mobile", record.get("mobile"))!=user.get("mobile"): raise HTTPException(404,"File not found")
    drive_id=record.get("drive_file_id")
    if not drive_id: raise HTTPException(404,"File not found")
    from googleapiclient.http import MediaIoBaseDownload
    service=drive_client(); meta=service.files().get(fileId=drive_id,fields="name,mimeType").execute()
    req=service.files().get_media(fileId=drive_id); stream=io.BytesIO(); downloader=MediaIoBaseDownload(stream,req); done=False
    while not done: _,done=downloader.next_chunk()
    filename=meta.get("name","document").replace('"','')
    return Response(stream.getvalue(),media_type=meta.get("mimeType","application/octet-stream"),headers={"Content-Disposition":f'inline; filename="{filename}"','X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store'})

@app.get("/api/my-applications")
def my_applications(user=Depends(current_user),db=Depends(db_dep)):
    rows=db.collection("applications").where("owner_mobile","==",user["mobile"]).stream()
    data=[{k:v for k,v in (x.to_dict() or {}).items() if k not in {"drive_file_id"}}|{"id":x.id} for x in rows]; data.sort(key=lambda x:x.get("created_at", ""),reverse=True)
    return {"status":"success","data":data}
@app.get("/api/applications")
def applications(_=Depends(admin_user),db=Depends(db_dep)):
    rows=db.collection("applications").stream(); data=[x.to_dict()|{"id":x.id} for x in rows]; data.sort(key=lambda x:x.get("created_at", ""),reverse=True)
    return {"status":"success","data":data}
@app.patch("/api/applications/{application_id}")
def update_application(application_id: str, data: ApplicationIn, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("applications").document(application_id)
    if not ref.get().exists: raise HTTPException(404,"Application not found")
    ref.update({"status":data.status,"admin_note":data.admin_note,"updated_at":now_iso()})
    return {"status":"success"}
@app.delete("/api/applications/{application_id}")
def delete_application(application_id: str, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("applications").document(application_id); snap=ref.get()
    if not snap.exists: raise HTTPException(404,"Application not found")
    record=snap.to_dict() or {}
    file_urls=[]
    for key in ("file_url", "frontImg", "backImg"):
        value=record.get(key)
        if isinstance(value,str): file_urls.append(value)
    for value in record.get("extraDocs", []) if isinstance(record.get("extraDocs", []), list) else []:
        if isinstance(value,str): file_urls.append(value)
    for url in set(file_urls):
        match=re.search(r"/api/files/([A-Za-z0-9-]+)$", url)
        if not match: continue
        doc_ref=db.collection("documents").document(match.group(1)); doc_snap=doc_ref.get()
        if doc_snap.exists:
            drive_id=(doc_snap.to_dict() or {}).get("drive_file_id")
            if drive_id:
                try: drive_client().files().delete(fileId=drive_id).execute()
                except Exception: pass
            doc_ref.delete()
    ref.delete(); return {"status":"success"}


# ---- Cloud-backed application, instant-print and issued-document workflows ----
from pydantic import ConfigDict

class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    serviceName: str = Field(min_length=2, max_length=180)
    mobile: str = Field(pattern=r"^\d{10}$")
    description: str = Field(default="", max_length=5000)
    status: str = Field(default="Pending", pattern=r"^(Pending|In Progress|Approved|Rejected|Completed|Issued)$")
    frontImg: Optional[str] = Field(default=None, max_length=200)
    backImg: Optional[str] = Field(default=None, max_length=200)
    extraDocs: list[str] = Field(default_factory=list, max_length=20)
    fileNamesList: list[str] = Field(default_factory=list, max_length=20)

class PrintQueueCreate(BaseModel):
    model_config = ConfigDict(extra="allow")
    customer_name: str = Field(min_length=1, max_length=160)
    print_type: str = Field(default="Document", max_length=80)
    mobile: str = Field(pattern=r"^\d{10}$")
    files: list[dict] = Field(default_factory=list, max_length=20)
    description: str = Field(default="", max_length=2000)

class PrintQueueUpdate(BaseModel):
    status: str = Field(pattern=r"^(Pending|In Progress|Completed|Cancelled)$")
    admin_note: str = Field(default="", max_length=2000)

class IssuedDocumentCreate(BaseModel):
    target_mobile: str = Field(pattern=r"^\d{10}$")
    title: str = Field(min_length=2, max_length=180)

@app.post("/api/applications")
def create_application(data: ApplicationCreate, user=Depends(current_user), db=Depends(db_dep)):
    payload = data.model_dump()
    if len(json.dumps(payload, default=str)) > 30000: raise HTTPException(413, "Application data is too large")
    urls=[x for x in [data.frontImg, data.backImg, *data.extraDocs] if x]
    for url in urls:
        match=re.fullmatch(r"/api/files/([A-Za-z0-9-]{36})", url)
        if not match: raise HTTPException(400, "Invalid document reference")
        doc_snap=db.collection("documents").document(match.group(1)).get()
        if not doc_snap.exists: raise HTTPException(400, "Uploaded document not found")
        doc_data=doc_snap.to_dict() or {}
        if user.get("role") != "admin" and doc_data.get("owner_mobile") != user.get("mobile"):
            raise HTTPException(403, "Document does not belong to this account")
    payload.update({"mobile": data.mobile, "owner_mobile": user["mobile"],
                    "service_name": data.serviceName, "status": data.status,
                    "created_at": now_iso(), "updated_at": now_iso(),
                    "submitted_by": user["mobile"], "record_type": "service_application"})
    ref = db.collection("applications").document(str(uuid.uuid4()))
    ref.set(payload)
    return {"status": "success", "id": ref.id, "message": "Application saved to cloud database"}

@app.get("/api/print-queue")
def get_print_queue(user=Depends(current_user), db=Depends(db_dep)):
    query = db.collection("print_queue")
    if user.get("role") != "admin": query = query.where("mobile", "==", user["mobile"])
    rows = [x.to_dict() | {"id": x.id} for x in query.stream()]
    rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"status": "success", "data": rows}

@app.post("/api/print-queue")
def create_print_queue(data: PrintQueueCreate, user=Depends(current_user), db=Depends(db_dep)):
    if data.mobile != user["mobile"] and user.get("role") != "admin":
        raise HTTPException(403, "You can only create your own print request")
    if not data.files: raise HTTPException(400, "At least one uploaded file is required")
    for item in data.files:
        url=item.get("url") or item.get("file_url")
        match=re.fullmatch(r"/api/files/([A-Za-z0-9-]{36})", url or "")
        if not match: raise HTTPException(400, "Invalid print document reference")
        snap=db.collection("documents").document(match.group(1)).get()
        if not snap.exists: raise HTTPException(400, "Print document not found")
        doc_data=snap.to_dict() or {}
        if user.get("role") != "admin" and doc_data.get("owner_mobile") != user.get("mobile"):
            raise HTTPException(403, "Print document does not belong to this account")
    payload = data.model_dump()
    payload.update({"mobile": user["mobile"] if user.get("role") != "admin" else data.mobile,
                    "status": "Pending", "created_at": now_iso(), "updated_at": now_iso()})
    ref = db.collection("print_queue").document(str(uuid.uuid4())); ref.set(payload)
    return {"status": "success", "id": ref.id}

@app.patch("/api/print-queue/{item_id}")
def update_print_queue(item_id: str, data: PrintQueueUpdate, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("print_queue").document(item_id)
    if not ref.get().exists: raise HTTPException(404, "Print request not found")
    ref.update({"status": data.status, "admin_note": data.admin_note, "updated_at": now_iso()})
    return {"status": "success"}

@app.delete("/api/print-queue/{item_id}")
def delete_print_queue(item_id: str, user=Depends(current_user), db=Depends(db_dep)):
    ref=db.collection("print_queue").document(item_id); snap=ref.get()
    if not snap.exists: raise HTTPException(404, "Print request not found")
    item=snap.to_dict() or {}
    if user.get("role") != "admin" and item.get("mobile") != user.get("mobile"):
        raise HTTPException(404, "Print request not found")
    ref.delete(); return {"status": "success"}

@app.get("/api/issued-documents")
def list_issued_documents(user=Depends(current_user), db=Depends(db_dep)):
    query=db.collection("issued_documents")
    if user.get("role") != "admin": query=query.where("target_mobile", "==", user["mobile"])
    rows=[{k:v for k,v in (x.to_dict() or {}).items() if k != "drive_file_id"} | {"id":x.id} for x in query.stream()]
    rows.sort(key=lambda x:x.get("created_at", ""), reverse=True)
    return {"status":"success", "data":rows}

@app.post("/api/issued-documents")
async def create_issued_document(target_mobile: str = Form(...), title: str = Form(...), file: UploadFile = File(...), _=Depends(admin_user), db=Depends(db_dep)):
    if not re.fullmatch(r"\d{10}", target_mobile): raise HTTPException(400, "Invalid target mobile")
    if not title.strip() or len(title)>180: raise HTTPException(400, "Invalid document title")
    data=await file.read(15*1024*1024+1)
    if not data or len(data)>15*1024*1024: raise HTTPException(413, "File must be between 1 byte and 15 MB")
    if Path(file.filename or "").suffix.lower() not in {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx", ".xls", ".xlsx", ".txt"}: raise HTTPException(415, "File type not allowed")
    folder=os.getenv("GOOGLE_DRIVE_FOLDER_ID")
    if not folder: raise HTTPException(503, "Google Drive folder is not configured")
    uid=str(uuid.uuid4()); safe_name=f"issued-{uid}{Path(file.filename or 'document').suffix.lower()}"
    try: drive_id=drive_upload(data,safe_name,file.content_type or "application/octet-stream")
    except Exception as exc: raise HTTPException(503, "Google Drive upload failed; check Drive API and folder permissions") from exc
    ref=db.collection("issued_documents").document(uid)
    ref.set({"target_mobile":target_mobile,"title":title.strip(),"file_name":file.filename or safe_name,
             "drive_file_id":drive_id,"file_url":f"/api/issued-documents/{uid}/file","status":"Issued","created_at":now_iso(),"created_by":_["mobile"]})
    return {"status":"success","id":uid}

@app.get("/api/issued-documents/{document_id}/file")
def get_issued_document_file(document_id: str, user=Depends(current_user), db=Depends(db_dep)):
    snap=db.collection("issued_documents").document(document_id).get()
    if not snap.exists: raise HTTPException(404,"Document not found")
    item=snap.to_dict() or {}
    if user.get("role") != "admin" and item.get("target_mobile") != user.get("mobile"):
        raise HTTPException(404,"Document not found")
    from googleapiclient.http import MediaIoBaseDownload
    service=drive_client(); meta=service.files().get(fileId=item["drive_file_id"],fields="name,mimeType").execute()
    req=service.files().get_media(fileId=item["drive_file_id"]); stream=io.BytesIO(); dl=MediaIoBaseDownload(stream,req); done=False
    while not done: _,done=dl.next_chunk()
    filename=meta.get("name","document").replace('"','')
    return Response(stream.getvalue(),media_type=meta.get("mimeType","application/octet-stream"),headers={"Content-Disposition":f'inline; filename="{filename}"',"X-Content-Type-Options":"nosniff","Cache-Control":"private, no-store"})

@app.delete("/api/issued-documents/{document_id}")
def delete_issued_document(document_id: str, _=Depends(admin_user), db=Depends(db_dep)):
    ref=db.collection("issued_documents").document(document_id); snap=ref.get()
    if not snap.exists: raise HTTPException(404,"Document not found")
    item=snap.to_dict() or {}
    try: drive_client().files().delete(fileId=item.get("drive_file_id", "")).execute()
    except Exception: pass
    ref.delete(); return {"status":"success"}

class PublicRequestIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    serviceName: str = Field(min_length=2, max_length=180)
    mobile: str = Field(pattern=r"^\d{10}$")
    description: str = Field(default="", max_length=5000)

@app.post("/api/public-requests")
def create_public_request(data: PublicRequestIn, db=Depends(db_dep)):
    # Public inquiries are stored separately; never grant them account privileges.
    payload=data.model_dump(); payload.update({"service_name":data.serviceName,"status":"Pending",
        "record_type":"public_request","created_at":now_iso(),"updated_at":now_iso()})
    ref=db.collection("applications").document(str(uuid.uuid4())); ref.set(payload)
    return {"status":"success","id":ref.id}

@app.get("/")
def home(): return FileResponse(BASE_DIR/"HOME.html")
@app.get("/{file_path:path}")
def pages(file_path: str):
    p=(BASE_DIR/file_path).resolve()
    if BASE_DIR not in p.parents or not p.is_file(): p=(BASE_DIR/(file_path+".html")).resolve()
    if BASE_DIR not in p.parents or not p.is_file():
        return JSONResponse(status_code=404,content={"message":"File not found"})
    relative=p.relative_to(BASE_DIR)
    allowed_extensions={".html", ".css", ".js", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".woff", ".woff2", ".ttf"}
    if any(part.startswith(".") or part.lower() == "secrets" for part in relative.parts) or p.suffix.lower() not in allowed_extensions:
        return JSONResponse(status_code=404,content={"message":"File not found"})
    return FileResponse(p)
