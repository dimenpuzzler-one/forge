from __future__ import annotations

import re
from dataclasses import dataclass

# Historical evidence accumulates per role, so an unstable role vocabulary scatters it. The
# same goal produced six roles on one live run and seven on the next, with `conversion-audit`,
# `conversion-validation`, and `copywriting` appearing where `conversion` and `copy` would do.
# Three runs of one goal would leave evidence spread across five role names that mean two
# things.
#
# Forge therefore publishes a canonical vocabulary and asks the provider to choose from it.
# Vol.2 section 8 requires that the taxonomy not be fully closed, so anything outside the list
# is still accepted — recorded verbatim, marked custom, and kept out of aggregate evidence
# until a human promotes it.

CANONICAL_ROLES: tuple[str, ...] = (
    # product and growth
    "positioning",
    "copy",
    "conversion",
    "research",
    # interface
    "visual-design",
    "component-architecture",
    "responsive",
    "accessibility",
    "performance",
    # engineering
    "api-design",
    "data-modeling",
    "database",
    "refactoring",
    "migration",
    "infrastructure",
    "observability",
    # assurance
    "testing",
    "security",
    "auth",
    "payments",
    "compliance",
    # communication
    "documentation",
    # fallback
    "general",
)

CUSTOM_PREFIX = "custom:"
_SEPARATORS = re.compile(r"[\s_/]+")


@dataclass(frozen=True)
class Role:
    """A role as recorded: the canonical name when known, the raw text when not."""

    name: str
    raw: str
    custom: bool

    @property
    def storage_key(self) -> str:
        """The value written to the database and to plan artifacts."""
        return f"{CUSTOM_PREFIX}{self.name}" if self.custom else self.name


def normalize_role(raw: str) -> Role:
    """Map provider text onto the canonical vocabulary without guessing at meaning.

    Only mechanical normalization is applied — case, separators, surrounding whitespace. No
    synonym table: mapping `conversion-audit` onto `conversion` would be Forge inventing an
    equivalence the provider did not state, and it would hide the taxonomy drift this module
    exists to surface. Providers are given the vocabulary in the prompt instead.
    """
    text = (raw or "").strip()
    if not text:
        return Role(name="general", raw=raw or "", custom=False)
    if text.casefold().startswith(CUSTOM_PREFIX):
        text = text[len(CUSTOM_PREFIX) :].strip()
    slug = _SEPARATORS.sub("-", text.casefold()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if slug in CANONICAL_ROLES:
        return Role(name=slug, raw=raw, custom=False)
    return Role(name=slug or "general", raw=raw, custom=bool(slug))


def is_custom(storage_key: str) -> bool:
    return storage_key.startswith(CUSTOM_PREFIX)


def display(storage_key: str) -> str:
    return storage_key[len(CUSTOM_PREFIX) :] + " (custom)" if is_custom(storage_key) else storage_key


def vocabulary_prompt_block() -> str:
    """The role list as it appears in the provider system prompt."""
    listed = "\n".join(f"  - {role}" for role in CANONICAL_ROLES)
    return (
        "Assign each selected Skill one role from this vocabulary:\n"
        f"{listed}\n"
        "If none of these fits, invent a short hyphenated role name. Forge will record it and "
        "mark it as custom. Prefer a listed role whenever one applies, because roles are how "
        "Forge accumulates evidence across tasks and an ad hoc name fragments that record."
    )
