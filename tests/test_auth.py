import os

# CI uses an isolated SQLite database; production uses the configured external PostgreSQL URL.
os.environ.setdefault("DATABASE_URL", "sqlite:///./test_auth.db")
os.environ.setdefault("SESSION_SECRET", "ci-only-session-secret")
os.environ.setdefault("ADMIN_MOBILE", "9999999999")
os.environ.setdefault("ADMIN_PASSWORD", "CI-only-admin-password-12345")
os.environ.setdefault("ADMIN_NAME", "CI Test Administrator")
os.environ.setdefault("UPLOADS_ENABLED", "false")
os.environ.setdefault("REQUIRE_EXTERNAL_DATABASE", "false")

import pytest
from fastapi.testclient import TestClient

from database import Base, engine, SessionLocal, User
from main import app, hash_password, provision_admin_from_environment


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    provision_admin_from_environment()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    Base.metadata.drop_all(bind=engine)


def create_user(client, mobile="9876543210", password="user-password-123"):
    response = client.post("/api/signup", json={
        "name": "Test User",
        "mobile": mobile,
        "email": f"{mobile}@example.com",
        "password": password,
    })
    return response


def test_signup_stores_hashed_password_and_rejects_duplicate(client):
    response = create_user(client)
    assert response.status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.mobile == "9876543210").one()
        assert user.password != "user-password-123"
        assert user.password.startswith("scrypt$")
        assert user.role == "user"
    finally:
        db.close()

    duplicate = create_user(client)
    assert duplicate.status_code == 409


def test_login_me_and_logout_flow(client):
    assert create_user(client).status_code == 200

    login = client.post("/api/auth/login", json={
        "mobile": "9876543210",
        "password": "user-password-123",
    })
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "user"

    cookie = login.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["mobile"] == "9876543210"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_regular_user_cannot_access_admin_data_or_dashboard(client):
    assert create_user(client).status_code == 200
    assert client.post("/api/auth/login", json={
        "mobile": "9876543210",
        "password": "user-password-123",
    }).status_code == 200

    assert client.get("/api/users").status_code == 403
    assert client.get("/api/applications").status_code == 403
    assert client.get("/admin.html").status_code == 403
    assert client.get("/H%20login.html").status_code == 200


def test_environment_provisioned_admin_can_access_admin_dashboard(client):
    login = client.post("/api/auth/login", json={
        "mobile": "9999999999",
        "password": "CI-only-admin-password-12345",
    })
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"
    assert client.get("/api/users").status_code == 200
    assert client.get("/admin.html").status_code == 200


def test_document_upload_is_disabled_on_free_hosting(client):
    assert create_user(client).status_code == 200
    assert client.post("/api/auth/login", json={
        "mobile": "9876543210",
        "password": "user-password-123",
    }).status_code == 200

    response = client.post("/api/upload", files={
        "file": ("sample.pdf", b"%PDF-1.4 test", "application/pdf")
    })
    assert response.status_code == 503
