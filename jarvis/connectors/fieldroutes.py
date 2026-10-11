"""Read-only FieldRoutes API client.

Safety: the client can only call ``*/search`` and ``*/get`` endpoints. Any
other path (create, update, delete, charge, send ...) raises before a request is
made, so JARVIS cannot change a customer record or trigger a customer
communication even if a bug or a future agent tried to.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from jarvis.connectors.base import EntityUnsupported, SourceError
from jarvis.connectors.fieldroutes_mapping import DATE_FILTERS, ENDPOINTS, MAPPERS
from jarvis.logging_setup import log_event

log = logging.getLogger(__name__)

READ_ONLY_PATH = re.compile(r"^[a-zA-Z]+/(search|get)$")
GET_BATCH = 1000  # FieldRoutes /get accepts up to 1000 IDs per call


class ReadOnlyViolation(RuntimeError):
    pass


class _Retryable(Exception):
    pass


class FieldRoutesClient:
    name = "fieldroutes"

    def __init__(
        self,
        subdomain: str,
        auth_key: str,
        auth_token: str,
        office_ids: list[str] | None = None,
        timeout: int = 60,
        session: requests.Session | None = None,
    ):
        if not re.fullmatch(r"[a-z0-9-]+", subdomain or ""):
            raise ValueError("Invalid FieldRoutes subdomain")
        self.base_url = f"https://{subdomain}.pestroutes.com/api/"
        self._auth = {"authenticationKey": auth_key, "authenticationToken": auth_token}
        self.office_ids = [str(o) for o in (office_ids or [])]
        self.timeout = timeout
        self.http = session or requests.Session()

    # ------------------------------------------------------------------ transport
    @retry(
        retry=retry_if_exception_type(_Retryable),
        wait=wait_exponential(multiplier=2, max=60) + wait_random(0, 2),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _call(self, path: str, params: dict) -> dict:
        if not READ_ONLY_PATH.match(path):
            raise ReadOnlyViolation(f"JARVIS is read-only; refusing to call FieldRoutes '{path}'")
        try:
            # Credentials go in the POST body, never the URL, so they can't leak into proxy/access logs.
            resp = self.http.post(self.base_url + path, data={**self._auth, **params}, timeout=self.timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise _Retryable(str(exc)) from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _Retryable(f"HTTP {resp.status_code} from {path}")
        if resp.status_code in (401, 403):
            raise EntityUnsupported(f"HTTP {resp.status_code}: credentials lack access to {path}")
        if resp.status_code >= 400:
            raise SourceError(f"HTTP {resp.status_code} from {path}: {resp.text[:300]}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise SourceError(f"Non-JSON response from {path}") from exc
        if body.get("success") is False:
            msg = str(body.get("errorMessage") or body.get("message") or body)[:300]
            if re.search(r"permission|not authori[sz]ed|access", msg, re.I):
                raise EntityUnsupported(f"{path}: {msg}")
            raise SourceError(f"{path}: {msg}")
        return body

    # ------------------------------------------------------------------ search/get
    def search_ids(self, entity: str, filters: dict) -> list[str]:
        segment, ids_key, _ = ENDPOINTS[entity]
        params = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in filters.items()}
        if self.office_ids:
            params["officeIDs"] = json.dumps(self.office_ids)
        body = self._call(f"{segment}/search", params)
        ids = body.get(ids_key) or []
        # FieldRoutes caps search results; if we hit the cap, fail loudly rather than undercount.
        if body.get("count") is not None and int(body["count"]) > len(ids):
            raise SourceError(
                f"{segment}/search returned {len(ids)} of {body['count']} IDs; narrow the window"
            )
        return [str(i) for i in ids]

    def get_records(self, entity: str, ids: list[str]) -> list[dict]:
        segment, ids_key, records_key = ENDPOINTS[entity]
        out: list[dict] = []
        for i in range(0, len(ids), GET_BATCH):
            body = self._call(f"{segment}/get", {ids_key: json.dumps(ids[i : i + GET_BATCH])})
            out.extend(body.get(records_key) or [])
        return out

    def fetch(self, entity: str, start: date, end: date) -> list[dict]:
        between = {"operator": "BETWEEN", "value": [start.isoformat(), end.isoformat()]}
        filters = DATE_FILTERS[entity]
        ids: set[str] = set()
        if not filters:
            ids.update(self.search_ids(entity, {}))
        for field in filters:
            ids.update(self.search_ids(entity, {field: between}))
        records = self.get_records(entity, sorted(ids))
        mapper = MAPPERS[entity]
        rows = [mapper(r) for r in records]
        log_event(log, "fieldroutes.fetch", entity=entity, start=start, end=end, records=len(rows))
        return rows
