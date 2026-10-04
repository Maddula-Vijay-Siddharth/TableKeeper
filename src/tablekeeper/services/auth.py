from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from tablekeeper.errors import AppError
from tablekeeper.models import MembershipRole, RestaurantMembership, User


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
