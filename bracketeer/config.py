import os


def _database_url(name: str = "DATABASE_URL") -> str:
    url = os.environ.get(name, "").strip()
    if not url:
        os.makedirs("instance", exist_ok=True)
        return "sqlite:///" + os.path.abspath(os.path.join("instance", "bracketeer.db"))
    # Hosts hand out "postgres://" or driver-less "postgresql://" URLs; pin the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


class Config:
    PRODUCTION = os.environ.get("BRACKETEER_ENV", "development") == "production"
    SECRET_KEY = os.environ.get("SECRET_KEY") or ("" if PRODUCTION else "dev-only-insecure-key")
    SQLALCHEMY_DATABASE_URI = _database_url()
    # Neon's pooled URL (PgBouncer) serves the app; Alembic migrations need a direct session,
    # so they use DATABASE_URL_UNPOOLED when it is set (see migrations/env.py).
    MIGRATIONS_DATABASE_URI = _database_url("DATABASE_URL_UNPOOLED") if os.environ.get("DATABASE_URL_UNPOOLED") else None
    # Free Postgres tiers (Neon) suspend idle connections, so check them before use.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", PRODUCTION)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024
    SITE_NAME = os.environ.get("SITE_NAME", "Bracketeer")
    REFRESH_SECONDS = int(os.environ.get("REFRESH_SECONDS", "60"))
    # Stellar: publishing result fingerprints to the results-registry contract (contracts/). All optional;
    # without STELLAR_CONTRACT_ID nothing onchain is shown, without STELLAR_SECRET_KEY nothing can be published.
    STELLAR_NETWORK = os.environ.get("STELLAR_NETWORK", "testnet")
    STELLAR_RPC_URL = os.environ.get("STELLAR_RPC_URL", "")
    STELLAR_CONTRACT_ID = os.environ.get("STELLAR_CONTRACT_ID", "").strip()
    STELLAR_SECRET_KEY = os.environ.get("STELLAR_SECRET_KEY", "").strip()
