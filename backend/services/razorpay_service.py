"""Razorpay client service for test-mode checkout, mandate simulation, and refunds."""

import base64
import json
import logging
from typing import Any, Dict, Optional
from urllib import error, request


logger = logging.getLogger(__name__)


class RazorpayService:
    """Minimal Razorpay REST client with production-style error handling."""

    def __init__(
        self,
        enabled: bool,
        key_id: Optional[str],
        key_secret: Optional[str],
        api_base_url: str,
        timeout_sec: int = 15,
    ) -> None:
        """Initialize Razorpay integration settings."""
        self._enabled = bool(enabled)
        self._key_id = (key_id or "").strip()
        self._key_secret = (key_secret or "").strip()
        self._api_base_url = api_base_url.rstrip("/")
        self._timeout_sec = max(1, int(timeout_sec))

    @property
    def is_enabled(self) -> bool:
        """Return whether Razorpay integration is enabled in config."""
        return self._enabled

    @property
    def is_configured(self) -> bool:
        """Return whether required API credentials are available."""
        return self._enabled and bool(self._key_id and self._key_secret)

    @property
    def is_test_mode(self) -> bool:
        """Return whether configured credentials are explicitly test-mode."""
        return self.key_mode == "test"

    @property
    def key_mode(self) -> str:
        """Return credential mode based on key prefix."""
        if self._key_id.startswith("rzp_test_"):
            return "test"
        if self._key_id.startswith("rzp_live_"):
            return "live"
        return "unknown"

    @property
    def key_id_masked(self) -> str:
        """Return masked key id for safe diagnostics."""
        if not self._key_id:
            return ""
        if len(self._key_id) <= 8:
            return self._key_id[:2] + "***"
        return "{0}***{1}".format(self._key_id[:8], self._key_id[-4:])

    @property
    def api_base_url(self) -> str:
        """Return configured Razorpay base URL."""
        return self._api_base_url

    @property
    def public_key_id(self) -> str:
        """Return Razorpay public key id for checkout usage."""
        return self._key_id

    def _auth_header(self) -> str:
        """Build HTTP basic auth header value."""
        token = "{0}:{1}".format(self._key_id, self._key_secret).encode("utf-8")
        return "Basic {0}".format(base64.b64encode(token).decode("utf-8"))

    def _request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute authenticated Razorpay JSON request."""
        if not self.is_configured:
            raise RuntimeError("Razorpay is not configured. Check razorpay.enabled/key_id/key_secret.")
        if not self.is_test_mode:
            raise RuntimeError(
                "Razorpay test mode is enforced. Configure an rzp_test_* key_id (current mode={0}).".format(
                    self.key_mode
                )
            )

        url = "{0}{1}".format(self._api_base_url, path)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        req = request.Request(
            url=url,
            data=data,
            method=method.upper(),
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "PingMastersBackend/1.0",
            },
        )
        try:
            with request.urlopen(req, timeout=self._timeout_sec) as response:
                body = response.read().decode("utf-8")
                if not body:
                    return {}
                return json.loads(body)
        except error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                body = ""
            logger.exception("Razorpay request failed method=%s path=%s status=%s", method, path, exc.code)
            raise RuntimeError("Razorpay API error status={0} body={1}".format(exc.code, body))
        except error.URLError as exc:
            logger.exception("Razorpay network error method=%s path=%s", method, path)
            raise RuntimeError("Razorpay network error: {0}".format(exc))

    def create_order(
        self,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create Razorpay order for merchant settlement flow."""
        if amount_minor <= 0:
            raise ValueError("amount_minor must be > 0")
        payload = {
            "amount": int(amount_minor),
            "currency": currency.upper(),
            "receipt": receipt,
            "payment_capture": 1,
            "notes": notes or {},
        }
        return self._request_json("POST", "/v1/orders", payload)

    def create_payment_link(
        self,
        amount_minor: int,
        currency: str,
        description: str,
        customer: Optional[Dict[str, str]] = None,
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create Razorpay payment link for autopay/mandate simulation."""
        if amount_minor <= 0:
            raise ValueError("amount_minor must be > 0")
        customer_payload: Dict[str, str] = {}
        if customer:
            for key in ("name", "email", "contact"):
                value = str(customer.get(key, "")).strip()
                if value:
                    customer_payload[key] = value
        notify_email = bool(customer_payload.get("email"))
        notify_sms = bool(customer_payload.get("contact"))
        payload: Dict[str, Any] = {
            "amount": int(amount_minor),
            "currency": currency.upper(),
            "description": description,
            "notify": {"sms": notify_sms, "email": notify_email},
            "notes": notes or {},
            "reminder_enable": True,
            "accept_partial": False,
        }
        if customer_payload:
            payload["customer"] = customer_payload
        return self._request_json("POST", "/v1/payment_links", payload)

    def create_refund(
        self,
        payment_id: str,
        amount_minor: Optional[int] = None,
        notes: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create refund against an existing Razorpay payment."""
        normalized_payment_id = (payment_id or "").strip()
        if not normalized_payment_id:
            raise ValueError("payment_id is required")
        payload: Dict[str, Any] = {"notes": notes or {}}
        if amount_minor is not None:
            if int(amount_minor) <= 0:
                raise ValueError("amount_minor must be > 0 when provided")
            payload["amount"] = int(amount_minor)
        path = "/v1/payments/{0}/refund".format(normalized_payment_id)
        return self._request_json("POST", path, payload)

    def verify_credentials(self) -> Dict[str, Any]:
        """Verify current credentials by calling a read-only Razorpay endpoint."""
        result = self._request_json("GET", "/v1/orders?count=1")
        items = result.get("items", []) if isinstance(result, dict) else []
        return {
            "ok": True,
            "mode": self.key_mode,
            "test_mode_enforced": True,
            "key_id_masked": self.key_id_masked,
            "api_base_url": self.api_base_url,
            "sample_orders_count": len(items) if isinstance(items, list) else 0,
        }
