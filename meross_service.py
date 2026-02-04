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

        api_candidates = [
            "AUTO",
            "https://iotx.meross.com",
            "https://iot.meross.com",
            "https://iotx-us.meross.com",
            "https://iotx-eu.meross.com",
            "https://iotx-ap.meross.com",
        ]

        try:
            for api_base_url in api_candidates:
                try:
                    http = await self._login(api_base_url, email, password)
                    if http is not None:
                        logger.info("Meross login success using api_base_url=%s", api_base_url)
                        break
                except Exception as e:
                    logger.warning(
                        "Meross login failed using api_base_url=%s err=%s",
                        api_base_url,
                        type(e).__name__,
                    )
                    http = None

            if http is None:
                raise ValueError(
                    "Meross login failed. If you use Apple/Google sign-in, please set/reset a Meross password in the Meross app and try again."
                )

            token_payload = self._extract_token_payload(http)
            token_plain = json.dumps(token_payload, ensure_ascii=False)

            devices_raw = await http.async_list_devices()  # type: ignore
            devices = self._normalize_devices(devices_raw)

            account_id = self.repo.create_or_update_account_auth(
                email=email,
                token_plain=token_plain,
            )
            self.repo.set_account_devices(account_id=account_id, devices=devices)

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

    def _extract_token_payload(self, http: Any) -> Dict[str, Any]:
        """
        Extract Meross auth data using a strict whitelist so the result is always JSON-serializable.
        """
        if hasattr(http, "cloud_credentials") and http.cloud_credentials:
            return self._extract_cloud_creds_whitelist(http.cloud_credentials)

        if hasattr(http, "token") and http.token:
            return {"token": str(http.token)}

        return {"session": "unknown"}

    def _extract_cloud_creds_whitelist(self, creds: Any) -> Dict[str, Any]:
        data: Dict[str, Any] = {}

        for key in [
            "token",
            "key",
            "userid",
            "email",
            "domain",
            "mqttDomain",
            "mqttPort",
            "region",
        ]:
            if hasattr(creds, key):
                value = getattr(creds, key)
                if value is not None:
                    data[key] = value

        if hasattr(creds, "cloudToken") and creds.cloudToken:
            data["cloudToken"] = creds.cloudToken

        return data

    async def _login(self, api_base_url: str, email: str, password: str) -> Any:
        if api_base_url == "AUTO":
            return await self._login_signature_fallback(None, email, password)
        return await self._login_signature_fallback(api_base_url, email, password)

    async def _login_signature_fallback(
        self,
        api_base_url: Optional[str],
        email: str,
        password: str,
    ) -> Any:
        if api_base_url:
            try:
                return await MerossHttpClient.async_from_user_password(
                    api_base_url=api_base_url,
                    email=email,
                    password=password,
                )
            except TypeError:
                pass

        return await MerossHttpClient.async_from_user_password(
            email=email,
            password=password,
        )

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")
        raise ValueError("Token-based sync is not enabled in MVP.")

    def _normalize_devices(self, devices_raw: Any) -> List[Dict[str, Any]]:
        devices: List[Dict[str, Any]] = []

        if isinstance(devices_raw, list):
            for d in devices_raw:
                if isinstance(d, dict):
                    devices.append(
                        {
                            "deviceId": d.get("uuid") or d.get("deviceId") or "",
                            "name": d.get("devName") or d.get("name"),
                            "model": d.get("deviceType") or d.get("model"),
                            "type": d.get("deviceType") or d.get("type"),
                            "onlineStatus": d.get("onlineStatus"),
                            "capabilities": d.get("abilities") or d.get("capabilities"),
                        }
                    )

        return devices