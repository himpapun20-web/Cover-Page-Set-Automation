from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .models import Company, SignupInvitation, User

router = APIRouter(prefix="/api/auth", tags=["authentication"])
HUMAN_ROLES = {"ADMIN", "PROJECT_MANAGER", "OPERATOR", "VIEWER"}
_login_failures: dict[str, tuple[int, float]] = {}
_login_failures_lock = threading.Lock()
_LOGIN_FAILURE_LIMIT = 5
_LOGIN_FAILURE_WINDOW = 15 * 60


class PasswordLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class PasswordUpdate(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class PasswordSignup(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invite_code: str = Field(min_length=20, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)
    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=12, max_length=128)


def hash_password(password: str) -> str:
    if len(password) < 12 or len(password) > 128:
        raise ValueError("Passwords must be between 12 and 128 characters.")
    salt = secrets.token_bytes(16)
    password_hash = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${password_hash.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, n, r, p, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "scrypt":
            return False
        expected = bytes.fromhex(hash_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def _session_secret() -> str:
    return os.getenv("CCTV_AUTH_SECRET") or _signing_secret()


def _login_is_blocked(email: str) -> bool:
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    now = time.monotonic()
    with _login_failures_lock:
        expired = [item for item, (_, until) in _login_failures.items() if until <= now]
        for item in expired:
            del _login_failures[item]
        failures, blocked_until = _login_failures.get(key, (0, 0))
        return failures >= _LOGIN_FAILURE_LIMIT and blocked_until > now


def _record_login_failure(email: str) -> None:
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    now = time.monotonic()
    with _login_failures_lock:
        failures, blocked_until = _login_failures.get(key, (0, 0))
        if blocked_until <= now:
            failures, blocked_until = 0, 0
        failures += 1
        _login_failures[key] = (failures, now + _LOGIN_FAILURE_WINDOW)


def _clear_login_failures(email: str) -> None:
    key = hashlib.sha256(email.strip().lower().encode()).hexdigest()
    with _login_failures_lock:
        _login_failures.pop(key, None)


def _require_password_auth() -> None:
    if os.getenv("CCTV_AUTH_MODE", "manus").strip().lower() != "password":
        raise HTTPException(status_code=404, detail="Email and password account access is not enabled.")
    if not _session_secret() or len(_session_secret()) < 32:
        raise HTTPException(status_code=503, detail="Password sign-in is not configured with a strong CCTV_AUTH_SECRET.")


def _invite_code_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _password_user_from_request(request: Request, db: Session) -> User:
    token = request.cookies.get("cctv_app_session")
    if not token or not _session_secret():
        raise HTTPException(status_code=401, detail="Please sign in with your email and password.")
    try:
        claims = jwt.decode(token, _session_secret(), algorithms=["HS256"])
        if claims.get("auth_mode") != "password":
            raise jwt.InvalidTokenError("Incorrect authentication mode")
        user_id = UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="The sign-in session is invalid or has expired.") from exc
    user = db.get(User, user_id)
    if not user or not user.is_active or user.role == "AI_SERVICE":
        raise HTTPException(status_code=401, detail="This account is unavailable. Please contact an administrator.")
    return user


def _set_password_cookie(request: Request, user: User, response: Response) -> None:
    secret = _session_secret()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="CCTV_AUTH_SECRET must contain at least 32 characters.")
    token = jwt.encode(
        {"sub": str(user.id), "auth_mode": "password", "exp": datetime.now(timezone.utc) + timedelta(hours=12)},
        secret,
        algorithm="HS256",
    )
    response.set_cookie(
        "cctv_app_session",
        token,
        max_age=43200,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        path="/",
    )


def _check_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        origin_host = urlsplit(origin).netloc.casefold()
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="The request origin is invalid.") from exc
    expected_host = request.headers.get("x-forwarded-host", request.headers.get("host", "")).split(",")[0].strip().casefold()
    if not expected_host or origin_host != expected_host:
        raise HTTPException(status_code=403, detail="Cross-origin account changes are not allowed.")


def _cookie_secure(request: Request) -> bool:
    # Public Preview is HTTPS even when the upstream development server receives HTTP.
    return request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip().lower() == "https"


def _public_base(request: Request) -> str:
    configured = os.getenv("APP_BASE_URL")
    if configured:
        return configured.rstrip("/")
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", "localhost")).split(",")[0].strip()
    return f"{scheme}://{host}"


def _signing_secret() -> str:
    return os.getenv("MANUS_JWT_SECRET", "")


def _identity(payload: dict) -> tuple[str | None, str | None, str | None]:
    return (
        payload.get("openId") or payload.get("open_id") or payload.get("sub"),
        payload.get("email"),
        payload.get("name") or payload.get("fullName") or payload.get("full_name"),
    )


def _resolve_user(db: Session, open_id: str, email: str, full_name: str | None) -> User:
    user = db.scalar(select(User).where(User.open_id == open_id)) or db.scalar(select(User).where(User.email == email.lower()))
    if not user:
        company = db.scalar(select(Company).order_by(Company.created_at))
        if not company:
            raise HTTPException(status_code=503, detail="No company records exist; run the database seed first.")
        bootstrap_email = os.getenv("CCTV_ADMIN_EMAIL", "").strip().lower()
        has_real_account = bool(db.scalar(select(func.count(User.id)).where(~User.email.like("%@example.test"))))
        # First real Manus identity becomes the administrator. Synthetic seed accounts never satisfy this check.
        if bootstrap_email:
            role = "ADMIN" if email.lower() == bootstrap_email else "VIEWER"
        else:
            role = "ADMIN" if not has_real_account else "VIEWER"
        user = User(company_id=company.id, full_name=full_name or email, email=email.lower(), open_id=open_id, role=role, is_active=True)
        db.add(user)
    else:
        if not user.is_active:
            raise HTTPException(status_code=403, detail="This user account is disabled.")
        user.open_id = open_id
        user.full_name = full_name or user.full_name
        user.email = email.lower()
    if user.role == "AI_SERVICE":
        raise HTTPException(status_code=403, detail="AI_SERVICE accounts are reserved for internal system use.")
    user.last_login_at = datetime.now(timezone.utc)
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth_mode = os.getenv("CCTV_AUTH_MODE", "manus").strip().lower()
    if auth_mode == "local":
        return _local_demo_user(request, db)
    if auth_mode == "password":
        if not _session_secret() or len(_session_secret()) < 32:
            raise HTTPException(status_code=503, detail="Password sign-in is not configured with a strong CCTV_AUTH_SECRET.")
        return _password_user_from_request(request, db)
    if auth_mode != "manus":
        raise HTTPException(status_code=503, detail="CCTV_AUTH_MODE accepts only manus, local or password.")
    token = request.cookies.get("webdev_app_session")
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token or not _signing_secret():
        raise HTTPException(status_code=401, detail="Please sign in with a Manus account.")
    try:
        claims = jwt.decode(token, _signing_secret(), algorithms=["HS256"], options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="The sign-in token is invalid or has expired.") from exc
    expected_app = os.getenv("MANUS_PROJECT_ID")
    if expected_app and claims.get("appId") != expected_app:
        raise HTTPException(status_code=401, detail="The sign-in token does not belong to this application.")
    open_id, email, full_name = _identity(claims)
    if not open_id or not email:
        raise HTTPException(status_code=401, detail="The sign-in token does not contain valid Manus account data.")
    user = _resolve_user(db, open_id, email, full_name)
    db.commit()
    return user


def _local_demo_user(request: Request, db: Session) -> User:
    if os.getenv("APP_ENV", "production").strip().lower() != "development":
        raise HTTPException(status_code=503, detail="Local demo login is only available when APP_ENV=development.")
    client = request.client
    if not client or client.host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="Local demo login is restricted to localhost.")
    email = os.getenv("CCTV_LOCAL_AUTH_EMAIL", "admin@example.test").strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if not user or not user.is_active:
        raise HTTPException(status_code=503, detail="No active local demo user was found; run the database seed first.")
    if user.role == "AI_SERVICE":
        raise HTTPException(status_code=403, detail="AI_SERVICE accounts are reserved for internal system use.")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return user


def require_roles(*roles: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Your role does not permit this operation.")
        return user
    return dependency


@router.get("/session")
def get_session(request: Request, db: Session = Depends(get_db)):
    auth_mode = os.getenv("CCTV_AUTH_MODE", "manus").strip().lower()
    if auth_mode == "local":
        user = _local_demo_user(request, db)
        return {"authenticated": True, "auth_mode": "local-demo", "user": {"id": str(user.id), "name": user.full_name, "email": user.email, "role": user.role}}
    if auth_mode == "password":
        if not request.cookies.get("cctv_app_session"):
            return {"authenticated": False, "auth_mode": "password"}
        try:
            user = current_user(request, db)
        except HTTPException as exc:
            if exc.status_code == 401:
                return {"authenticated": False, "auth_mode": "password"}
            raise
        return {"authenticated": True, "auth_mode": "password", "user": {"id": str(user.id), "name": user.full_name, "email": user.email, "role": user.role}}
    token = request.cookies.get("webdev_app_session")
    if not token and request.headers.get("authorization", "").lower().startswith("bearer "):
        token = request.headers["authorization"][7:].strip()
    if not token:
        return {"authenticated": False, "login_url": "/api/auth/login"}
    user = current_user(request, db)
    return {"authenticated": True, "user": {"id": str(user.id), "name": user.full_name, "email": user.email, "role": user.role}}


@router.post("/login")
def password_login(payload: PasswordLogin, request: Request, db: Session = Depends(get_db)):
    _require_password_auth()
    _check_same_origin(request)

    email = payload.email.strip().lower()
    if _login_is_blocked(email):
        raise HTTPException(status_code=429, detail="Too many failed sign-in attempts. Try again in 15 minutes.")
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    password_matches = verify_password(payload.password, user.password_hash if user else _DUMMY_PASSWORD_HASH)
    if not user or not user.is_active or user.role == "AI_SERVICE" or not password_matches:
        _record_login_failure(email)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    _clear_login_failures(email)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    response = Response(status_code=204)
    _set_password_cookie(request, user, response)
    return response


@router.post("/invitations", status_code=201)
def create_signup_invitation(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("ADMIN")),
):
    _require_password_auth()
    _check_same_origin(request)
    code = secrets.token_urlsafe(32)
    invitation = SignupInvitation(
        company_id=admin.company_id,
        code_hash=_invite_code_hash(code),
        created_by=admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invitation)
    db.commit()
    return {"code": code, "expires_at": invitation.expires_at}


@router.post("/signup", status_code=204)
def password_signup(payload: PasswordSignup, request: Request, db: Session = Depends(get_db)):
    _require_password_auth()
    _check_same_origin(request)
    email = payload.email.lower()
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="An account with this email address already exists.")

    now = datetime.now(timezone.utc)
    invitation = db.scalar(
        select(SignupInvitation).where(
            SignupInvitation.code_hash == _invite_code_hash(payload.invite_code),
            SignupInvitation.used_at.is_(None),
            SignupInvitation.expires_at > now,
        )
    )
    if not invitation:
        raise HTTPException(status_code=400, detail="This invitation is invalid, expired or already used.")

    user = User(
        company_id=invitation.company_id,
        full_name=payload.full_name,
        email=email,
        password_hash=hash_password(payload.password),
        role="VIEWER",
        is_active=True,
        last_login_at=now,
    )
    claimed = db.execute(
        update(SignupInvitation)
        .where(
            SignupInvitation.id == invitation.id,
            SignupInvitation.used_at.is_(None),
            SignupInvitation.expires_at > now,
        )
        .values(used_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="This invitation is invalid, expired or already used.")
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email address already exists.") from exc

    response = Response(status_code=204)
    _set_password_cookie(request, user, response)
    return response


@router.put("/users/{user_id}/password", status_code=204)
def set_user_password(
    user_id: UUID,
    payload: PasswordUpdate,
    request: Request,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_roles("ADMIN")),
):
    if os.getenv("CCTV_AUTH_MODE", "manus").strip().lower() != "password":
        raise HTTPException(status_code=404, detail="Password account management is not enabled.")
    _check_same_origin(request)
    user = db.get(User, user_id)
    if not user or user.role == "AI_SERVICE":
        raise HTTPException(status_code=404, detail="The requested human account was not found.")
    try:
        user.password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return Response(status_code=204)


@router.get("/login")
def login(request: Request):
    auth_mode = os.getenv("CCTV_AUTH_MODE", "manus").strip().lower()
    if auth_mode in {"local", "password"}:
        return RedirectResponse("/", status_code=303)
    if not all(os.getenv(name) for name in ("MANUS_PROJECT_ID", "MANUS_OAUTH_PORTAL_URL", "MANUS_JWT_SECRET")):
        raise HTTPException(status_code=503, detail="Manus OAuth is not configured for this project.")
    nonce = secrets.token_urlsafe(24)
    redirect_uri = f"{_public_base(request)}/api/auth/callback"
    state_payload = {"redirectUri": redirect_uri, "nonce": nonce}
    state = base64.urlsafe_b64encode(json.dumps(state_payload, separators=(",", ":")).encode()).decode().rstrip("=")
    portal = os.environ["MANUS_OAUTH_PORTAL_URL"].rstrip("/") + "/app-auth"
    response = RedirectResponse(portal + "?" + urlencode({"appId": os.environ["MANUS_PROJECT_ID"], "redirectUri": redirect_uri, "state": state, "responseType": "code"}), status_code=302)
    secure = _cookie_secure(request)
    response.set_cookie("cctv_oauth_state", nonce, max_age=600, httponly=True, secure=secure, samesite="none" if secure else "lax", path="/api/auth")
    return response


@router.get("/callback")
async def callback(request: Request, code: str, state: str, db: Session = Depends(get_db)):
    try:
        padded = state + "=" * (-len(state) % 4)
        state_data = json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The sign-in state is invalid.") from exc
    nonce = request.cookies.get("cctv_oauth_state")
    if not nonce or not secrets.compare_digest(nonce, str(state_data.get("nonce", ""))):
        raise HTTPException(status_code=400, detail="Sign-in state verification failed. Please sign in again.")
    redirect_uri = str(state_data.get("redirectUri", ""))
    expected_uri = f"{_public_base(request)}/api/auth/callback"
    if not secrets.compare_digest(redirect_uri, expected_uri):
        raise HTTPException(status_code=400, detail="The callback origin does not match the origin that started sign-in.")
    api_base = os.getenv("MANUS_OAUTH_API_URL", "").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            token_response = await client.post(api_base + "/webdev.v1.WebDevAuthPublicService/ExchangeToken", json={"clientId": os.getenv("MANUS_PROJECT_ID"), "grantType": "authorization_code", "code": code, "redirectUri": redirect_uri})
            token_response.raise_for_status()
            access_token = token_response.json()["accessToken"]
            identity_response = await client.post(api_base + "/webdev.v1.WebDevAuthPublicService/GetUserInfo", json={"accessToken": access_token})
            identity_response.raise_for_status()
            identity = identity_response.json()
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Manus OAuth identity verification could not be completed.") from exc
    open_id, email, full_name = _identity(identity)
    if not open_id or not email:
        raise HTTPException(status_code=401, detail="OAuth did not return the required account identifiers.")
    user = _resolve_user(db, open_id, email, full_name)
    db.commit()
    claims = {"appId": os.getenv("MANUS_PROJECT_ID"), "openId": open_id, "email": email.lower(), "name": full_name or email, "exp": datetime.now(timezone.utc) + timedelta(hours=12)}
    session_token = jwt.encode(claims, _signing_secret(), algorithm="HS256")
    secure = _cookie_secure(request)
    result = RedirectResponse("/", status_code=303)
    result.set_cookie("webdev_app_session", session_token, max_age=43200, httponly=True, secure=secure, samesite="none" if secure else "lax", path="/")
    result.delete_cookie("cctv_oauth_state", path="/api/auth")
    return result


@router.post("/logout")
def logout(request: Request):
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("webdev_app_session", path="/", secure=_cookie_secure(request), samesite="none" if _cookie_secure(request) else "lax")
    response.delete_cookie("cctv_app_session", path="/", secure=_cookie_secure(request), samesite="lax")
    return response
