import json
import logging
from typing import Any, Dict, List, Optional

from firestore_repo import FirestoreRepo

from meross_iot.http_api import MerossHttpClient  # type: ignore

logger = logging.getLogger("meross_service")
logger.setLevel(logging.INFO)


class MerossService:
    def __init__(self, repo: FirestoreRepo):
        self.repo = repo

    async def connect_account(self, email: str, password: str) -> Dict[str, Any]:
        """
        1) 用 Meross 雲端登入（多 endpoint / 多 signature fallback）
        2) 拉取裝置列表
        3) 保存 token + devices
        """
        http: Optional[Any] = None

        # Meross 可能有 iot / iotx 兩個雲端入口；不同帳戶/區域會有差異
        api_candidates = [
            "https://iotx.meross.com",
            "https://iot.meross.com",
        ]

        # 逐個 endpoint 嘗試登入
        last_err: Optional[Exception] = None

        try:
            for api_base_url in api_candidates:
                try:
                    http = await self._login_with_fallback(api_base_url, email, password)
                    if http is not None:
                        logger.info("Meross login success using api_base_url=%s", api_base_url)
                        break
                except Exception as e:
                    # 唔 log 敏感資料；只記錄 exception 類型
                    last_err = e
                    logger.warning(
                        "Meross login failed using api_base_url=%s err=%s",
                        api_base_url,
                        type(e).__name__,
                    )
                    http = None

            if http is None:
                # 登入仍失敗 → 回 401
                raise ValueError(
                    "Meross login failed. If you use Apple/Google sign-in, please set/reset a Meross password in the Meross app and try again."
                )

            # 取 token / session（不同版本可能叫 cloud_credentials / token 等）
            token_payload: Dict[str, Any]
            if hasattr(http, "cloud_credentials"):
                token_payload = {"cloud_credentials": getattr(http, "cloud_credentials")}
            elif hasattr(http, "token"):
                token_payload = {"token": getattr(http, "token")}
            else:
                token_payload = {"session": "unknown"}

            token_plain = json.dumps(token_payload, ensure_ascii=False)

            # 拉裝置
            devices_raw = await http.async_list_devices()  # type: ignore
            devices = self._normalize_devices(devices_raw)

            # 目前你 firestore_repo 係每次 create 新 accountId（MVP OK）
            # 如你想同 email 固定同一 accountId，我之後再幫你改成 upsert
            account_id = self.repo.create_or_update_account_auth(email=email, token_plain=token_plain)
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

    async def _login_with_fallback(self, api_base_url: str, email: str, password: str) -> Any:
        """
        meross-iot 0.4.7 及不同小版本，async_from_user_password signature 可能不同。
        呢度做幾個常見 fallback，盡量提升成功率。
        """
        # 1) named args（你原本寫法）
        try:
            return await MerossHttpClient.async_from_user_password(
                api_base_url=api_base_url,
                email=email,
                password=password,
            )  # type: ignore
        except TypeError:
            pass

        # 2) 無 api_base_url（由 library 自己決定）
        try:
            return await MerossHttpClient.async_from_user_password(
                email=email,
                password=password,
            )  # type: ignore
        except TypeError:
            pass

        # 3) positional： (api_base_url, email, password)
        try:
            return await MerossHttpClient.async_from_user_password(
                api_base_url,
                email,
                password,
            )  # type: ignore
        except TypeError:
            pass

        # 4) positional： (email, password, api_base_url)
        # 有啲版本係第三個參數先係 base url
        return await MerossHttpClient.async_from_user_password(
            email,
            password,
            api_base_url,
        )  # type: ignore

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")
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