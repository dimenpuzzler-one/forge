from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from forge_core.errors import SourceError
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


DEFAULT_BASE_URL = "https://skills.sh"


class Transport(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]: ...


class UrllibTransport:
    def get(self, url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes]:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS source adapter endpoint
                return response.status, dict(response.headers.items()), response.read()
        except HTTPError as error:
            return error.code, dict(error.headers.items()), error.read()
        except URLError as error:
            raise SourceError(f"Could not reach skills.sh: {error.reason}") from error


@dataclass(frozen=True)
class SkillPage:
    entries: list[SkillMetadata]
    page: int
    has_more: bool


class SkillsShAdapter:
    """skills.sh contract boundary; it only downloads JSON and never executes fetched content."""

    name = "skills-sh"

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        token: str | None = None,
        transport: Transport | None = None,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        sleep: Any = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token if token is not None else os.environ.get("VERCEL_OIDC_TOKEN")
        self.transport = transport or UrllibTransport()
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.sleep = sleep

    def list_skills(self, *, page: int, per_page: int = 100) -> SkillPage:
        if page < 0 or not 1 <= per_page <= 500:
            raise ValueError("page must be non-negative and per_page must be between 1 and 500")
        payload = self._get_json(
            "/api/v1/skills",
            {"view": "all-time", "page": page, "per_page": per_page},
        )
        data = payload.get("data")
        pagination = payload.get("pagination")
        if not isinstance(data, list) or not isinstance(pagination, dict):
            raise SourceError("skills.sh returned an unexpected list response.")
        entries = [SkillMetadata.from_api(item) for item in data if isinstance(item, dict)]
        response_page = pagination.get("page", page)
        return SkillPage(entries=entries, page=int(response_page), has_more=bool(pagination.get("hasMore", False)))

    def fetch_skill(self, skill_id: str) -> dict[str, Any]:
        if not _valid_skill_id(skill_id):
            raise ValueError(f"Invalid skills.sh skill id: {skill_id!r}")
        payload = self._get_json(f"/api/v1/skills/{quote(skill_id, safe='/')}", {})
        if str(payload.get("id", skill_id)) != skill_id:
            raise SourceError("skills.sh detail response did not match the requested skill id.")
        return payload

    def fetch_audit(self, skill_id: str) -> list[dict[str, Any]]:
        if not _valid_skill_id(skill_id):
            raise ValueError(f"Invalid skills.sh skill id: {skill_id!r}")
        try:
            payload = self._get_json(f"/api/v1/skills/audit/{quote(skill_id, safe='/')}", {})
        except SourceError as error:
            if error.status == 404:
                return []
            raise
        audits = payload.get("audits")
        if not isinstance(audits, list):
            raise SourceError("skills.sh returned an unexpected audit response.")
        return [audit for audit in audits if isinstance(audit, dict)]

    def _get_json(self, endpoint: str, parameters: dict[str, object]) -> dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        if parameters:
            url = f"{url}?{urlencode(parameters)}"
        headers = {"Accept": "application/json", "User-Agent": "forge-skill-toolkit/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        last_error: SourceError | None = None
        for attempt in range(self.max_attempts):
            try:
                status, response_headers, body = self.transport.get(url, headers, self.timeout_seconds)
            except SourceError as error:
                last_error = error
                if attempt + 1 == self.max_attempts:
                    break
                self.sleep(2**attempt)
                continue
            if 200 <= status < 300:
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise SourceError("skills.sh returned invalid JSON.", status=status) from error
                if not isinstance(parsed, dict):
                    raise SourceError("skills.sh returned a JSON response with an invalid shape.", status=status)
                return parsed
            retry_after = _retry_after(response_headers)
            message = _error_message(body)
            if status == 401:
                raise SourceError(
                    "skills.sh returned 401. Set VERCEL_OIDC_TOKEN and retry; locally stored metadata remains usable.",
                    status=status,
                )
            last_error = SourceError(
                f"skills.sh returned {status}{': ' + message if message else ''}",
                status=status,
                retry_after=retry_after,
            )
            if status not in {429, 500, 502, 503, 504} or attempt + 1 == self.max_attempts:
                break
            self.sleep(retry_after if retry_after is not None else 2**attempt)
        assert last_error is not None
        raise last_error


def sync_metadata(registry: Registry, adapter: SkillsShAdapter, *, per_page: int = 100) -> dict[str, int]:
    """Sync pages transactionally; a page is committed before the resume cursor advances."""
    source_id = registry.ensure_source(name=adapter.name, source_type="skills_sh", base_url=adapter.base_url)
    run_id = registry.start_sync_run(source_id)
    page = registry.source_cursor(source_id) or 0
    totals = {"pages": 0, "discovered": 0, "inserted": 0, "updated": 0}
    try:
        while True:
            response = adapter.list_skills(page=page, per_page=per_page)
            next_page = response.page + 1 if response.has_more else None
            counts = registry.upsert_metadata_page(
                source_id, response.entries, next_page=next_page, run_id=run_id
            )
            totals["pages"] += 1
            for key in ("discovered", "inserted", "updated"):
                totals[key] += counts[key]
            if not response.has_more:
                registry.mark_source_synced(source_id)
                registry.finish_sync_run(run_id)
                return totals
            page = next_page
            assert page is not None
    except Exception:
        registry.finish_sync_run(run_id, error_count=1)
        raise


def _valid_skill_id(skill_id: str) -> bool:
    parts = skill_id.split("/")
    return len(parts) >= 2 and all(part and part not in {".", ".."} for part in parts)


def _retry_after(headers: dict[str, str]) -> float | None:
    for key, value in headers.items():
        if key.casefold() == "retry-after":
            try:
                return max(0.0, float(value))
            except ValueError:
                return None
    return None


def _error_message(body: bytes) -> str:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ""
    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        return parsed["message"]
    return ""
