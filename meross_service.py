import json
from typing import Any, Dict, List, Optional

from firestore_repo import FirestoreRepo

# 注意：meross-iot 版本可能導致 import / method 名不同
from meross_iot.http_api import MerossHttpClient  # type: ignore


class MerossService:
    def __init__(self, repo: FirestoreRepo):
        self.repo = repo

    async def connect_account(self, email: str, password: str) -> Dict[str, Any]:
        """
        1) 用 Meross 雲端登入
        2) 拉取裝置列表
        3) 保存 account auth + devices
        """
        http: Optional[Any] = None

        try:
            try:
                http = await MerossHttpClient.async_from_user_password(
                    api_base_url="https://iot.meross.com",
                    email=email,
                    password=password,
                )  # type: ignore
            except Exception:
                # 不要回傳底層 exception（可能包含敏感資訊）
                raise ValueError("Meross login failed. Please verify email/password and try again.")

            # 取 token / session（不同版本可能叫 cloud_credentials / token 等）
            token_payload: Dict[str, Any]
            if hasattr(http, "cloud_credentials"):
                token_payload = {"cloud_credentials": getattr(http, "cloud_credentials")}
            elif hasattr(http, "token"):
                token_payload = {"token": getattr(http, "token")}
            else:
                # 最少要保存一個可追溯的結構，避免空字串
                token_payload = {"session": "unknown"}

            token_plain = json.dumps(token_payload, ensure_ascii=False)

            # 拉裝置
            devices_raw = await http.async_list_devices()  # type: ignore
            devices = self._normalize_devices(devices_raw)

            # Upsert：同一 email 用同一 accountId（避免無限新增）
            account_id = self.repo.upsert_account_auth_by_email(email=email, token_plain=token_plain)
            self.repo.set_account_devices(account_id=account_id, devices=[d for d in devices])

            # 登出（如支援）
            try:
                await http.async_logout()  # type: ignore
            except Exception:
                pass

            return {
                "accountId": account_id,
                "status": "connected",
                "devices": devices,
            }
        finally:
            # 釋放連線
            if http is not None:
                try:
                    await http.async_close()  # type: ignore
                except Exception:
                    pass

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        """
        MVP：暫未支援用 token 重建 session 再 sync
        """
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")

        # MVP：暫不支援 token-based sync
        raise ValueError(
            "Token-based sync is not enabled in MVP. Please reconnect with email/password to refresh devices."
        )

    def _normalize_devices(self, devices_raw: Any) -> List[Dict[str, Any]]:
        devices: List[Dict[str, Any]] = []

        if isinstance(devices_raw, list):
            for d in devices_raw:
                if isinstance(d, dict):
                    device_id = d.get("uuid") or d.get("deviceId") or d.get("id") or ""
                    devices.append(
                        {
                            "deviceId": device_id,
                            "name": d.get("devName") or d.get("name"),
                            "model": d.get("deviceType") or d.get("model"),
                            "type": d.get("deviceType") or d.get("type"),
                            "onlineStatus": d.get("onlineStatus") if isinstance(d.get("onlineStatus"), bool) else None,
                            "capabilities": d.get("abilities") or d.get("capabilities") or None,
                        }
                    )
                else:
                    device_id = getattr(d, "uuid", "") or getattr(d, "device_id", "") or ""
                    devices.append(
                        {
                            "deviceId": device_id,
                            "name": getattr(d, "name", None),
                            "model": getattr(d, "model", None),
                            "type": getattr(d, "type", None),
                            "onlineStatus": getattr(d, "online_status", None),
                            "capabilities": getattr(d, "abilities", None) or getattr(d, "capabilities", None),
                        }
                    )

        return devices