from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Role, User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def get_user_from_token(token: str, db: Session) -> User | None:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        email = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None
    return db.scalar(select(User).where(User.email == email))


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    settings = get_settings()
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    user = get_user_from_token(token, db)
    if not user or not user.active:
        raise credentials_error
    return user


def require_roles(*roles: Role):
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.must_change_password:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Password change required")
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency


CanView = Annotated[User, Depends(require_roles(Role.admin, Role.supervisor, Role.analyst, Role.viewer))]
CanLabel = Annotated[User, Depends(require_roles(Role.admin, Role.supervisor, Role.analyst))]
CanTrain = Annotated[User, Depends(require_roles(Role.admin, Role.supervisor))]
CanConfigure = Annotated[User, Depends(require_roles(Role.admin))]
