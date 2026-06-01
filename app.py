"""
FastAPI backend for the API 16D Accumulator Sizing calculator.

All confidential data (the NIST nitrogen grid, the Cameron EB702D master-lookup
constants, the BOP specs) and every formula live here, server-side. The browser
only ever sends a plain inputs dict and receives computed results.

Access control: clients log in with a username/password (POST /api/login). The
server verifies it against stored PBKDF2 hashes (users.json) and returns a
short-lived HMAC-signed token. Every protected call carries that token; the
server re-verifies it before running any calculation or returning any data.

Environment variables (see .env.example):
  SECRET_KEY       Secret used to sign/verify login tokens. REQUIRED in prod.
  ALLOWED_ORIGINS  Comma-separated browser origins for CORS (your Pages URL).
"""
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

import json

import engine
import engine2
import nist
import userauth

# ---- Configuration -------------------------------------------------------
# If SECRET_KEY is not set we generate a random one. That still works, but every
# server restart invalidates existing tokens (users just log in again). Set a
# stable SECRET_KEY in production.
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip() or secrets.token_hex(32)

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "").split(",")
    if o.strip()
] or ["http://localhost:8123"]

# How long a login token stays valid.
TOKEN_TTL_SECONDS = int(os.environ.get("TOKEN_TTL_SECONDS", str(12 * 3600)))

app = FastAPI(title="API 16D Accumulator Sizing", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ---- Auth ----------------------------------------------------------------
def require_user(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing token.")
    token = authorization.split(" ", 1)[1].strip()
    username = userauth.verify_token(token, SECRET_KEY)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return username


# ---- Request models ------------------------------------------------------
class LoginInput(BaseModel):
    username: str
    password: str


class ShearInput(BaseModel):
    bopType: Optional[str] = None
    ramType: Optional[str] = None
    pipeGrade: Optional[str] = None
    od: float
    wall: float
    ppf: float
    pw: float
    maxOpOverride: Optional[float] = None


class ComputeInput(BaseModel):
    atmospheric: float
    surfaceTemp: float
    tempRange: float
    rwp: float
    mopOverride: Optional[float] = None
    prechargeOverride: Optional[float] = None
    shear: ShearInput
    methodBRows: List[Dict[str, Any]] = []
    methodCRows: List[Dict[str, Any]] = []


# ---- 2nd edition (Dixstone): Method A + Method B ------------------------
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_NIST = None  # lazy-loaded shared NIST grid


def _get_nist():
    global _NIST
    if _NIST is None:
        _NIST = nist.load_nist()
    return _NIST


def _load_bop_specs2():
    with open(os.path.join(_DATA_DIR, "bopSpecs2.json"), "r", encoding="utf-8") as f:
        return json.load(f)


class Compute2Input(BaseModel):
    atm: float = 14.7
    surfaceTempF: float = 85.0
    maxSurfaceTempF: float = 100.0
    chargedPsig: float
    prechargePsig: float
    operatorShearPsig: float = 0.0
    gasVolPerBottle: float = 11.0
    bottleRatingPsig: float = 3000.0
    fvrOverride: Optional[float] = None
    equipment: List[Dict[str, Any]] = []


# ---- Endpoints -----------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/login")
def login(body: LoginInput):
    record = userauth.find_user(body.username)
    if not record or not userauth.verify_password(body.password, record):
        # Same message for unknown user vs. wrong password (no user enumeration).
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    username = body.username.strip().lower()
    token = userauth.make_token(username, SECRET_KEY, TOKEN_TTL_SECONDS)
    return {"token": token, "username": username, "expiresIn": TOKEN_TTL_SECONDS}


@app.get("/api/meta")
def get_meta(_user: str = Depends(require_user)):
    """Non-secret data (BOP specs + dropdown lists) the UI needs to render."""
    return engine.meta()


@app.post("/api/compute")
def post_compute(inp: ComputeInput, _user: str = Depends(require_user)):
    return engine.compute(inp.model_dump())


@app.get("/api/meta2")
def get_meta2(_user: str = Depends(require_user)):
    """2nd-edition BOP Stack catalogue (no secret constants)."""
    return {"bopSpecs": _load_bop_specs2()}


@app.post("/api/compute2")
def post_compute2(inp: Compute2Input, _user: str = Depends(require_user)):
    """2nd edition (Dixstone): Method A (ideal gas) + Method B (NIST density)."""
    return engine2.compute(inp.model_dump(), _get_nist())
