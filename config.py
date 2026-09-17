import os
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse, quote

load_dotenv()


def _fix_db_url(url: str) -> str:
    """
    Supabase connection strings use percent-encoded characters in the password
    (e.g. %23 for #, %40 for @).  SQLAlchemy's engine needs the URL to use the
    postgresql+psycopg2 dialect and the password must stay encoded.
    """
    if not url:
        return 'sqlite:///flight_booking.db'
    # Swap scheme so SQLAlchemy uses psycopg2
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg2://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg2://' + url[len('postgresql://'):]
    return url


class Config:
    SECRET_KEY               = os.getenv('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI  = _fix_db_url(os.getenv('DATABASE_URL', ''))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,       # drops stale connections before use
        'pool_recycle':  300,        # recycle connections every 5 min
        'connect_args':  {
            'sslmode':        'require',   # Supabase requires SSL
            'connect_timeout': 10,
        }
    }

    # Supabase Realtime (exposed to frontend via template)
    SUPABASE_URL      = os.getenv('SUPABASE_URL', '')
    SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY', '')

    # Crypto wallets
    BTC_WALLET        = os.getenv('BTC_WALLET', '')
    ETH_WALLET        = os.getenv('ETH_WALLET', '')
    SOL_WALLET        = os.getenv('SOL_WALLET', '')
    # USDT — ERC-20 (Ethereum) and SPL (Solana)
    USDT_ETH_WALLET   = os.getenv('USDT_ETH_WALLET', '')
    USDT_SOL_WALLET   = os.getenv('USDT_SOL_WALLET', '')
    # USDC — ERC-20 (Ethereum) and SPL (Solana)
    USDC_ETH_WALLET   = os.getenv('USDC_ETH_WALLET', '')
    USDC_SOL_WALLET   = os.getenv('USDC_SOL_WALLET', '')
    WEB3_PROVIDER = os.getenv('WEB3_PROVIDER', 'https://mainnet.infura.io/v3/your_key')
