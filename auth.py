"""
B.L.I.T.Z. Auth Module — JWT passphrase login + rate limiting
"""
import os, time, hashlib, secrets
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from jose import jwt, JWTError
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY  = os.getenv("BLITZ_SECRET_KEY", secrets.token_hex(32))
PASSPHRASE  = os.getenv("BLITZ_PASSPHRASE", "blitz-jarvis-2025")  # set in .env
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 72

# ── Rate Limiter ──────────────────────────────────────────────────────────────
_rate_store: dict[str, list[float]] = {}   # ip → list of timestamps
RATE_LIMIT   = 60   # requests per window
RATE_WINDOW  = 60   # seconds


def rate_check(ip: str) -> bool:
    """Returns True if request is allowed."""
    now = time.time()
    history = _rate_store.get(ip, [])
    # Prune old entries
    history = [t for t in history if now - t < RATE_WINDOW]
    if len(history) >= RATE_LIMIT:
        _rate_store[ip] = history
        return False
    history.append(now)
    _rate_store[ip] = history
    return True


# ── JWT helpers ───────────────────────────────────────────────────────────────
def create_token(sub: str = "blitz-user") -> str:
    payload = {"sub": sub, "iat": int(time.time()), "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str) -> Optional[str]:
    try:
        data = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return data.get("sub")
    except JWTError:
        return None


# ── FastAPI Dependencies ───────────────────────────────────────────────────────
def get_token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    # Also check cookie
    return request.cookies.get("blitz_token")


async def require_auth(request: Request):
    ip = request.client.host if request.client else "unknown"
    if not rate_check(ip):
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Slow down.")
    token = get_token_from_request(request)
    if not token or not verify_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized. Please login.")


async def require_auth_ws(token: Optional[str], ip: str = "ws"):
    """For WebSocket auth — call manually."""
    if not rate_check(ip):
        return False
    if not token or not verify_token(token):
        return False
    return True
