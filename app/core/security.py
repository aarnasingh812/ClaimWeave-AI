from datetime import datetime, timedelta, timezone
import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models import User

hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return hasher.verify(password, hashed)

def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': user_id, 'iat': now, 'exp': now + timedelta(minutes=settings.access_token_minutes)},
                      settings.jwt_secret, algorithm='HS256')

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=['HS256'])
        user_id = payload.get('sub')
        if not isinstance(user_id, str):
            raise InvalidTokenError('Missing subject')
    except InvalidTokenError:
        raise HTTPException(401, 'Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, 'Account not found')
    return user
