"""FastAPI backend: JWT auth, AWS discovery, Gemini analysis, history, WebSocket progress."""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from ai_analyzer import GeminiAnalyzerError, analyze_resources
from auth import (
    AuthError,
    create_access_token,
    get_current_user,
    hash_password,
    user_from_token_string,
    verify_password,
)
from aws_scanner import AwsScannerError, list_aws_regions, scan_region
from db import (
    DatabaseError,
    close_db,
    create_user,
    get_analysis_for_user,
    get_user_by_email,
    init_db,
    insert_analysis,
    list_analyses_for_user,
    ping_db,
    update_analysis,
)

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR.parent / ".env")


class ProgressHub:
    """Fan-out progress events to WebSocket clients, with replay for late subscribers."""

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)

    async def connect(self, analysis_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[analysis_id].add(websocket)
        for message in self._history[analysis_id]:
            await websocket.send_json(message)

    def disconnect(self, analysis_id: str, websocket: WebSocket) -> None:
        self._connections[analysis_id].discard(websocket)

    async def publish(self, analysis_id: str, message: str, *, percent: int, status: str) -> None:
        payload = {
            "analysis_id": analysis_id,
            "message": message,
            "percent": percent,
            "status": status,
        }
        self._history[analysis_id].append(payload)
        stale: list[WebSocket] = []
        for websocket in list(self._connections[analysis_id]):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            self._connections[analysis_id].discard(websocket)


progress_hub = ProgressHub()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="AI Cloud Cost Detective",
    description="JWT auth, read-only AWS discovery, Gemini analysis, PostgreSQL history, live progress.",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AuthRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)


class AnalyzeRequest(BaseModel):
    region: str = Field(..., min_length=1, description="AWS region to scan, e.g. ap-south-1")
    analysis_id: UUID | None = Field(
        default=None,
        description="Optional UUID so the client can subscribe to /ws/progress/{analysis_id} first.",
    )


def _http_error(exc: AwsScannerError | GeminiAnalyzerError | DatabaseError | AuthError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _public_user(user_id: UUID, email: str) -> dict[str, str]:
    return {"id": str(user_id), "email": email}


def _token_response(user_id: UUID, email: str) -> dict[str, Any]:
    return {
        "token": create_access_token(user_id=user_id, email=email),
        "token_type": "bearer",
        "user": _public_user(user_id, email),
    }


def _savings_text(analysis: dict[str, Any]) -> str:
    savings = analysis.get("estimated_savings") or {}
    if not isinstance(savings, dict):
        return str(savings)
    currency = savings.get("currency") or "USD"
    low = savings.get("monthly_low")
    high = savings.get("monthly_high")
    if low is None and high is None:
        return str(savings.get("notes") or "")
    return f"{currency} {low}-{high} / month"


@app.get("/health")
async def health() -> dict[str, object]:
    db_ok = False
    try:
        db_ok = await ping_db()
    except DatabaseError:
        db_ok = False
    return {
        "status": "ok",
        "aws_region": os.getenv("AWS_REGION", ""),
        "aws_profile": os.getenv("AWS_PROFILE", ""),
        "gemini_configured": bool((os.getenv("GEMINI_API_KEY") or "").strip()),
        "database": "connected" if db_ok else "unavailable",
    }


@app.post("/api/auth/signup")
async def signup(payload: AuthRequest) -> dict:
    email = _normalize_email(payload.email)
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_EMAIL", "message": "Enter a valid email address."},
        )
    try:
        existing = await get_user_by_email(email)
        if existing:
            raise DatabaseError(
                "An account with this email already exists.",
                code="EMAIL_TAKEN",
                status_code=409,
            )
        password_hash = await asyncio.to_thread(hash_password, payload.password)
        user = await create_user(email=email, password_hash=password_hash)
        return _token_response(user["id"], user["email"])
    except (DatabaseError, AuthError) as exc:
        raise _http_error(exc) from exc


@app.post("/api/auth/login")
async def login(payload: AuthRequest) -> dict:
    email = _normalize_email(payload.email)
    try:
        user = await get_user_by_email(email)
        if not user:
            raise AuthError("Invalid email or password.", code="INVALID_CREDENTIALS")
        valid = await asyncio.to_thread(verify_password, payload.password, user["password_hash"])
        if not valid:
            raise AuthError("Invalid email or password.", code="INVALID_CREDENTIALS")
        return _token_response(user["id"], user["email"])
    except (DatabaseError, AuthError) as exc:
        raise _http_error(exc) from exc


@app.get("/api/auth/me")
async def me(current_user: dict = Depends(get_current_user)) -> dict:
    return {"user": _public_user(current_user["user_id"], current_user["email"])}


@app.get("/api/regions")
def get_regions(_current_user: dict = Depends(get_current_user)) -> dict:
    try:
        regions = list_aws_regions()
        return {"regions": regions, "default_region": os.getenv("AWS_REGION", "")}
    except AwsScannerError as exc:
        raise _http_error(exc) from exc


@app.get("/api/history")
async def get_history(current_user: dict = Depends(get_current_user)) -> dict:
    try:
        analyses = await list_analyses_for_user(current_user["user_id"])
    except DatabaseError as exc:
        raise _http_error(exc) from exc
    return {"user_id": str(current_user["user_id"]), "analyses": analyses}


@app.get("/api/history/{analysis_id}")
async def get_history_item(analysis_id: UUID, current_user: dict = Depends(get_current_user)) -> dict:
    try:
        item = await get_analysis_for_user(current_user["user_id"], analysis_id)
    except DatabaseError as exc:
        raise _http_error(exc) from exc
    if not item:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": "Analysis not found."},
        )
    return item


@app.websocket("/ws/progress/{analysis_id}")
async def progress_socket(websocket: WebSocket, analysis_id: str, token: str | None = None) -> None:
    try:
        user_from_token_string(token)
    except AuthError:
        await websocket.close(code=4401)
        return
    await progress_hub.connect(analysis_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress_hub.disconnect(analysis_id, websocket)


@app.post("/api/analyze")
async def analyze(
    payload: AnalyzeRequest,
    current_user: dict = Depends(get_current_user),
) -> dict:
    region = payload.region.strip()
    analysis_id = payload.analysis_id or uuid4()
    analysis_key = str(analysis_id)
    user_id = current_user["user_id"]

    try:
        await insert_analysis(
            analysis_id=analysis_id,
            user_id=user_id,
            region=region,
            status="running",
        )
    except Exception as exc:
        raise _http_error(DatabaseError(f"Failed to create analysis record: {exc}")) from exc

    async def emit(message: str, percent: int, status: str = "running") -> None:
        await progress_hub.publish(analysis_key, message, percent=percent, status=status)

    try:
        await emit("Fetching AWS resources...", 10)
        await emit(f"Scanning resources in {region}...", 30)
        scan = await asyncio.to_thread(scan_region, region)

        await emit("Analyzing costs with AI...", 60)
        analysis = await asyncio.to_thread(analyze_resources, scan)

        result = {
            "analysis_id": analysis_key,
            "region": scan["region"],
            "account_id": scan["account_id"],
            "scanned_at": scan["scanned_at"],
            "resource_count": scan["resource_count"],
            "counts_by_type": scan["counts_by_type"],
            "partial_errors": scan["partial_errors"],
            "resources": scan["resources"],
            "analysis": analysis,
        }
        issues_found = len((analysis or {}).get("issues") or [])

        await emit("Storing results...", 85)
        await update_analysis(
            analysis_id=analysis_id,
            status="complete",
            resources_scanned=int(scan.get("resource_count") or 0),
            issues_found=issues_found,
            estimated_savings=_savings_text(analysis),
            analysis_result=result,
        )
        await emit("Analysis complete", 100, status="complete")
        return result
    except (AwsScannerError, GeminiAnalyzerError, DatabaseError) as exc:
        await emit(f"Analysis failed: {exc.message}", 100, status="failed")
        try:
            await update_analysis(analysis_id=analysis_id, status="failed")
        except DatabaseError:
            pass
        raise _http_error(exc) from exc
    except Exception as exc:
        await emit(f"Analysis failed: {exc}", 100, status="failed")
        try:
            await update_analysis(analysis_id=analysis_id, status="failed")
        except DatabaseError:
            pass
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": str(exc)},
        ) from exc
