import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from crypto_utils import encrypt_str, decrypt_str

COL_ACCOUNTS = "merossAccounts"

class FirestoreRepo:
    def __init__(self):
        self.db = firestore.Client(project=os.getenv("GCP_PROJECT_ID") or None)

    def create_or_update_account_auth(self, email: str, token_plain: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        doc_ref = self.db.collection(COL_ACCOUNTS).document()
        doc_ref.set(
            {
                "email": email,
                "status": "connected",
                "createdAt": now,
                "lastSyncedAt": None,
                "auth": {
                    "tokenEncrypted": encrypt_str(token_plain),
                },
            }
        )
        return doc_ref.id

    def update_account_token(self, account_id: str, token_plain: str) -> None:
        doc_ref = self.db.collection(COL_ACCOUNTS).document(account_id)
        doc_ref.update(
            {
                "auth.tokenEncrypted": encrypt_str(token_plain),
                "status": "connected",
            }
        )

    def get_account_token(self, account_id: str) -> Optional[str]:
        doc_ref = self.db.collection(COL_ACCOUNTS).document(account_id)
        snap = doc_ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        auth = data.get("auth") or {}
        enc = auth.get("tokenEncrypted")
        if not enc:
            return None
        return decrypt_str(enc)

    def set_account_devices(self, account_id: str, devices: List[Dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        doc_ref = self.db.collection(COL_ACCOUNTS).document(account_id)
        doc_ref.update(
            {
                "devices": devices,
                "lastSyncedAt": now,
                "status": "connected",
            }
        )

    def get_account_devices(self, account_id: str) -> Optional[Dict[str, Any]]:
        doc_ref = self.db.collection(COL_ACCOUNTS).document(account_id)
        snap = doc_ref.get()
        if not snap.exists:
            return None
        return snap.to_dict() or {}