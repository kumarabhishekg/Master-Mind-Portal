"""MongoDB-backed account storage with SQL fallback for local development.

Set MONGODB_URI on the server to make MongoDB the source of truth for users.
The portal's service requests, uploads, and print queue continue to use the
existing SQL database so they can be moved to the planned Google datastore
separately.
"""

import os
from types import SimpleNamespace

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, MongoClient


MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "mastermind_portal").strip() or "mastermind_portal"
if os.getenv("MONGO_AUTH_REQUIRED", "false").lower() == "true" and not MONGODB_URI:
    raise RuntimeError("MONGO_AUTH_REQUIRED is enabled but MONGODB_URI is missing")

_client = None
_users = None


def mongo_enabled() -> bool:
    return bool(MONGODB_URI)


def init_mongo_users():
    """Connect and ensure MongoDB account uniqueness before serving requests."""
    global _client, _users
    if not mongo_enabled():
        return None
    if _users is None:
        _client = MongoClient(MONGODB_URI, appname="mastermind-portal", serverSelectionTimeoutMS=8000)
        _client.admin.command("ping")
        _users = _client[MONGODB_DATABASE]["users"]
        _users.create_index([("mobile", ASCENDING)], unique=True, name="uniq_mobile")
    return _users


def users_collection():
    collection = init_mongo_users()
    if collection is None:
        raise RuntimeError("MONGODB_URI is not configured")
    return collection


def user_from_document(document):
    if document is None:
        return None
    return SimpleNamespace(
        id=str(document["_id"]),
        name=document.get("name", ""),
        mobile=document["mobile"],
        email=document.get("email", ""),
        password=document.get("password", ""),
        status=document.get("status", "Active"),
        role=document.get("role", "user"),
    )


def find_user_by_mobile(mobile: str):
    return user_from_document(users_collection().find_one({"mobile": mobile}))


def find_user_by_id(user_id: str):
    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        return None
    return user_from_document(users_collection().find_one({"_id": object_id}))


def list_users():
    return [user_from_document(doc) for doc in users_collection().find().sort("_id", -1)]


def update_user(user_id: str, values: dict):
    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        return False
    result = users_collection().update_one({"_id": object_id}, {"$set": values})
    return result.matched_count == 1


def delete_user(user_id: str):
    try:
        object_id = ObjectId(user_id)
    except InvalidId:
        return False
    result = users_collection().delete_one({"_id": object_id})
    return result.deleted_count == 1


def migrate_legacy_users(legacy_users):
    """Copy SQL accounts to MongoDB without overwriting existing Mongo users."""
    collection = users_collection()
    for legacy in legacy_users:
        collection.update_one(
            {"mobile": legacy.mobile},
            {"$setOnInsert": {
                "name": legacy.name,
                "mobile": legacy.mobile,
                "email": legacy.email or "",
                "password": legacy.password or "",
                "status": legacy.status or "Active",
                "role": getattr(legacy, "role", "user") or "user",
            }},
            upsert=True,
        )
