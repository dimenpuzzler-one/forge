from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from forge_core.errors import ValidationError
from forge_core.models import SkillMetadata


SCHEMA_VERSION = 2
MAX_SKILL_FILE_BYTES = 1_048_576
MAX_SKILL_TOTAL_BYTES = 5 * 1_048_576
SCRIPT_SUFFIXES = {".bat", ".cmd", ".exe", ".ps1", ".py", ".sh", ".zsh"}
SUSPICIOUS_PATTERNS = {
    "network download command": re.compile(r"\b(curl|wget|invoke-webrequest|iwr)\b", re.IGNORECASE),
    "encoded payload": re.compile(r"\b(base64|frombase64string)\b", re.IGNORECASE),
    "credential exfiltration language": re.compile(r"\b(send|upload|post).{0,80}\b(token|secret|credential|api[_ -]?key)\b", re.IGNORECASE | re.DOTALL),
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def valid_relative_skill_path(value: str) -> bool:
    path = PurePosixPath(value)
    first_part = path.parts[0] if path.parts else ""
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and not PureWindowsPath(value).is_absolute()
        and ".." not in path.parts
        and ":" not in first_part
        and "\x00" not in value
    )


def _source_owner(source: str) -> str:
    return source.split("/", 1)[0]


class Registry:
    """SQLite storage for metadata, FTS search, and immutable cached detail."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")

    def close(self) -> None:
        self.connection.close()

    def migrate(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema version {current} is newer than this Forge release ({SCHEMA_VERSION})."
            )
        if current == 0:
            self.connection.executescript(
                """
                CREATE TABLE sources (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_sync_at TEXT,
                    sync_cursor TEXT
                );

                CREATE TABLE skills (
                    id TEXT PRIMARY KEY,
                    upstream_id TEXT NOT NULL,
                    source_id INTEGER NOT NULL REFERENCES sources(id),
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    source_repo TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT '',
                    install_url TEXT,
                    skills_sh_url TEXT,
                    install_count INTEGER NOT NULL DEFAULT 0,
                    is_duplicate INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    latest_seen_version_id INTEGER,
                    trusted_version_id INTEGER
                );

                CREATE TABLE skill_versions (
                    id INTEGER PRIMARY KEY,
                    skill_id TEXT NOT NULL REFERENCES skills(id),
                    content_hash TEXT NOT NULL,
                    git_commit_sha TEXT,
                    observed_at TEXT NOT NULL,
                    file_count INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    license_spdx TEXT,
                    license_status TEXT NOT NULL DEFAULT 'unknown',
                    security_status TEXT NOT NULL DEFAULT 'unknown',
                    risk_level TEXT NOT NULL DEFAULT 'unknown',
                    UNIQUE(skill_id, content_hash)
                );

                CREATE TABLE skill_files (
                    id INTEGER PRIMARY KEY,
                    skill_version_id INTEGER NOT NULL REFERENCES skill_versions(id),
                    path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    media_type TEXT,
                    contents TEXT,
                    is_entrypoint INTEGER NOT NULL DEFAULT 0,
                    is_script INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(skill_version_id, path)
                );

                CREATE TABLE security_audits (
                    id INTEGER PRIMARY KEY,
                    skill_version_id INTEGER NOT NULL REFERENCES skill_versions(id),
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    risk_level TEXT,
                    summary TEXT,
                    audited_at TEXT,
                    raw_json TEXT,
                    UNIQUE(skill_version_id, provider)
                );

                CREATE TABLE sync_runs (
                    id INTEGER PRIMARY KEY,
                    source_id INTEGER NOT NULL REFERENCES sources(id),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    pages INTEGER NOT NULL DEFAULT 0,
                    discovered INTEGER NOT NULL DEFAULT 0,
                    inserted INTEGER NOT NULL DEFAULT 0,
                    updated INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE VIRTUAL TABLE skills_fts USING fts5(
                    skill_id UNINDEXED,
                    name,
                    description,
                    source,
                    owner
                );
                """
            )
            self.connection.execute("PRAGMA user_version = 1")
            self.connection.commit()
            current = 1
        if current < 2:
            self.connection.executescript(
                """
                CREATE TABLE collections (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE collection_skills (
                    collection_id INTEGER NOT NULL REFERENCES collections(id),
                    skill_id TEXT NOT NULL REFERENCES skills(id),
                    added_at TEXT NOT NULL,
                    PRIMARY KEY(collection_id, skill_id)
                );

                CREATE TABLE compositions (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    goal TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE composition_skills (
                    composition_id INTEGER NOT NULL REFERENCES compositions(id),
                    skill_id TEXT NOT NULL REFERENCES skills(id),
                    content_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY(composition_id, skill_id)
                );
                """
            )
            self.connection.execute("PRAGMA user_version = 2")
            self.connection.commit()

    @contextmanager
    def transaction(self):
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def ensure_source(self, *, name: str, source_type: str, base_url: str) -> int:
        self.connection.execute(
            """
            INSERT INTO sources(name, type, base_url) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET type = excluded.type, base_url = excluded.base_url
            """,
            (name, source_type, base_url),
        )
        row = self.connection.execute("SELECT id FROM sources WHERE name = ?", (name,)).fetchone()
        self.connection.commit()
        assert row is not None
        return int(row["id"])

    def source_cursor(self, source_id: int) -> int | None:
        row = self.connection.execute("SELECT sync_cursor FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None or row["sync_cursor"] is None:
            return None
        try:
            return int(row["sync_cursor"])
        except ValueError:
            return None

    def start_sync_run(self, source_id: int) -> int:
        cursor = self.connection.execute(
            "INSERT INTO sync_runs(source_id, started_at) VALUES (?, ?)", (source_id, utc_now())
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_sync_run(self, run_id: int, *, error_count: int = 0) -> None:
        self.connection.execute(
            "UPDATE sync_runs SET completed_at = ?, error_count = ? WHERE id = ?",
            (utc_now(), error_count, run_id),
        )
        self.connection.commit()

    def upsert_metadata_page(
        self, source_id: int, entries: Iterable[SkillMetadata], *, next_page: int | None, run_id: int
    ) -> dict[str, int]:
        inserted = updated = discovered = 0
        now = utc_now()
        with self.transaction():
            for entry in entries:
                discovered += 1
                exists = self.connection.execute("SELECT 1 FROM skills WHERE id = ?", (entry.id,)).fetchone()
                if exists is None:
                    inserted += 1
                    self.connection.execute(
                        """
                        INSERT INTO skills(
                            id, upstream_id, source_id, slug, name, description, source_repo,
                            source_type, install_url, skills_sh_url, install_count, is_duplicate,
                            first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry.id,
                            entry.id,
                            source_id,
                            entry.slug,
                            entry.name,
                            entry.description,
                            entry.source,
                            entry.source_type,
                            entry.install_url,
                            entry.skills_sh_url,
                            entry.installs,
                            int(entry.is_duplicate),
                            now,
                            now,
                        ),
                    )
                else:
                    updated += 1
                    self.connection.execute(
                        """
                        UPDATE skills SET slug = ?, name = ?, description = ?, source_repo = ?,
                            source_type = ?, install_url = ?, skills_sh_url = ?, install_count = ?,
                            is_duplicate = ?, last_seen_at = ? WHERE id = ?
                        """,
                        (
                            entry.slug,
                            entry.name,
                            entry.description,
                            entry.source,
                            entry.source_type,
                            entry.install_url,
                            entry.skills_sh_url,
                            entry.installs,
                            int(entry.is_duplicate),
                            now,
                            entry.id,
                        ),
                    )
                self.connection.execute("DELETE FROM skills_fts WHERE skill_id = ?", (entry.id,))
                self.connection.execute(
                    "INSERT INTO skills_fts(skill_id, name, description, source, owner) VALUES (?, ?, ?, ?, ?)",
                    (entry.id, entry.name, entry.description, entry.source, _source_owner(entry.source)),
                )
            self.connection.execute(
                "UPDATE sources SET sync_cursor = ? WHERE id = ?",
                (str(next_page) if next_page is not None else None, source_id),
            )
            self.connection.execute(
                """
                UPDATE sync_runs
                SET pages = pages + 1, discovered = discovered + ?, inserted = inserted + ?, updated = updated + ?
                WHERE id = ?
                """,
                (discovered, inserted, updated, run_id),
            )
        return {"discovered": discovered, "inserted": inserted, "updated": updated}

    def mark_source_synced(self, source_id: int) -> None:
        self.connection.execute("UPDATE sources SET last_sync_at = ?, sync_cursor = NULL WHERE id = ?", (utc_now(), source_id))
        self.connection.commit()

    def search(self, query: str, *, limit: int = 20) -> list[sqlite3.Row]:
        tokens = [token for token in query.replace('"', " ").split() if token]
        if not tokens:
            return []
        # Metadata listings may not include a rich description, so retain useful partial matches.
        fts_query = " OR ".join(f'"{token}"' for token in tokens)
        try:
            return list(
                self.connection.execute(
                    """
                    SELECT s.*, bm25(skills_fts) AS lexical_rank
                    FROM skills_fts
                    JOIN skills AS s ON s.id = skills_fts.skill_id
                    WHERE skills_fts MATCH ?
                    ORDER BY lexical_rank, s.install_count DESC, s.name COLLATE NOCASE
                    LIMIT ?
                    """,
                    (fts_query, limit),
                )
            )
        except sqlite3.OperationalError:
            pattern = f"%{query}%"
            return list(
                self.connection.execute(
                    """
                    SELECT *, 0 AS lexical_rank FROM skills
                    WHERE name LIKE ? OR description LIKE ? OR source_repo LIKE ?
                    ORDER BY install_count DESC, name COLLATE NOCASE LIMIT ?
                    """,
                    (pattern, pattern, pattern, limit),
                )
            )

    def get_skill(self, skill_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT s.*, v.content_hash, v.file_count, v.total_bytes, v.license_spdx, v.license_status,
                v.security_status, v.risk_level
            FROM skills AS s
            LEFT JOIN skill_versions AS v ON v.id = s.latest_seen_version_id
            WHERE s.id = ?
            """,
            (skill_id,),
        ).fetchone()

    def get_files(self, skill_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT f.* FROM skill_files AS f
                JOIN skill_versions AS v ON v.id = f.skill_version_id
                JOIN skills AS s ON s.latest_seen_version_id = v.id
                WHERE s.id = ? ORDER BY f.path
                """,
                (skill_id,),
            )
        )

    def create_collection(self, name: str) -> None:
        _validate_name(name, label="Collection")
        try:
            self.connection.execute("INSERT INTO collections(name, created_at) VALUES (?, ?)", (name, utc_now()))
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Collection already exists: {name}") from error

    def add_to_collection(self, name: str, skill_id: str) -> None:
        collection = self.connection.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone()
        if collection is None:
            raise ValueError(f"Collection not found: {name}")
        if self.get_skill(skill_id) is None:
            raise ValueError(f"Skill not found locally: {skill_id}")
        self.connection.execute(
            "INSERT OR IGNORE INTO collection_skills(collection_id, skill_id, added_at) VALUES (?, ?, ?)",
            (collection["id"], skill_id, utc_now()),
        )
        self.connection.commit()

    def list_collections(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT c.name, c.created_at, COUNT(cs.skill_id) AS skill_count
                FROM collections AS c LEFT JOIN collection_skills AS cs ON cs.collection_id = c.id
                GROUP BY c.id ORDER BY c.name COLLATE NOCASE
                """
            )
        )

    def get_collection_skills(self, name: str) -> list[sqlite3.Row]:
        exists = self.connection.execute("SELECT 1 FROM collections WHERE name = ?", (name,)).fetchone()
        if exists is None:
            raise ValueError(f"Collection not found: {name}")
        return list(
            self.connection.execute(
                """
                SELECT s.* FROM collection_skills AS cs
                JOIN collections AS c ON c.id = cs.collection_id
                JOIN skills AS s ON s.id = cs.skill_id
                WHERE c.name = ? ORDER BY cs.added_at, s.name COLLATE NOCASE
                """,
                (name,),
            )
        )

    def create_composition(self, name: str, *, goal: str = "") -> None:
        _validate_name(name, label="Composition")
        now = utc_now()
        try:
            self.connection.execute(
                "INSERT INTO compositions(name, goal, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (name, goal, now, now),
            )
            self.connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError(f"Composition already exists: {name}") from error

    def get_composition(self, name: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM compositions WHERE name = ?", (name,)).fetchone()

    def add_composition_skill(self, *, name: str, skill_id: str, content_hash: str, role: str) -> None:
        composition = self.get_composition(name)
        if composition is None:
            raise ValueError(f"Composition not found: {name}")
        _validate_name(role, label="Role")
        current = self.connection.execute(
            "SELECT position FROM composition_skills WHERE composition_id = ? AND skill_id = ?",
            (composition["id"], skill_id),
        ).fetchone()
        if current is None:
            position = int(
                self.connection.execute(
                    "SELECT COALESCE(MAX(position), 0) + 1 FROM composition_skills WHERE composition_id = ?",
                    (composition["id"],),
                ).fetchone()[0]
            )
            self.connection.execute(
                """
                INSERT INTO composition_skills(composition_id, skill_id, content_hash, role, position)
                VALUES (?, ?, ?, ?, ?)
                """,
                (composition["id"], skill_id, content_hash, role, position),
            )
        else:
            self.connection.execute(
                """
                UPDATE composition_skills SET content_hash = ?, role = ?
                WHERE composition_id = ? AND skill_id = ?
                """,
                (content_hash, role, composition["id"], skill_id),
            )
        self.connection.execute("UPDATE compositions SET updated_at = ? WHERE id = ?", (utc_now(), composition["id"]))
        self.connection.commit()

    def get_composition_skills(self, name: str) -> list[sqlite3.Row]:
        composition = self.get_composition(name)
        if composition is None:
            raise ValueError(f"Composition not found: {name}")
        return list(
            self.connection.execute(
                """
                SELECT cs.skill_id, cs.content_hash, cs.role, cs.position, s.name, s.source_repo,
                    EXISTS(
                        SELECT 1 FROM skill_files AS f
                        JOIN skill_versions AS v ON v.id = f.skill_version_id
                        WHERE v.skill_id = cs.skill_id AND v.content_hash = cs.content_hash AND f.is_script = 1
                    ) AS has_scripts
                FROM composition_skills AS cs
                JOIN skills AS s ON s.id = cs.skill_id
                WHERE cs.composition_id = ? ORDER BY cs.position
                """,
                (composition["id"],),
            )
        )

    def store_detail(self, skill_id: str, detail: dict[str, Any], *, snapshots_root: Path) -> tuple[int, str]:
        skill = self.get_skill(skill_id)
        if skill is None:
            raise ValidationError(f"Cannot cache unknown skill: {skill_id}")
        raw_files = detail.get("files")
        if not isinstance(raw_files, list):
            raise ValidationError("Skill detail did not contain a file list.")
        files: list[tuple[str, str, str]] = []
        total_bytes = 0
        digest = hashlib.sha256()
        for raw_file in raw_files:
            if not isinstance(raw_file, dict):
                raise ValidationError("Skill detail included an invalid file entry.")
            path = raw_file.get("path")
            contents = raw_file.get("contents")
            if not isinstance(path, str) or not valid_relative_skill_path(path):
                raise ValidationError(f"Rejected unsafe upstream file path: {path!r}")
            if not isinstance(contents, str):
                raise ValidationError(f"Skill file {path!r} did not contain text contents.")
            size = len(contents.encode("utf-8"))
            if size > MAX_SKILL_FILE_BYTES:
                raise ValidationError(f"Rejected unexpectedly large upstream file: {path}")
            total_bytes += size
            if total_bytes > MAX_SKILL_TOTAL_BYTES:
                raise ValidationError("Rejected skill detail larger than the configured 5 MiB safety limit.")
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(contents.encode("utf-8"))
            digest.update(b"\0")
            files.append((path, contents, hashlib.sha256(contents.encode("utf-8")).hexdigest()))
        content_hash = detail.get("hash")
        if not isinstance(content_hash, str) or not content_hash:
            content_hash = digest.hexdigest()
        snapshot_root = snapshots_root / "skills-sh" / _safe_snapshot_name(skill_id) / content_hash
        snapshot_root.mkdir(parents=True, exist_ok=True)
        license_value = detail.get("license")
        license_spdx = license_value.strip() if isinstance(license_value, str) and license_value.strip() else None
        license_status = "known" if license_spdx else "unknown"
        static_audit = _static_audit(files)
        with self.transaction():
            self.connection.execute(
                """
                INSERT INTO skill_versions(
                    skill_id, content_hash, observed_at, file_count, total_bytes, license_spdx,
                    license_status, security_status, risk_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id, content_hash) DO NOTHING
                """,
                (
                    skill_id,
                    content_hash,
                    utc_now(),
                    len(files),
                    total_bytes,
                    license_spdx,
                    license_status,
                    static_audit["status"],
                    static_audit["risk_level"],
                ),
            )
            version = self.connection.execute(
                "SELECT id FROM skill_versions WHERE skill_id = ? AND content_hash = ?", (skill_id, content_hash)
            ).fetchone()
            assert version is not None
            version_id = int(version["id"])
            for path, contents, file_hash in files:
                output = snapshot_root / PurePosixPath(path)
                output.parent.mkdir(parents=True, exist_ok=True)
                if not output.exists():
                    output.write_text(contents, encoding="utf-8")
                suffix = PurePosixPath(path).suffix.casefold()
                self.connection.execute(
                    """
                    INSERT INTO skill_files(
                        skill_version_id, path, content_hash, size, media_type, contents, is_entrypoint, is_script
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(skill_version_id, path) DO NOTHING
                    """,
                    (
                        version_id,
                        path,
                        file_hash,
                        len(contents.encode("utf-8")),
                        "text/markdown" if suffix in {".md", ".mdx"} else "text/plain",
                        contents,
                        int(PurePosixPath(path).name.casefold() == "skill.md"),
                        int(suffix in SCRIPT_SUFFIXES),
                    ),
                )
            self.connection.execute(
                """
                INSERT INTO security_audits(skill_version_id, provider, status, risk_level, summary, audited_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_version_id, provider) DO UPDATE SET
                    status = excluded.status, risk_level = excluded.risk_level, summary = excluded.summary,
                    audited_at = excluded.audited_at, raw_json = excluded.raw_json
                """,
                (
                    version_id,
                    "forge-static",
                    static_audit["status"],
                    static_audit["risk_level"],
                    static_audit["summary"],
                    utc_now(),
                    json.dumps(static_audit, ensure_ascii=False),
                ),
            )
            self.connection.execute("UPDATE skills SET latest_seen_version_id = ? WHERE id = ?", (version_id, skill_id))
        return version_id, content_hash

    def get_version_files(self, skill_id: str, content_hash: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT f.* FROM skill_files AS f JOIN skill_versions AS v ON v.id = f.skill_version_id
                WHERE v.skill_id = ? AND v.content_hash = ? ORDER BY f.path
                """,
                (skill_id, content_hash),
            )
        )

    def get_audits(self, skill_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                """
                SELECT a.* FROM security_audits AS a
                JOIN skills AS s ON s.latest_seen_version_id = a.skill_version_id
                WHERE s.id = ? ORDER BY a.provider
                """,
                (skill_id,),
            )
        )

    def store_external_audits(self, skill_id: str, audits: list[dict[str, Any]]) -> int:
        skill = self.get_skill(skill_id)
        if skill is None or skill["latest_seen_version_id"] is None:
            raise ValueError("Cache a Skill detail before importing its security audit.")
        version_id = int(skill["latest_seen_version_id"])
        for audit in audits:
            provider = str(audit.get("provider") or audit.get("slug") or "skills-sh")
            status = str(audit.get("status") or "unknown").casefold()
            risk = str(audit.get("riskLevel") or "unknown").casefold()
            self.connection.execute(
                """
                INSERT INTO security_audits(skill_version_id, provider, status, risk_level, summary, audited_at, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_version_id, provider) DO UPDATE SET
                    status = excluded.status, risk_level = excluded.risk_level, summary = excluded.summary,
                    audited_at = excluded.audited_at, raw_json = excluded.raw_json
                """,
                (
                    version_id,
                    provider,
                    status,
                    risk,
                    str(audit.get("summary") or ""),
                    str(audit.get("auditedAt") or utc_now()),
                    json.dumps(audit, ensure_ascii=False),
                ),
            )
        self.connection.commit()
        return len(audits)


def _safe_snapshot_name(skill_id: str) -> str:
    return hashlib.sha256(skill_id.encode("utf-8")).hexdigest()[:16]


def _validate_name(value: str, *, label: str) -> None:
    if not value or not value.strip() or len(value) > 120 or any(character in value for character in "\\/:\x00"):
        raise ValueError(f"{label} name must be 1–120 characters and cannot contain path separators.")


def _static_audit(files: list[tuple[str, str, str]]) -> dict[str, Any]:
    signals: list[dict[str, str]] = []
    script_count = 0
    for path, contents, _ in files:
        suffix = PurePosixPath(path).suffix.casefold()
        if suffix in SCRIPT_SUFFIXES:
            script_count += 1
        for label, pattern in SUSPICIOUS_PATTERNS.items():
            if pattern.search(contents):
                signals.append({"path": path, "signal": label})
    if signals:
        status, risk_level = "warn", "medium"
        summary = f"Static review found {len(signals)} suspicious signal(s); inspect before using."
    elif script_count:
        status, risk_level = "warn", "low"
        summary = f"Static review found {script_count} script file(s); scripts are not executed by Forge."
    else:
        status, risk_level = "pass", "low"
        summary = "No static risk signals found. This is not a safety guarantee."
    return {
        "provider": "forge-static",
        "status": status,
        "risk_level": risk_level,
        "summary": summary,
        "signals": signals,
        "scriptCount": script_count,
    }
