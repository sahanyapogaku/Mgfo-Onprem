"""Configuration loaded from environment / .env — never hardcode secrets here."""
import os
from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# --- Manufacturo API ---
MNFO_BASE_URL = _env("MNFO_BASE_URL", "https://karman-industries.manufacturo.cloud")
MNFO_API_KEY = _env("MNFO_API_KEY", required=True)
HTTP_TIMEOUT_SECONDS = float(_env("MNFO_HTTP_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(_env("MNFO_MAX_RETRIES", "3"))
RETRY_BACKOFF_SECONDS = float(_env("MNFO_RETRY_BACKOFF_SECONDS", "2"))

# Short-lived interactive-login Bearer token for the undocumented purchase
# order "cockpit" list endpoint (no service-account/API-key variant exists
# for it). Optional: only needed to discover NEW order numbers; refreshing
# already-known orders works with MNFO_API_KEY alone. Paste a fresh token
# (captured from browser DevTools after logging into Manufacturo) before a
# bootstrap run — it expires in ~5 minutes. Never commit a real value.
MANUFACTURO_BEARER_TOKEN = _env("MANUFACTURO_BEARER_TOKEN")

# --- MSSQL ---
MSSQL_DRIVER = _env("MSSQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
MSSQL_SERVER = _env("MSSQL_SERVER", required=True)
MSSQL_DATABASE = _env("MSSQL_DATABASE", required=True)
MSSQL_UID = _env("MSSQL_UID", required=True)
MSSQL_PWD = _env("MSSQL_PWD", required=True)
MSSQL_ENCRYPT = _env("MSSQL_ENCRYPT", "yes")
MSSQL_TRUST_SERVER_CERTIFICATE = _env("MSSQL_TRUST_SERVER_CERTIFICATE", "no")


def mssql_connection_string():
    return (
        f"DRIVER={MSSQL_DRIVER};"
        f"SERVER={MSSQL_SERVER};"
        f"DATABASE={MSSQL_DATABASE};"
        f"UID={MSSQL_UID};"
        f"PWD={MSSQL_PWD};"
        f"Encrypt={MSSQL_ENCRYPT};"
        f"TrustServerCertificate={MSSQL_TRUST_SERVER_CERTIFICATE};"
    )


# --- Logging ---
ETL_LOG_LEVEL = _env("ETL_LOG_LEVEL", "INFO")
ETL_LOG_FILE = _env("ETL_LOG_FILE", "logs/etl.log")

# --- Per-endpoint page sizes (documented API maximums) ---
PAGE_SIZES = {
    "nonconformances": 25,
    "conditions": 25,
    "dispositions": 25,
    "equipment": 25,
    "process_plans": 10,  # API rejects >10 with HTTP 400 (confirmed live 2026-08-19)
    "execution_operations": 50,
    "execution_components": 50,
    "wip_traces": 50,
    "users": 50,
    "skills": 50,
    "work_centers": 200,
    "products": 25,
}
