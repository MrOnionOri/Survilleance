from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DEFAULT_EVENT_CATEGORIES, EventCategory, Role, User
from app.security import hash_password


def seed_admin(db: Session) -> None:
    settings = get_settings()
    existing = db.scalar(select(User).where(User.email == settings.admin_email))
    if existing:
        existing.password_hash = hash_password(settings.admin_password)
        existing.role = Role.admin
        db.commit()
        return

    db.add(
        User(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            role=Role.admin,
        )
    )
    db.commit()


def seed_event_categories(db: Session) -> None:
    existing_keys = set(db.scalars(select(EventCategory.key)).all())
    for key, name, critical in DEFAULT_EVENT_CATEGORIES:
        if key in existing_keys:
            continue
        db.add(EventCategory(key=key, name=name, critical=critical))
    db.commit()
