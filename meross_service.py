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

# 先唔好用 AUTO 做第一個（AUTO 其實就等同唔指定 base_url）
api_candidates = [
None,  # AUTO / default
"https://iotx.meross.com",
"https://iot.meross.com",
"https://iotx-us.meross.com",
"https://iotx-eu.meross.com",
"https://iotx-ap.meross.com",
]

try:
for api_base_url in api_candidates:
label = "AUTO" if api_base_url is None else api_base_url
try:
http = await self._login(api_base_url, email, password)
if http is not None:
logger.info("Meross login success using api_base_url=%s", label)
break
except KeyError as e:
logger.warning(
"Meross login failed using api_base_url=%s err=KeyError missing_key=%s",
label,
str(e),
)
http = None
except TypeError as e:
# 最關鍵：顯示 TypeError 內容（唔含任何秘密）
logger.warning(
"Meross login failed using api_base_url=%s err=TypeError msg=%s",
label,
str(e),
)
http = None
except Exception as e:
logger.warning(
"Meross login failed using api_base_url=%s err=%s",
label,
type(e).__name__,
)
http = None

if http is None:
raise ValueError(
"Meross login failed. If you use Apple/Google sign-in, please set/reset a Meross password in the Meross app and try again."
)

# ✅ 用 whitelist / JSON-safe token payload
token_payload = self._extract_token_payload(http)
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

def _extract_token_payload(self, http: Any) -> Dict[str, Any]:
"""
Extract Meross auth data using a strict whitelist so the result is always JSON-serializable.
This MUST NOT attempt to serialize MerossCloudCreds directly.
"""
# Newer meross-iot versions
if hasattr(http, "cloud_credentials") and getattr(http, "cloud_credentials"):
return self._extract_cloud_creds_whitelist(getattr(http, "cloud_credentials"))

# Older fallback
if hasattr(http, "token") and getattr(http, "token"):
return {"token": str(getattr(http, "token"))}

return {"session": "unknown"}

def _extract_cloud_creds_whitelist(self, creds: Any) -> Dict[str, Any]:
"""
Whitelist-only extraction from MerossCloudCreds.
Ensures the payload is always JSON-serializable.
"""
data: Dict[str, Any] = {}

# 注意：meross-iot 唔同版本 field 名有少少唔同，所以用多幾個 alias
key_candidates = [
"token",
"key",
"userid",
"userId",
"email",
"domain",
"mqttDomain",
"mqtt_domain",
"mqttPort",
"mqtt_port",
"region",
"issued_at",
"expires_in",
]

for k in key_candidates:
if hasattr(creds, k):
v = getattr(creds, k)
if v is None:
continue
# bytes -> str（避免 json dumps 爆）
if isinstance(v, (bytes, bytearray)):
v = v.decode("utf-8", errors="ignore")
data[k] = v

if hasattr(creds, "cloudToken") and getattr(creds, "cloudToken"):
data["cloudToken"] = getattr(creds, "cloudToken")

return data

async def _login(self, api_base_url: Optional[str], email: str, password: str) -> Any:
"""
meross-iot 0.4.10.x 經常唔食 keyword args，所以優先用 positional。
"""
# 1) AUTO / default：只傳 email, password（positional）
if not api_base_url:
return await self._login_positional(email, password, None)

# 2) 指定 api_base_url：先試 (email, password, api_base_url) positional
return await self._login_positional(email, password, api_base_url)

async def _login_positional(self, email: str, password: str, api_base_url: Optional[str]) -> Any:
# A) positional with base_url
if api_base_url:
try:
return await MerossHttpClient.async_from_user_password(email, password, api_base_url)  # type: ignore
except TypeError:
pass

# B) positional without base_url
try:
return await MerossHttpClient.async_from_user_password(email, password)  # type: ignore
except TypeError:
pass

# C) keyword fallback（最後先試）
if api_base_url:
try:
return await MerossHttpClient.async_from_user_password(
email=email,
password=password,
api_base_url=api_base_url,
)  # type: ignore
except TypeError:
pass

return await MerossHttpClient.async_from_user_password(
email=email,
password=password,
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