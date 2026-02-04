import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException
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
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def create_account(
    payload: CreateAccountRequest,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    require_admin(x_admin_key)

    if not payload.email or not payload.password:
        raise HTTPException(status_code=400, detail="email and password are required.")

    try:
        result = await meross.connect_account(email=payload.email, password=payload.password)
        return CreateAccountResponse(
            accountId=result["accountId"],
            status=result["status"],
            devices=result["devices"],
        )
    except ValueError as e:
        # Meross login failed / invalid account
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        # Do NOT log secrets
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")


@app.post(
    "/accounts/{account_id}/sync",
    response_model=SyncResponse,
    responses={
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def sync_devices(
    account_id: str,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    require_admin(x_admin_key)

    try:
        result = await meross.sync_devices(account_id=account_id)
        return SyncResponse(
            accountId=account_id,
            syncedAt=result["syncedAt"],
            devices=result["devices"],
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Account not found.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")


@app.get(
    "/accounts/{account_id}/devices",
    response_model=DevicesResponse,
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
async def get_devices(
    account_id: str,
    x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key"),
):
    require_admin(x_admin_key)

    try:
        data = repo.get_account_devices(account_id=account_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Account not found.")
        return DevicesResponse(
            accountId=account_id,
            lastSyncedAt=data.get("lastSyncedAt"),
            devices=data.get("devices", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {type(e).__name__}")