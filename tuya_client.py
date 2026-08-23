"""
Minimal, dependency-light Tuya Cloud API client.

Implements Tuya's documented request-signing algorithm directly
(HMAC-SHA256 over method + content hash + headers + path) so this
project has no dependency on any third-party Tuya SDK package.

Reference: Tuya Cloud "Calculate the Signature" developer docs.
"""

import hashlib
import hmac
import time
import json
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger("tuya_client")


class TuyaAPIError(Exception):
    """Raised when the Tuya Cloud API returns success=false or a transport error occurs."""
    pass


class TuyaClient:
    def __init__(self, access_id: str, access_secret: str, api_endpoint: str,
                 timeout_seconds: int = 10):
        self.access_id = access_id
        self.access_secret = access_secret
        self.api_endpoint = api_endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    # ---------------------------------------------------------
    # Signing
    # ---------------------------------------------------------
    def _sha256_hex(self, body: str) -> str:
        return hashlib.sha256(body.encode("utf-8")).hexdigest()

    def _sign(self, message: str) -> str:
        signature = hmac.new(
            self.access_secret.encode("utf-8"),
            msg=message.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest().upper()
        return signature

    def _build_string_to_sign(self, method: str, path: str, body: str) -> str:
        content_sha256 = self._sha256_hex(body or "")
        headers_str = ""  # no signed headers used in this simple client
        return f"{method}\n{content_sha256}\n{headers_str}\n{path}"

    # ---------------------------------------------------------
    # Token management
    # ---------------------------------------------------------
    def _get_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at - 30:
            return self._token

        t = str(int(now * 1000))
        path = "/v1.0/token?grant_type=1"
        string_to_sign = self._build_string_to_sign("GET", path, "")
        message = self.access_id + t + string_to_sign
        sign = self._sign(message)

        headers = {
            "client_id": self.access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
            "mode": "cors",
        }

        resp = self._request_raw("GET", path, headers=headers)
        if not resp.get("success"):
            raise TuyaAPIError(f"Failed to obtain access token: {resp}")

        result = resp["result"]
        self._token = result["access_token"]
        self._token_expires_at = now + result.get("expire_time", 7200)
        return self._token

    # ---------------------------------------------------------
    # Low-level request
    # ---------------------------------------------------------
    def _request_raw(self, method: str, path: str, headers: dict,
                      body: Optional[dict] = None) -> dict:
        url = self.api_endpoint + path
        body_str = json.dumps(body) if body is not None else ""
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            elif method == "POST":
                r = requests.post(url, headers=headers, data=body_str,
                                   timeout=self.timeout_seconds)
            else:
                raise TuyaAPIError(f"Unsupported HTTP method: {method}")
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            raise TuyaAPIError(f"Network/transport error calling {path}: {e}") from e
        except ValueError as e:
            raise TuyaAPIError(f"Invalid JSON response from {path}: {e}") from e

    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        """Authenticated request (business API calls, after token obtained)."""
        token = self._get_token()
        t = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body is not None else ""
        string_to_sign = self._build_string_to_sign(method, path, body_str)
        message = self.access_id + token + t + string_to_sign
        sign = self._sign(message)

        headers = {
            "client_id": self.access_id,
            "access_token": token,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
            "mode": "cors",
            "Content-Type": "application/json",
        }

        resp = self._request_raw(method, path, headers=headers, body=body)
        if not resp.get("success"):
            raise TuyaAPIError(f"Tuya API call failed for {path}: {resp}")
        return resp

    # ---------------------------------------------------------
    # Public device methods
    # ---------------------------------------------------------
    def test_connection(self) -> bool:
        """Attempts to obtain a token. Raises TuyaAPIError on failure."""
        self._token = None  # force fresh attempt
        self._get_token()
        return True

    def get_device_status(self, device_id: str) -> list[dict[str, Any]]:
        resp = self._request("GET", f"/v1.0/iot-03/devices/{device_id}/status")
        return resp["result"]

    def get_device_info(self, device_id: str) -> dict[str, Any]:
        resp = self._request("GET", f"/v1.0/iot-03/devices/{device_id}")
        return resp["result"]

    def send_commands(self, device_id: str, commands: list[dict[str, Any]]) -> bool:
        resp = self._request(
            "POST",
            f"/v1.0/iot-03/devices/{device_id}/commands",
            body={"commands": commands},
        )
        return bool(resp.get("result", False))
