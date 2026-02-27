"""Public crypto market data service for real-time and historical chart requests."""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Dict, List, Optional
from urllib import error, parse, request


logger = logging.getLogger(__name__)


class MarketDataService:
    """Fetch market symbols and chart time-series from public API providers."""

    _TIMEFRAME_TO_DAYS = {
        "1D": 1,
        "7D": 7,
        "14D": 14,
        "30D": 30,
        "90D": 90,
        "180D": 180,
        "1Y": 365,
    }
    _TIMEFRAME_TO_CRYPTOCOMPARE = {
        "1D": ("v2/histohour", 24),
        "7D": ("v2/histohour", 24 * 7),
        "14D": ("v2/histohour", 24 * 14),
        "30D": ("v2/histoday", 30),
        "90D": ("v2/histoday", 90),
        "180D": ("v2/histoday", 180),
        "1Y": ("v2/histoday", 365),
        "MAX": ("v2/histoday", 2000),
    }

    def __init__(
        self,
        base_url: str,
        provider: str = "coincap",
        symbols_cache_ttl_sec: int = 1800,
        api_key: Optional[str] = None,
        api_key_header: str = "x-cg-demo-api-key",
    ) -> None:
        self._provider = provider.strip().lower()
        self._base_url = base_url.rstrip("/")
        self._symbols_cache_ttl_sec = symbols_cache_ttl_sec
        self._api_key = api_key.strip() if isinstance(api_key, str) else ""
        self._api_key_header = api_key_header
        self._symbols_cache: List[Dict[str, str]] = []
        self._symbols_cached_at: Optional[datetime] = None

    def _http_get_json(self, path: str, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send GET request and parse JSON payload."""
        url = "{0}{1}".format(self._base_url, path)
        if query:
            url = "{0}?{1}".format(url, parse.urlencode(query))
        req = request.Request(
            url=url,
            headers={
                "User-Agent": "PingMastersBackend/1.0 (+https://localhost)",
                "Accept": "application/json",
            },
        )
        if self._api_key:
            if self._provider == "cryptocompare" and self._api_key_header.lower() == "authorization":
                req.add_header("authorization", "Apikey {0}".format(self._api_key))
            else:
                req.add_header(self._api_key_header, self._api_key)
        try:
            with request.urlopen(req, timeout=15) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)
        except error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise RuntimeError(
                    "Market API unauthorized. Check market_api.api_key and market_api.api_key_header in config.yml."
                )
            if exc.code == 429:
                raise RuntimeError("Market API rate limit exceeded. Retry later.")
            raise RuntimeError("Market API request failed with status={0}".format(exc.code))
        except error.URLError as exc:
            raise RuntimeError("Market API network/DNS error: {0}".format(exc))

    def _is_symbols_cache_valid(self) -> bool:
        """Check whether symbol cache is still valid."""
        if self._symbols_cached_at is None:
            return False
        return datetime.now(timezone.utc) <= self._symbols_cached_at + timedelta(seconds=self._symbols_cache_ttl_sec)

    def list_all_symbols(self, refresh: bool = False) -> List[Dict[str, str]]:
        """Return all available coins/symbols from provider."""
        try:
            if not refresh and self._symbols_cache and self._is_symbols_cache_valid():
                return self._symbols_cache

            normalized: List[Dict[str, str]] = []
            if self._provider == "cryptocompare":
                records = self._http_get_json(path="/data/all/coinlist")
                data = records.get("Data", {})
                for symbol, item in data.items():
                    normalized.append(
                        {
                            "id": str(symbol).lower(),
                            "symbol": str(symbol).upper(),
                            "name": str(item.get("FullName") or item.get("CoinName") or symbol),
                        }
                    )
            elif self._provider == "coincap":
                records = self._http_get_json(path="/assets").get("data", [])
                for item in records:
                    normalized.append(
                        {
                            "id": str(item.get("id", "")),
                            "symbol": str(item.get("symbol", "")).upper(),
                            "name": str(item.get("name", "")),
                        }
                    )
            else:
                records = self._http_get_json(path="/coins/list", query={"include_platform": "false"})
                for item in records:
                    normalized.append(
                        {
                            "id": str(item.get("id", "")),
                            "symbol": str(item.get("symbol", "")).upper(),
                            "name": str(item.get("name", "")),
                        }
                    )
            self._symbols_cache = normalized
            self._symbols_cached_at = datetime.now(timezone.utc)
            return normalized
        except Exception:
            logger.exception("Failed to fetch symbol list from market API.")
            raise

    def resolve_coin_id(self, symbol_or_id: str) -> str:
        """Resolve user symbol/id to CoinGecko coin id."""
        try:
            query_value = symbol_or_id.strip()
            if not query_value:
                raise ValueError("symbol is required")
            lower_value = query_value.lower()

            symbols = self.list_all_symbols(refresh=False)
            exact_id_match = next((item for item in symbols if item["id"] == lower_value), None)
            if exact_id_match:
                return exact_id_match["id"]

            symbol_matches = [item for item in symbols if item["symbol"].lower() == lower_value]
            if len(symbol_matches) == 1:
                if self._provider == "cryptocompare":
                    return symbol_matches[0]["symbol"]
                return symbol_matches[0]["id"]

            if self._provider == "cryptocompare":
                raise ValueError("No matching coin found for symbol/id: {0}".format(symbol_or_id))

            if self._provider == "coincap":
                raise ValueError("No matching coin found for symbol/id: {0}".format(symbol_or_id))

            search = self._http_get_json(path="/search", query={"query": query_value})
            coins = search.get("coins", [])
            if not coins:
                raise ValueError("No matching coin found for symbol/id: {0}".format(symbol_or_id))

            exact_symbol = [item for item in coins if str(item.get("symbol", "")).lower() == lower_value]
            ranked = exact_symbol or coins
            ranked = sorted(ranked, key=lambda item: item.get("market_cap_rank") or 10**9)
            return str(ranked[0]["id"])
        except Exception:
            logger.exception("Failed resolving coin id for symbol_or_id=%s", symbol_or_id)
            raise

    def get_chart(self, symbol_or_id: str, timeframe: str, vs_currency: str = "usd") -> Dict[str, Any]:
        """Fetch chart data for user-selected symbol and timeframe."""
        try:
            coin_id = self.resolve_coin_id(symbol_or_id=symbol_or_id)
            normalized_timeframe = timeframe.strip().upper()
            if normalized_timeframe not in self._TIMEFRAME_TO_DAYS:
                raise ValueError(
                    "Unsupported timeframe. Use one of: {0}".format(", ".join(sorted(self._TIMEFRAME_TO_DAYS.keys())))
                )
            days = self._TIMEFRAME_TO_DAYS[normalized_timeframe]
            normalized_vs_currency = vs_currency.strip().lower()

            if self._provider == "cryptocompare":
                endpoint, limit = self._TIMEFRAME_TO_CRYPTOCOMPARE[normalized_timeframe]
                payload = self._http_get_json(
                    path="/data/{0}".format(endpoint),
                    query={
                        "fsym": coin_id.upper(),
                        "tsym": normalized_vs_currency.upper(),
                        "limit": limit,
                    },
                )
                if str(payload.get("Response", "")).lower() == "error":
                    raise ValueError(str(payload.get("Message", "Unable to fetch chart data.")))
                candles = payload.get("Data", {}).get("Data", [])
                prices = [[int(item.get("time", 0)) * 1000, float(item.get("close", 0.0))] for item in candles]
                total_volumes = [
                    [int(item.get("time", 0)) * 1000, float(item.get("volumeto", 0.0))]
                    for item in candles
                ]
                return {
                    "coin_id": coin_id.lower(),
                    "symbol_input": symbol_or_id,
                    "timeframe": normalized_timeframe,
                    "vs_currency": normalized_vs_currency,
                    "points": len(prices),
                    "prices": prices,
                    "market_caps": [],
                    "total_volumes": total_volumes,
                    "provider": self._base_url,
                }

            if self._provider == "coincap":
                end_time = int(datetime.now(timezone.utc).timestamp() * 1000)
                start_time = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
                interval = "h1" if days <= 14 else "d1"
                history = self._http_get_json(
                    path="/assets/{0}/history".format(coin_id),
                    query={"interval": interval, "start": start_time, "end": end_time},
                ).get("data", [])
                prices = [[int(item.get("time", 0)), float(item.get("priceUsd", 0.0))] for item in history]
                return {
                    "coin_id": coin_id,
                    "symbol_input": symbol_or_id,
                    "timeframe": normalized_timeframe,
                    "vs_currency": "usd",
                    "points": len(prices),
                    "prices": prices,
                    "market_caps": [],
                    "total_volumes": [],
                    "provider": self._base_url,
                    "note": "CoinCap provides USD-denominated history. vs_currency ignored unless usd.",
                }

            interval = "hourly" if days in {1, 7, 14} else "daily"
            payload = self._http_get_json(
                path="/coins/{0}/market_chart".format(coin_id),
                query={
                    "vs_currency": normalized_vs_currency,
                    "days": days,
                    "interval": interval,
                },
            )
            prices = payload.get("prices", [])
            market_caps = payload.get("market_caps", [])
            total_volumes = payload.get("total_volumes", [])
            return {
                "coin_id": coin_id,
                "symbol_input": symbol_or_id,
                "timeframe": normalized_timeframe,
                "vs_currency": normalized_vs_currency,
                "points": len(prices),
                "prices": prices,
                "market_caps": market_caps,
                "total_volumes": total_volumes,
                "provider": self._base_url,
            }
        except Exception:
            logger.exception(
                "Failed to fetch chart symbol_or_id=%s timeframe=%s vs_currency=%s",
                symbol_or_id,
                timeframe,
                vs_currency,
            )
            raise
