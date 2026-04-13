from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Role, User
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
