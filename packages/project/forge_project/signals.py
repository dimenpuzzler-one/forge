from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

# A term appearing in prose is not evidence that a project uses that technology. Forge learned
# this by scanning itself: documentation examples and benchmark fixtures promoted supabase,
# quant, and payments into the project's declared stack, which then poisoned planner retrieval.
#
# Evidence is therefore weighted by where it was found, and only a Skill's aggregate confidence
# decides whether it is reported as "used" (safe to expand a retrieval query with) or merely
# "mentioned" (recorded, never expanded).

WEIGHTS = {
    "manifest": 1.0,   # a declared dependency in package.json, pyproject.toml, requirements, go.mod, Cargo.toml
    "import": 0.9,     # an actual import or require in source code
    "config": 0.85,    # a technology-specific config file or directory
    "project-name": 0.35,
    "readme": 0.20,    # the primary README describing the project
    "prose": 0.05,     # any other document: planning notes, development logs, architecture prose
}

USED_THRESHOLD = 0.5

# Never contribute signal. These contain terms describing *other* projects: authored test
# fixtures, generated benchmark output, and recorded execution history.
SIGNAL_EXCLUDED_PREFIXES = (
    "tests/fixtures",
    "test/fixtures",
    "artifacts",
    ".forge",
    "node_modules",
    "vendor",
    "third_party",
    "examples",
)

SOURCE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs"}
MAX_SOURCE_FILES = 400
MAX_SOURCE_BYTES = 256 * 1024

PYTHON_IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_.]+)|import\s+([A-Za-z0-9_.]+))", re.MULTILINE)
JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*)['"]([^'"]+)['"]""")

# technology -> (category, manifest package names, config paths, prose terms)
TECHNOLOGIES: dict[str, dict[str, Any]] = {
    "nextjs": {
        "category": "stack",
        "packages": ("next",),
        "modules": ("next",),
        "configs": ("next.config.js", "next.config.mjs", "next.config.ts"),
        "terms": ("next.js", "nextjs"),
    },
    "react": {
        "category": "stack",
        "packages": ("react",),
        "modules": ("react",),
        "configs": (),
        "terms": ("react",),
    },
    "supabase": {
        "category": "stack",
        "packages": ("@supabase/supabase-js", "supabase"),
        "modules": ("supabase", "@supabase/supabase-js"),
        "configs": ("supabase/config.toml", "supabase"),
        "terms": ("supabase",),
    },
    "turborepo": {
        "category": "stack",
        "packages": ("turbo",),
        "modules": (),
        "configs": ("turbo.json",),
        "terms": ("turborepo",),
    },
    "fastapi": {
        "category": "stack",
        "packages": ("fastapi",),
        "modules": ("fastapi",),
        "configs": (),
        "terms": ("fastapi",),
    },
    "django": {
        "category": "stack",
        "packages": ("django",),
        "modules": ("django",),
        "configs": ("manage.py",),
        "terms": ("django",),
    },
    "postgres": {
        "category": "stack",
        "packages": ("psycopg", "psycopg2", "psycopg2-binary", "asyncpg", "pg"),
        "modules": ("psycopg", "psycopg2", "asyncpg"),
        "configs": (),
        "terms": ("postgres", "postgresql"),
    },
    "quant": {
        "category": "domain",
        "packages": ("backtrader", "zipline", "vectorbt"),
        "modules": ("backtrader", "zipline", "vectorbt"),
        "configs": (),
        "terms": ("quant", "trading", "equity", "futures", "market"),
    },
    "backtesting": {
        "category": "domain",
        "packages": ("backtrader", "zipline", "vectorbt"),
        "modules": ("backtrader", "zipline", "vectorbt"),
        "configs": (),
        "terms": ("backtest", "walk-forward", "monte carlo"),
    },
    "kr-equity": {
        "category": "domain",
        "packages": (),
        "modules": (),
        "configs": (),
        "terms": ("korea stock", "korean stock", "한국주식", "creon"),
    },
    "payments": {
        "category": "domain",
        "packages": ("stripe", "@stripe/stripe-js"),
        "modules": ("stripe",),
        "configs": (),
        "terms": ("payment", "결제", "ksnet", "stripe"),
    },
    "ai": {
        "category": "domain",
        "packages": ("openai", "anthropic", "langchain", "llama-index"),
        "modules": ("openai", "anthropic", "langchain"),
        "configs": (),
        "terms": ("openai", "llm", "structured output", "agent"),
    },
    "saas": {
        "category": "domain",
        "packages": (),
        "modules": (),
        "configs": (),
        "terms": ("saas", "subscription", "multi-tenant"),
    },
}


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str

    @property
    def weight(self) -> float:
        return WEIGHTS.get(self.kind, 0.0)


@dataclass
class TechnologySignal:
    technology: str
    category: str
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        # One occurrence of each kind, so repeating a word in prose cannot fake a dependency.
        strongest_per_kind = {evidence.kind: evidence.weight for evidence in self.evidence}
        return round(min(1.0, sum(strongest_per_kind.values())), 4)

    @property
    def classification(self) -> str:
        return "used" if self.confidence >= USED_THRESHOLD else "mentioned"

    def as_dict(self) -> dict[str, Any]:
        return {
            "technology": self.technology,
            "category": self.category,
            "classification": self.classification,
            "confidence": self.confidence,
            "sources": sorted({evidence.source for evidence in self.evidence}),
            "evidenceKinds": sorted({evidence.kind for evidence in self.evidence}),
        }


def contributes_signal(relative_path: str) -> bool:
    """Whether a file may contribute project-technology evidence at all."""
    # removeprefix, not lstrip: lstrip("./") would strip the leading dot of ".forge" too.
    normalized = relative_path.replace("\\", "/").removeprefix("./")
    posix = PurePosixPath(normalized).as_posix()
    return not any(
        posix == prefix or posix.startswith(f"{prefix}/") for prefix in SIGNAL_EXCLUDED_PREFIXES
    )


def collect_signals(
    root: Path,
    *,
    documents: list[tuple[str, str]],
    readme_relative: str | None,
) -> list[TechnologySignal]:
    """Build weighted technology signals from manifests, imports, configs, and prose.

    `documents` is a list of (relative posix path, text) already read by the scanner under its
    own size and sensitivity limits. Nothing here reads a file the scanner would refuse.
    """
    signals: dict[str, TechnologySignal] = {
        name: TechnologySignal(technology=name, category=str(spec["category"]))
        for name, spec in TECHNOLOGIES.items()
    }

    declared = _declared_dependencies(root)
    imported = _imported_modules(root)
    project_name = root.name.casefold()

    for name, spec in TECHNOLOGIES.items():
        signal = signals[name]
        for package in spec["packages"]:
            if package.casefold() in declared:
                signal.evidence.append(Evidence("manifest", f"dependency:{package}"))
                break
        for module in spec["modules"]:
            if module.casefold() in imported:
                signal.evidence.append(Evidence("import", f"import:{module}"))
                break
        for config in spec["configs"]:
            candidate = root / config
            if candidate.exists() and contributes_signal(config):
                signal.evidence.append(Evidence("config", config))
                break
        if any(term in project_name for term in spec["terms"]):
            signal.evidence.append(Evidence("project-name", root.name))

    for relative, text in documents:
        if not contributes_signal(relative):
            continue
        corpus = text.casefold()
        kind = "readme" if relative == readme_relative else "prose"
        for name, spec in TECHNOLOGIES.items():
            if any(term in corpus for term in spec["terms"]):
                signals[name].evidence.append(Evidence(kind, relative))

    return [signal for signal in signals.values() if signal.evidence]


def used(signals: Iterable[TechnologySignal], category: str) -> list[str]:
    """Only high-confidence signals are exposed as project facts."""
    return sorted(
        signal.technology
        for signal in signals
        if signal.category == category and signal.classification == "used"
    )


def mentioned(signals: Iterable[TechnologySignal]) -> list[str]:
    return sorted(signal.technology for signal in signals if signal.classification == "mentioned")


def _declared_dependencies(root: Path) -> set[str]:
    names: set[str] = set()
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            for group_name in ("dependencies", "devDependencies", "peerDependencies"):
                group = data.get(group_name)
                if isinstance(group, dict):
                    names.update(str(key).casefold() for key in group)

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        names.update(_requirement_names(_read(pyproject)))

    for requirements in sorted(root.glob("requirements*.txt")):
        names.update(_requirement_names(_read(requirements)))

    go_mod = root / "go.mod"
    if go_mod.is_file():
        for line in _read(go_mod).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(("module ", "go ", "require (", ")", "//")):
                names.add(stripped.split()[0].casefold())

    cargo = root / "Cargo.toml"
    if cargo.is_file():
        names.update(_requirement_names(_read(cargo)))
    return names


REQUIREMENT_NAME = re.compile(r'^([A-Za-z0-9_.\-@/]+)')


def _requirement_names(text: str) -> set[str]:
    """Extract dependency names from requirements.txt, pyproject.toml, and Cargo.toml.

    Handles three shapes: a bare `fastapi>=1` line, a quoted entry inside an inline array
    such as `dependencies = ["fastapi>=1"]`, and a TOML table key such as `fastapi = "1.0"`.
    """
    names: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip().strip(",")
        if not line or line.startswith("#"):
            continue
        # Every quoted string on the line is a dependency candidate. This covers inline arrays,
        # which a line-anchored match would otherwise read as the array's own key.
        for quoted in re.findall(r'["\']([^"\']+)["\']', line):
            match = REQUIREMENT_NAME.match(quoted.strip())
            if match:
                names.add(match.group(1).casefold())
        key = re.match(r'^([A-Za-z0-9_.\-]+)\s*=\s*["\'{]', line)
        if key:
            names.add(key.group(1).casefold())
        bare = re.match(r'^([A-Za-z0-9_.\-@/]+)\s*(?:[<>=!~]=?|\[)', line)
        if bare:
            names.add(bare.group(1).casefold())
        if re.fullmatch(r"[A-Za-z0-9_.\-@/]+", line):
            names.add(line.casefold())
    return names


def _imported_modules(root: Path) -> set[str]:
    modules: set[str] = set()
    scanned = 0
    for path in sorted(root.rglob("*")):
        if scanned >= MAX_SOURCE_FILES:
            break
        if not path.is_file() or path.suffix.casefold() not in SOURCE_SUFFIXES:
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if not contributes_signal(relative):
            continue
        try:
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
        except OSError:
            continue
        text = _read(path)
        if not text:
            continue
        scanned += 1
        for first, second in PYTHON_IMPORT.findall(text):
            module = (first or second).split(".")[0].casefold()
            if module:
                modules.add(module)
        for specifier in JS_IMPORT.findall(text):
            if specifier.startswith("."):
                continue
            parts = specifier.split("/")
            modules.add(specifier.casefold())
            modules.add(("/".join(parts[:2]) if specifier.startswith("@") else parts[0]).casefold())
    return modules


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
