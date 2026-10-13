from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.security import create_access_token, current_user, hash_password, verify_password
from app.db.session import get_db
from app.models import User

router = APIRouter(prefix='/api/v1/auth', tags=['auth'])

class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)

class LoginCredentials(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = 'bearer'

@router.post('/register', response_model=Token, status_code=201)
def register(payload: Credentials, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if '@' not in email or email.startswith('@'):
        raise HTTPException(422, 'Invalid email address')
    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Email already registered')
    db.refresh(user)
    return Token(access_token=create_access_token(user.id))

@router.post('/login', response_model=Token)
def login(payload: LoginCredentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, 'Invalid email or password')
    return Token(access_token=create_access_token(user.id))

@router.get('/me')
def me(user: User = Depends(current_user)):
    return {'id': user.id, 'email': user.email}
