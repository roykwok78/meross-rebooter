from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Device(BaseModel):
    deviceId: str = Field(..., description="Meross device uuid/id")
    name: Optional[str] = None
    model: Optional[str] = None
    type: Optional[str] = None
    onlineStatus: Optional[bool] = None
    capabilities: Optional[Dict[str, Any]] = None

class CreateAccountRequest(BaseModel):
    email: str
    password: str

class CreateAccountResponse(BaseModel):
    accountId: str
    status: str
    devices: List[Device]

class SyncResponse(BaseModel):
    accountId: str
    syncedAt: str
    devices: List[Device]

class DevicesResponse(BaseModel):
    accountId: str
    lastSyncedAt: Optional[str] = None
    devices: List[Device]

class ErrorResponse(BaseModel):
    detail: str