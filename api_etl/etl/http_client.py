"""
Manufacturo HTTP client.

Safety net: this client only knows how to call the exact (method, path) pairs in
ALLOWLIST below. Any attempt to call something else raises DisallowedEndpointError
before a request is ever sent. This is a defense-in-depth measure — the API key
itself should also be scoped read-only — but the allowlist ensures a coding
mistake (e.g. accidentally hitting an upsert endpoint) fails loudly instead of
mutating Manufacturo data.
"""
import logging
import time

import requests

from etl import config

logger = logging.getLogger("etl.http_client")

# Exactly the endpoints this pipeline is permitted to call. GET and POST .../filter
# or .../list only — no create/update/delete/upsert/action-trigger endpoints.
ALLOWLIST = {
    ("POST", "/eworkin-plus/nc/api/v2/nonconformances/filter"),
    ("POST", "/eworkin-plus/nc/api/v2/conditions/filter"),
    ("POST", "/eworkin-plus/nc/api/v2/dispositions/filter"),
    ("POST", "/equipment/api/public/equipment/filter"),
    ("POST", "/eworkin-plus/planning/api/v2/process-plans/filter"),
    ("POST", "/eworkin-plus/execution/api/v1/operations/filter"),
    ("POST", "/eworkin-plus/execution/api/v1/components/filter"),
    ("POST", "/eworkin-plus/execution/api/v1/wip-traces/filter"),
    ("POST", "/api/v1/persons/list"),
    ("POST", "/api/v1/skills/list"),
    ("POST", "/api/v1/work-centers/list"),
    ("POST", "/eworkin-plus/masterdata/api/public/products/filter"),
    ("GET", "/eworkin-plus/masterdata/api/v1/public/inspection-codes"),
    ("GET", "/eworkin-plus/inventory/api/integrations/orders/purchase-orders"),
}

RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


class DisallowedEndpointError(Exception):
    pass


class ManufacturoApiError(Exception):
    pass


class ManufacturoClient:
    """Thin, read-only wrapper around the Manufacturo Public API."""

    def __init__(self, base_url=None, api_key=None, session=None):
        self.base_url = (base_url or config.MNFO_BASE_URL).rstrip("/")
        self.api_key = api_key or config.MNFO_API_KEY
        self.session = session or requests.Session()

    def _check_allowlist(self, method, path):
        if (method, path) not in ALLOWLIST:
            logger.error("Blocked disallowed endpoint call: %s %s", method, path)
            raise DisallowedEndpointError(
                f"{method} {path} is not in the read-only allowlist. "
                "This pipeline may only call GET/filter/list endpoints."
            )

    def _request(self, method, path, json_body=None, params=None):
        self._check_allowlist(method, path)
        url = f"{self.base_url}{path}"
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}

        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                    timeout=config.HTTP_TIMEOUT_SECONDS,
                )
            except requests.exceptions.RequestException as exc:
                if attempt > config.MAX_RETRIES:
                    raise ManufacturoApiError(
                        f"{method} {path} failed after {attempt} attempts: {exc}"
                    ) from exc
                backoff = config.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Network error on %s %s (attempt %d/%d): %s — retrying in %.1fs",
                    method, path, attempt, config.MAX_RETRIES, exc, backoff,
                )
                time.sleep(backoff)
                continue

            if resp.status_code in RETRYABLE_STATUS_CODES:
                if attempt > config.MAX_RETRIES:
                    raise ManufacturoApiError(
                        f"{method} {path} failed after {attempt} attempts: "
                        f"HTTP {resp.status_code} — {resp.text[:500]}"
                    )
                backoff = config.RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    "Retryable HTTP %d on %s %s (attempt %d/%d) — retrying in %.1fs",
                    resp.status_code, method, path, attempt, config.MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
                continue

            if not resp.ok:
                raise ManufacturoApiError(
                    f"{method} {path} returned HTTP {resp.status_code}: {resp.text[:500]}"
                )

            if not resp.content:
                return {}
            return resp.json()

    def get(self, path, params=None):
        return self._request("GET", path, params=params)

    def post_filter(self, path, body):
        return self._request("POST", path, json_body=body or {})
