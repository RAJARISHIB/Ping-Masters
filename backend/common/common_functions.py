"""Common utility functions used across backend modules."""

from decimal import Decimal, InvalidOperation
import json
import logging
from typing import Any, Dict
from urllib import parse, request


logger = logging.getLogger(__name__)


def _http_get_json(url: str, timeout_sec: int) -> Dict[str, Any]:
    """Perform an HTTP GET and parse JSON with request headers."""
    req = request.Request(
        url=url,
        headers={
            "User-Agent": "PingMastersBackend/1.0 (+https://localhost)",
            "Accept": "application/json",
        },
    )
    with request.urlopen(req, timeout=timeout_sec) as response:
        return json.loads(response.read().decode("utf-8"))


def convert_currency_amount(
    amount: float,
    from_currency: str,
    to_currency: str,
    api_base_url: str,
    timeout_sec: int = 10,
) -> Dict[str, Any]:
    """Convert amount between two currencies via a public exchange-rate API.

    Args:
        amount: Amount to convert.
        from_currency: Source currency code (for example, USD).
        to_currency: Target currency code (for example, INR).
        api_base_url: Public API base URL (for example, https://api.frankfurter.app).
        timeout_sec: Request timeout in seconds.

    Returns:
        Dict[str, Any]: Conversion payload with converted amount and metadata.

    Raises:
        ValueError: If input parameters are invalid.
        RuntimeError: If API request or response parsing fails.
    """
    try:
        normalized_from = (from_currency or "").strip().upper()
        normalized_to = (to_currency or "").strip().upper()
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        logger.exception("Invalid amount input for currency conversion amount=%s", amount)
        raise ValueError("Invalid amount. Please provide a numeric value.")

    if decimal_amount <= 0:
        raise ValueError("Amount must be greater than 0.")
    if len(normalized_from) != 3 or len(normalized_to) != 3:
        raise ValueError("Currency codes must be 3-letter ISO codes.")

    providers = [
        ("frankfurter", api_base_url.rstrip("/")),
        ("open-er-api", "https://open.er-api.com/v6"),
    ]

    last_error: Exception = RuntimeError("Currency conversion failed.")
    for provider_name, provider_base_url in providers:
        try:
            if provider_name == "frankfurter":
                query = parse.urlencode(
                    {
                        "amount": str(decimal_amount),
                        "from": normalized_from,
                        "to": normalized_to,
                    }
                )
                url = "{0}/latest?{1}".format(provider_base_url, query)
                payload = _http_get_json(url=url, timeout_sec=timeout_sec)
                rates = payload.get("rates", {})
                converted_value = rates[normalized_to]
                rate = float(Decimal(str(converted_value)) / decimal_amount)
                return {
                    "amount": float(decimal_amount),
                    "from_currency": normalized_from,
                    "to_currency": normalized_to,
                    "converted_amount": float(converted_value),
                    "rate": rate,
                    "provider": provider_base_url,
                    "raw": payload,
                }

            url = "{0}/latest/{1}".format(provider_base_url, normalized_from)
            payload = _http_get_json(url=url, timeout_sec=timeout_sec)
            rates = payload.get("rates", {})
            unit_rate = Decimal(str(rates[normalized_to]))
            converted_value = float(decimal_amount * unit_rate)
            return {
                "amount": float(decimal_amount),
                "from_currency": normalized_from,
                "to_currency": normalized_to,
                "converted_amount": converted_value,
                "rate": float(unit_rate),
                "provider": provider_base_url,
                "raw": payload,
            }
        except Exception as exc:
            last_error = exc
            logger.warning("Currency provider failed provider=%s error=%s", provider_name, exc)

    logger.exception("All currency providers failed.")
    raise RuntimeError("Currency conversion API request failed: {0}".format(last_error))
