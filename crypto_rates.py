"""
Live crypto prices in USD.

Sources, tried in order:
  1. CoinGecko (public API, optional COINGECKO_API_KEY for higher limits)
  2. Coinbase spot prices (public, no key needed)

Behaviour:
- Successful results are cached for CACHE_SECONDS.
- After a failed attempt, no new attempt is made for RETRY_BACKOFF_SECONDS,
  so a rate-limited source isn't hammered on every page view.
- If every source fails, the last good prices are used for up to
  MAX_STALE_SECONDS. After that RateUnavailable is raised and payment is refused.
- Nothing is hardcoded. The amount is always calculated on the server at submit.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone

import httpx

log = logging.getLogger('crypto_rates')

SYMBOLS = ['BTC', 'ETH', 'SOL', 'USDT', 'USDC']
COINGECKO_IDS = {
    'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana',
    'USDT': 'tether', 'USDC': 'usd-coin',
}
COINGECKO_URL = 'https://api.coingecko.com/api/v3/simple/price'
COINBASE_URL  = 'https://api.coinbase.com/v2/prices/{sym}-USD/spot'

CACHE_SECONDS         = 60
RETRY_BACKOFF_SECONDS = 20
MAX_STALE_SECONDS     = 600
TIMEOUT               = 5.0

_lock  = threading.Lock()
_state = {'prices': None, 'fetched_at': 0.0, 'failed_at': 0.0, 'source': None}


class RateUnavailable(Exception):
    """Raised when no sufficiently recent live price can be obtained."""


def _from_coingecko():
    headers = {'User-Agent': 'SkyChain/1.0'}
    api_key = os.getenv('COINGECKO_API_KEY', '').strip()
    if api_key:
        headers['x-cg-demo-api-key'] = api_key
    resp = httpx.get(
        COINGECKO_URL,
        params={'ids': ','.join(COINGECKO_IDS.values()), 'vs_currencies': 'usd'},
        headers=headers, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    prices = {}
    for sym, coin_id in COINGECKO_IDS.items():
        price = (data.get(coin_id) or {}).get('usd')
        if not price or price <= 0:
            raise ValueError(f'no price for {sym}')
        prices[sym] = float(price)
    return prices


def _from_coinbase():
    prices = {}
    for sym in SYMBOLS:
        resp = httpx.get(COINBASE_URL.format(sym=sym),
                         headers={'User-Agent': 'SkyChain/1.0'}, timeout=TIMEOUT)
        resp.raise_for_status()
        amount = float(resp.json()['data']['amount'])
        if amount <= 0:
            raise ValueError(f'zero price for {sym}')
        prices[sym] = amount
    return prices


def _fetch_live():
    errors = []
    for name, fetcher in (('coingecko', _from_coingecko), ('coinbase', _from_coinbase)):
        try:
            return name, fetcher()
        except Exception as exc:
            errors.append(f'{name}: {exc!r}')
            log.warning('[crypto_rates] %s failed: %r', name, exc)
    raise RuntimeError('; '.join(errors))


def get_usd_prices():
    """
    Returns:
      {'prices': {...USD per coin...}, 'as_of': ISO timestamp, 'source': 'live'|'cached'|'last-known'}
    Raises RateUnavailable if no acceptable price can be obtained.
    """
    with _lock:
        now = time.time()

        if _state['prices'] and now - _state['fetched_at'] < CACHE_SECONDS:
            return _snapshot('cached')

        if now - _state['failed_at'] >= RETRY_BACKOFF_SECONDS:
            try:
                name, prices = _fetch_live()
                _state.update(prices=prices, fetched_at=now, source=name, failed_at=0.0)
                return _snapshot('live')
            except Exception as exc:
                _state['failed_at'] = now
                log.error('[crypto_rates] all price sources failed: %s', exc)

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
    """Convert a USD total to a crypto amount, rounded to a sensible precision."""
    decimals = 2 if crypto in ('USDT', 'USDC') else 6
    return round(total_usd / prices[crypto], decimals)
