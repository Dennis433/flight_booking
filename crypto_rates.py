"""
Live crypto prices in USD, fetched from CoinGecko's public API.

- Results are cached for CACHE_SECONDS so every page view doesn't hit the API.
- If the API is unreachable, the last good prices are used for up to
  MAX_STALE_SECONDS. After that, RateUnavailable is raised and payments are
  refused rather than charged at an outdated price.
- There are no hardcoded prices. The amount owed is always calculated on the
  server at the moment the payment is submitted.

Optional: set COINGECKO_API_KEY in .env for higher rate limits (demo or pro key).
"""
import os
import threading
import time
from datetime import datetime, timezone

import httpx

COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price'
COIN_IDS = {
    'BTC':  'bitcoin',
    'ETH':  'ethereum',
    'SOL':  'solana',
    'USDT': 'tether',
    'USDC': 'usd-coin',
}
CACHE_SECONDS     = 60      # how long a successful fetch is reused
MAX_STALE_SECONDS = 600     # oldest prices we will still accept during an outage

_lock  = threading.Lock()
_state = {'prices': None, 'fetched_at': 0.0}


class RateUnavailable(Exception):
    """Raised when no sufficiently recent live price can be obtained."""


def _fetch_live():
    headers = {}
    api_key = os.getenv('COINGECKO_API_KEY', '').strip()
    if api_key:
        headers['x-cg-demo-api-key'] = api_key

    resp = httpx.get(
        COINGECKO_URL,
        params={'ids': ','.join(COIN_IDS.values()), 'vs_currencies': 'usd'},
        headers=headers,
        timeout=5.0,
    )
    resp.raise_for_status()
    data = resp.json()

    prices = {}
    for symbol, coin_id in COIN_IDS.items():
        price = (data.get(coin_id) or {}).get('usd')
        if not price or price <= 0:
            raise ValueError(f'No USD price returned for {symbol}')
        prices[symbol] = float(price)
    return prices


def get_usd_prices():
    """
    Returns a dict:
      {
        'prices':  {'BTC': 64000.0, 'ETH': ..., 'SOL': ..., 'USDT': ..., 'USDC': ...},
        'as_of':   '2026-11-16T09:30:00+00:00',   # when these prices were fetched
        'source':  'live' | 'cached' | 'last-known',
      }
    Raises RateUnavailable if no acceptable price can be obtained.
    """
    with _lock:
        now = time.time()

        # Fresh enough: reuse the cache
        if _state['prices'] and now - _state['fetched_at'] < CACHE_SECONDS:
            return _snapshot('cached')

        # Try to fetch new prices
        try:
            _state['prices']     = _fetch_live()
            _state['fetched_at'] = now
            return _snapshot('live')
        except Exception as exc:
            print(f'[crypto_rates] live fetch failed: {exc}')

        # Outage: fall back to the last good prices, but only if they're recent
        if _state['prices'] and now - _state['fetched_at'] < MAX_STALE_SECONDS:
            return _snapshot('last-known')

        raise RateUnavailable('Live crypto prices are unavailable right now.')


def _snapshot(source):
    return {
        'prices': dict(_state['prices']),
        'as_of':  datetime.fromtimestamp(_state['fetched_at'], tz=timezone.utc).isoformat(),
        'source': source,
    }


def crypto_amount(total_usd, crypto, prices):
    """Convert a USD total into the crypto amount, rounded to a sensible precision."""
    decimals = 2 if crypto in ('USDT', 'USDC') else 6
    return round(total_usd / prices[crypto], decimals)
