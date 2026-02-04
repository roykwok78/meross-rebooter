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
        http: Optional[Any] = None

        # 多 endpoint + 一次 auto（唔指定 api_base_url）
        api_candidates = [
            "AUTO",  # 先讓 library 自己決定
            "https://iotx.meross.com",
            "https://iot.meross.com",
            "https://iotx-ap.meross.com",
            "https://iotx-eu.meross.com",
        ]

        last_err: Optional[Exception] = None

        try:
            for api_base_url in api_candidates:
                try:
                    http = await self._login(api_base_url, email, password)
                    if http is not None:
                        logger.info("Meross login success using api_base_url=%s", api_base_url)
                        break
                except KeyError as e:
                    # 關鍵：KeyError 代表 library parse 回應格式唔符合預期
                    last_err = e
                    logger.warning(
                        "Meross login failed using api_base_url=%s err=KeyError missing_key=%s",
                        api_base_url,
                        str(e),
                    )
                    http = None
                except Exception as e:
                    last_err = e
                    logger.warning(
                        "Meross login failed using api_base_url=%s err=%s",
                        api_base_url,
                        type(e).__name__,
                    )
                    http = None

            if http is None:
                # 給更有用的錯誤訊息（但仍不洩漏敏感）
                raise ValueError(
                    "Meross login failed (library parse error). "
                    "This often happens when Meross cloud response format differs by region/account. "
                    "If you use Apple/Google sign-in, please set/reset a Meross password in the Meross app. "
                    "If still failing, we will enable a debug-safe log of response shape."
                )

            token_payload: Dict[str, Any]
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
            if http is not None:
                try:
                    await http.async_close()  # type: ignore
                except Exception:
                    pass

    async def _login(self, api_base_url: str, email: str, password: str) -> Any:
        """
        嘗試登入。AUTO 代表唔指定 api_base_url，交俾 library 自己揀。
        """
        if api_base_url == "AUTO":
            # 有啲版本 signature 只接受 email/password
            return await self._login_signature_fallback(None, email, password)
        return await self._login_signature_fallback(api_base_url, email, password)

    async def _login_signature_fallback(self, api_base_url: Optional[str], email: str, password: str) -> Any:
        """
        兼容 meross-iot 0.4.7 可能出現的 signature 差異
        """
        # 1) named args
        if api_base_url:
            try:
                return await MerossHttpClient.async_from_user_password(
                    api_base_url=api_base_url,
                    email=email,
                    password=password,
                )  # type: ignore
            except TypeError:
                pass

        # 2) 不帶 api_base_url
        try:
            return await MerossHttpClient.async_from_user_password(
                email=email,
                password=password,
            )  # type: ignore
        except TypeError:
            pass

        # 3) positional (api_base_url, email, password)
        if api_base_url:
            try:
                return await MerossHttpClient.async_from_user_password(
                    api_base_url,
                    email,
                    password,
                )  # type: ignore
            except TypeError:
                pass

        # 4) positional (email, password, api_base_url)
        if api_base_url:
            return await MerossHttpClient.async_from_user_password(
                email,
                password,
                api_base_url,
            )  # type: ignore

        # 最後 fallback：只有 email/password
        return await MerossHttpClient.async_from_user_password(
            email,
            password,
        )  # type: ignore

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")
        raise ValueError("Token-based sync is not enabled in MVP. Please reconnect to refresh devices.")

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
        return devices