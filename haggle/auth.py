"""Per-user bearer credentials and signed, HttpOnly browser sessions."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from .config import ROOT


def required():
    """Login is OFF by default: the public demo is open (owner "local" for everyone, limits per IP).
    Turn it on with HAGGLE_REQUIRE_LOGIN=1 (single token: HAGGLE_ACCESS_TOKEN) or HAGGLE_USERS (per-user tokens)."""
    return os.environ.get("HAGGLE_REQUIRE_LOGIN") == "1" or bool(os.environ.get("HAGGLE_USERS"))


def users():
    configured = os.environ.get("HAGGLE_USERS")
    if configured:
        result = json.loads(configured)
        if not isinstance(result, dict) or not result or any(not isinstance(k, str) or ":" in k or not k for k in result) or any(not isinstance(v, str) or len(v) < 16 for v in result.values()):
            raise ValueError("HAGGLE_USERS must map usernames to tokens of at least 16 characters")
        if len(set(result.values())) != len(result):
            raise ValueError("each user needs a unique token")
        return result
    token = os.environ.get("HAGGLE_ACCESS_TOKEN")
    if not token:
        path = Path(os.environ.get("HAGGLE_TOKEN_FILE", str(ROOT / "runs" / "access-token")))
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("x") as f:
                path.chmod(0o600)
                f.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        token = path.read_text().strip()
    if len(token) < 16:
        raise ValueError("access token must contain at least 16 characters")
    return {"local": token}


def authenticate(token):
    if not isinstance(token, str):
        return None
    return next((name for name, secret in users().items() if hmac.compare_digest(token.encode(), secret.encode())), None)


def session(owner):
    expires = int(time.time()) + 24 * 3600
    data = f"{owner}:{expires}"
    sig = hmac.new(users()[owner].encode(), data.encode(), hashlib.sha256).hexdigest()
    return f"{data}:{sig}"


def identity(request):
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        return authenticate(authorization[7:])
    value = request.cookies.get("haggle_session", "")
    try:
        owner, expires, sig = value.rsplit(":", 2)
        secret = users().get(owner)
        if not secret or int(expires) <= time.time():
            return None
        expected = hmac.new(secret.encode(), f"{owner}:{expires}".encode(), hashlib.sha256).hexdigest()
        return owner if hmac.compare_digest(sig, expected) else None
    except (ValueError, TypeError):
        return None
