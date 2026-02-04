    def _extract_token_payload(self, http: Any) -> Dict[str, Any]:
        """
        Extract Meross auth data using a strict whitelist so the result is always JSON-serializable.
        This MUST NOT attempt to serialize MerossCloudCreds directly.
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