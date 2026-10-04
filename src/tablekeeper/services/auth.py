from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tablekeeper.config import settings
from tablekeeper.errors import AppError
from tablekeeper.models import MembershipRole, RestaurantMembership, User


def create_access_token(user_id: uuid.UUID, *, expires_in_seconds: int = 3600) -> str:
    """Create a compact HMAC-signed bearer token for a user."""
    if not settings.auth_token_secret:
        raise RuntimeError("TABLEKEEPER_AUTH_TOKEN_SECRET must be configured")
    payload = json.dumps(
        {"sub": str(user_id), "exp": int(time.time()) + expires_in_seconds},
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
    signature = hmac.new(settings.auth_token_secret.encode(), encoded, hashlib.sha256).digest()
    return encoded.decode() + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()


def verify_access_token(token: str) -> uuid.UUID:
    """Verify token signature and expiry, returning its authenticated subject."""
    try:
        encoded, signature_text = token.split(".", 1)
        signature = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        expected = hmac.new(settings.auth_token_secret.encode(), encoded.encode(), hashlib.sha256).digest()
        if not settings.auth_token_secret or not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        payload_bytes = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(payload_bytes)
        user_id = uuid.UUID(payload["sub"])
        if not isinstance(payload["exp"], int) or payload["exp"] <= int(time.time()):
            raise ValueError("expired token")
        return user_id
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise AppError("unauthenticated", "Missing or invalid bearer token", status_code=401) from exc


def ensure_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id, email=f"{user_id}@example.local", name="Tablekeeper User")
        db.add(user)
        db.flush()
    return user


def require_staff(db: Session, user_id: uuid.UUID, restaurant_id: uuid.UUID) -> RestaurantMembership:
    membership = db.scalar(
        select(RestaurantMembership).where(
            RestaurantMembership.user_id == user_id,
            RestaurantMembership.restaurant_id == restaurant_id,
        )
    )
    if membership is None or membership.role not in {MembershipRole.owner, MembershipRole.manager, MembershipRole.staff}:
        raise AppError("forbidden", "Restaurant staff access required", status_code=403)
    return membership
