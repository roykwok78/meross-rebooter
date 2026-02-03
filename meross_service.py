import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from firestore_repo import FirestoreRepo

# 注意：以下 import 名稱可能會因 meross-iot 版本而有差異
# 如果你部署 log 顯示 import error，我會根據你貼出嘅錯誤訊息，立即用「完整檔案」方式修正。
from meross_iot.http_api import MerossHttpClient  # type: ignore

class MerossService:
    def __init__(self, repo: FirestoreRepo):
        self.repo = repo

    async def connect_account(self, email: str, password: str) -> Dict[str, Any]:
        """
        1) 用 Meross 雲端登入
        2) 取回 token/session
        3) 拉取裝置列表
        4) 保存 token + devices
        """
        try:
            # 常見用法：MerossHttpClient.async_from_user_password(...)
            # 若版本不同，你貼錯誤，我會改成正確入口（例如 from_email_and_password 等）
            http = await MerossHttpClient.async_from_user_password(api_base_url="https://iot.meross.com", email=email, password=password)  # type: ignore
        except Exception:
            # 不要回傳底層 exception（可能包含敏感資訊）
            raise ValueError("Meross login failed. Please verify email/password and try again.")

        try:
            # 取 token / session（不同版本可能叫 cloud_credentials / token 等）
            token_payload = {}
            if hasattr(http, "cloud_credentials"):
                token_payload = {"cloud_credentials": getattr(http, "cloud_credentials")}
            elif hasattr(http, "token"):
                token_payload = {"token": getattr(http, "token")}
            else:
                token_payload = {"session": "unknown"}

            token_plain = json.dumps(token_payload, ensure_ascii=False)

            devices_raw = await http.async_list_devices()  # type: ignore

            devices = self._normalize_devices(devices_raw)

            account_id = self.repo.create_or_update_account_auth(email=email, token_plain=token_plain)
            self.repo.set_account_devices(account_id=account_id, devices=[d for d in devices])

            await http.async_logout()  # type: ignore

            return {
                "accountId": account_id,
                "status": "connected",
                "devices": devices,
            }
        finally:
            # 盡量釋放連線
            try:
                await http.async_close()  # type: ignore
            except Exception:
                pass

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        """
        用已保存 token/session 重新拉裝置列表
        第一階段：如果 token payload 無法直接重建 session，就會回報需要重新登入（之後可再補）
        """
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")

        # 目前 token_plain 只係保存一個 payload 快照。
        # 不同 meross-iot 版本對「用 token 重建 client」方式差異大。
        # 第一階段最穩方式係：先做到 connect 時立即拉 devices + 保存快照；
        # sync 如要做到完全無密碼重登，需要按你實際 meross-iot 版本補上正確做法。
        #
        # 所以第一階段：先回報「需要重新輸入密碼再 connect」或你選擇保存 email+password（不建議）。
        raise ValueError("Token-based sync is not enabled in MVP. Please reconnect with email/password to refresh devices.")

    def _normalize_devices(self, devices_raw: Any) -> List[Dict[str, Any]]:
        """
        將 meross-iot 返回的 devices 轉成前端需要的統一結構
        """
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
                            "capabilities": None,
                        }
                    )
                else:
                    # 若返回係 object，盡量用屬性名取值
                    device_id = getattr(d, "uuid", "") or getattr(d, "device_id", "") or ""
                    devices.append(
                        {
                            "deviceId": device_id,
                            "name": getattr(d, "name", None),
                            "model": getattr(d, "model", None),
                            "type": getattr(d, "type", None),
                            "onlineStatus": getattr(d, "online_status", None),
                            "capabilities": None,
                        }
                    )

        return devices