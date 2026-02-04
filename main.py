import os
import uuid
import logging
import traceback
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from models import (
    CreateAccountRequest,
    CreateAccountResponse,
    ErrorResponse,
    SyncResponse,
    DevicesResponse,
)
from firestore_repo import FirestoreRepo
from meross_service import MerossService

APP_NAME = "meross-connector-api"

logger = logging.getLogger("app")
logger.setLevel(logging.INFO)

def require_admin(x_admin_key: Optional[str]) -> None:
    expected = os.getenv("ADMIN_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=500, detail="Server misconfigured: ADMIN_API_KEY not set.")
    if not x_admin_key or x_admin_key.strip() != expected:
        raise HTTPException(status_code=403, detail="Forbidden.")

app = FastAPI(title=APP_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

repo = FirestoreRepo()
meross = MerossService(repo=repo)

@app.get("/health")
def health():
    return {"ok": True, "service": APP_NAME}

@app.post(
    "/accounts",
    response_model=CreateAccountResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
async def create_account(
    payload: CreateAccountRequest,
    request: Request,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    require_admin(x_admin_key)

    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="email and password are required.")

    req_id = str(uuid.uuid4())[:8]

    try:
        result = await meross.connect_account(email=payload.email, password=payload.password)
        return CreateAccountResponse(
            accountId=result["accountId"],
            status=result["status"],
            devices=result["devices"],
        )
    except ValueError as e:
        # 仍然係 login failed / business error → 401
        logger.warning("req_id=%s /accounts login failed: %s", req_id, str(e))
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # 500：打印 traceback（唔包含 email/password；但 traceback 會顯示程式行號/方法名）
        tb = traceback.format_exc()
        logger.error("req_id=%s /accounts internal error type=%s\n%s", req_id, type(e).__name__, tb)
        raise HTTPException(status_code=500, detail=f"Internal error ({req_id}): {type(e).__name__}")