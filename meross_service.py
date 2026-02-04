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

        # 明確列出 endpoint，避免 AUTO 造成 TypeError 噪音
        api_candidates = [
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
                    "Meross login failed. "
                    "If you use Apple/Google sign-in, please set/reset a Meross password in the Meross app and try again."
                )

            # ✅ 嚴格白名單 token payload（必定 JSON-safe）
            token_payload = self._extract_token_payload(http)
            token_plain = json.dumps(token_payload, ensure_ascii=False)

            devices_raw = await http.async_list_devices()  # type: ignore
            devices = self._normalize_devices(devices_raw)

            account_id = self.repo.create_or_update_account_auth(
                email=email,
                token_plain=token_plain,
            )
            self.repo.set_account_devices(
                account_id=account_id,
                devices=[d for d in devices],
            )

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

    # ------------------------------------------------------------------
    # Token extraction (STRICT whitelist)
    # ------------------------------------------------------------------

    def _extract_token_payload(self, http: Any) -> Dict[str, Any]:
        """
        Extract Meross auth data using a strict whitelist so the result
        is always JSON-serializable.

        ⚠️ MUST NOT serialize MerossCloudCreds / __dict__ directly.
        """
        # Newer meross-iot versions
        if hasattr(http, "cloud_credentials") and http.cloud_credentials:
            return self._extract_cloud_creds_whitelist(http.cloud_credentials)

        # Older fallback
        if hasattr(http, "token") and http.token:
            return {
                "token": str(http.token)
            }

        return {
            "session": "unknown"
        }

    def _extract_cloud_creds_whitelist(self, creds: Any) -> Dict[str, Any]:
        """
        Whitelist-only extraction from MerossCloudCreds.
        Ensures the payload is always JSON-serializable.
        """
        data: Dict[str, Any] = {}

        # 兼容唔同 meross-iot 版本命名
        key_map = [
            ("token", "token"),
            ("key", "key"),
            ("userid", "userid"),
            ("userId", "userid"),
            ("email", "email"),
            ("domain", "domain"),
            ("region", "region"),
            ("mqttDomain", "mqttDomain"),
            ("mqtt_domain", "mqttDomain"),
            ("mqttPort", "mqttPort"),
            ("mqtt_port", "mqttPort"),
        ]

        for src, dst in key_map:
            if hasattr(creds, src):
                value = getattr(creds, src)
                if value is not None:
                    data[dst] = value

        # 有啲版本會額外有 cloudToken
        if hasattr(creds, "cloudToken") and getattr(creds, "cloudToken"):
            data["cloudToken"] = getattr(creds, "cloudToken")

        return data

    # ------------------------------------------------------------------
    # Login helpers
    # ------------------------------------------------------------------

    async def _login(self, api_base_url: str, email: str, password: str) -> Any:
        """
        Try multiple signatures for compatibility with different
        meross-iot versions.
        """
        # Preferred signature
        try:
            return await MerossHttpClient.async_from_user_password(
                api_base_url=api_base_url,
                email=email,
                password=password,
            )  # type: ignore
        except TypeError:
            pass

        # Older signatures
        try:
            return await MerossHttpClient.async_from_user_password(
                email=email,
                password=password,
            )  # type: ignore
        except TypeError:
            pass

        try:
            return await MerossHttpClient.async_from_user_password(
                api_base_url,
                email,
                password,
            )  # type: ignore
        except TypeError:
            pass

        return await MerossHttpClient.async_from_user_password(
            email,
            password,
            api_base_url,
        )  # type: ignore

    # ------------------------------------------------------------------
    # Device helpers
    # ------------------------------------------------------------------

    async def sync_devices(self, account_id: str) -> Dict[str, Any]:
        token_plain = self.repo.get_account_token(account_id=account_id)
        if token_plain is None:
            raise KeyError("account not found")

        raise ValueError(
            "Token-based sync is not enabled in MVP. "
            "Please reconnect the account to refresh devices."
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
                            "onlineStatus": (
                                d.get("onlineStatus")
                                if isinstance(d.get("onlineStatus"), bool)
                                else None
                            ),
                            "capabilities": d.get("abilities") or d.get("capabilities"),
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
                            "capabilities": getattr(d, "abilities", None)
                            or getattr(d, "capabilities", None),
                        }
                    )

        return devices