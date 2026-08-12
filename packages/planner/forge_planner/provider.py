from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from forge_core.errors import ForgeError, ValidationError
from forge_planner.roles import normalize_role, vocabulary_prompt_block

# The planner sends candidate metadata only. Skill file contents are untrusted data and are
# never forwarded to a provider during planning.
MAX_CANDIDATES_SENT = 60
MAX_DESCRIPTION_CHARS = 400
DEFAULT_TIMEOUT_SECONDS = 60.0


class ProviderError(ForgeError):
    """A planning provider failed in a way the user can act on."""


@dataclass(frozen=True)
class SkillCandidate:
    """The only Skill information a provider is allowed to see."""

    skill_id: str
    name: str
    source: str
    description: str

    def as_prompt_dict(self) -> dict[str, str]:
        description = self.description.replace("\n", " ").strip()
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = f"{description[:MAX_DESCRIPTION_CHARS - 3]}..."
        return {
            "id": self.skill_id,
            "name": self.name,
            "source": self.source,
            "description": description,
        }


@dataclass(frozen=True)
class PlanRequest:
    goal: str
    project_context: dict[str, Any]
    candidates: list[SkillCandidate]


@dataclass(frozen=True)
class SkillProposal:
    skill_id: str
    role: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class Exclusion:
    skill_id: str
    reason: str


@dataclass(frozen=True)
class PlanProposal:
    """An unverified LLM proposal. Nothing here is trusted until the policy gate runs."""

    task_type: list[str] = field(default_factory=list)
    risk: str = "medium"
    roles: list[str] = field(default_factory=list)
    selected: list[SkillProposal] = field(default_factory=list)
    excluded: list[Exclusion] = field(default_factory=list)
    verification_plan: list[str] = field(default_factory=list)
    human_approval_required: list[str] = field(default_factory=list)
    notes: str = ""


@runtime_checkable
class PlanProvider(Protocol):
    """Semantic judgment only. A provider never reads the registry and never grants permission."""

    name: str

    def propose(self, request: PlanRequest) -> PlanProposal: ...


# Assembled by concatenation rather than an f-string: the JSON schema below contains braces,
# which an f-string would try to interpret as format fields.
SYSTEM_PROMPT = """You are the planning stage of Forge, a procedural-knowledge toolkit.

You receive a user goal, a project context, and a list of candidate Skills that a
deterministic local registry already retrieved. Your job is semantic judgment only.

""" + vocabulary_prompt_block() + """

Rules you must follow:
1. Decompose the goal into task roles drawn from the vocabulary above.
2. Select Skills ONLY from the provided candidate list. Never invent a Skill id.
   Any id you emit that is not in the candidate list will be discarded.
3. Give every selection a concrete reason tied to the goal, not to popularity.
4. Explicitly exclude candidates that look plausible but are not needed, with a reason.
5. Assess task risk as low, medium, or high. Auth, payment, credentials, destructive
   data migration, and production infrastructure are high.
6. Propose a verification plan of concrete checks (commands, routes, or observations).
7. List anything that requires human validation rather than agent self-evaluation.

You do not decide trust, versions, or permissions. Forge enforces those separately.

Respond with a single JSON object and nothing else, in this exact shape:
{
  "taskType": ["string"],
  "risk": "low|medium|high",
  "roles": ["string"],
  "selected": [
    {"id": "string", "role": "string", "reason": "string", "confidence": 0.0}
  ],
  "excluded": [{"id": "string", "reason": "string"}],
  "verificationPlan": ["string"],
  "humanApprovalRequired": ["string"],
  "notes": "string"
}"""


def build_user_prompt(request: PlanRequest) -> str:
    context = {
        "name": request.project_context.get("name"),
        "languages": request.project_context.get("languages", []),
        "stack": request.project_context.get("stack", []),
        "domains": request.project_context.get("domains", []),
        "architecture": request.project_context.get("architecture", []),
        "commands": request.project_context.get("commands", {}),
    }
    candidates = [candidate.as_prompt_dict() for candidate in request.candidates[:MAX_CANDIDATES_SENT]]
    return (
        f"GOAL:\n{request.goal}\n\n"
        f"PROJECT CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        f"CANDIDATE SKILLS ({len(candidates)}):\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
    )


def parse_proposal(payload: str) -> PlanProposal:
    """Parse untrusted provider output. Malformed fields degrade, they do not crash the plan."""
    data = _extract_json_object(payload)
    selected: list[SkillProposal] = []
    for entry in _as_list(data.get("selected")):
        if not isinstance(entry, dict):
            continue
        skill_id = entry.get("id")
        if not isinstance(skill_id, str) or not skill_id.strip():
            continue
        selected.append(
            SkillProposal(
                skill_id=skill_id.strip(),
                role=normalize_role(_as_text(entry.get("role"), fallback="general")).storage_key,
                reason=_as_text(entry.get("reason"), fallback="No reason was provided by the provider."),
                confidence=_as_confidence(entry.get("confidence")),
            )
        )
    excluded: list[Exclusion] = []
    for entry in _as_list(data.get("excluded")):
        if not isinstance(entry, dict):
            continue
        skill_id = entry.get("id")
        if not isinstance(skill_id, str) or not skill_id.strip():
            continue
        excluded.append(
            Exclusion(
                skill_id=skill_id.strip(),
                reason=_as_text(entry.get("reason"), fallback="No exclusion reason was provided."),
            )
        )
    risk = _as_text(data.get("risk"), fallback="medium").casefold()
    return PlanProposal(
        task_type=_as_text_list(data.get("taskType")),
        risk=risk if risk in {"low", "medium", "high"} else "medium",
        roles=list(
            dict.fromkeys(normalize_role(role).storage_key for role in _as_text_list(data.get("roles")))
        ),
        selected=selected,
        excluded=excluded,
        verification_plan=_as_text_list(data.get("verificationPlan")),
        human_approval_required=_as_text_list(data.get("humanApprovalRequired")),
        notes=_as_text(data.get("notes"), fallback=""),
    )


class StubProvider:
    """A deterministic offline provider.

    It exists so the planner pipeline, the policy gate, and the artifact schema are
    testable and usable without a network call or an API key. It performs shallow
    lexical matching only and never claims to be a semantic judgment.
    """

    name = "stub"

    def __init__(self, *, limit: int = 6):
        self.limit = limit

    def propose(self, request: PlanRequest) -> PlanProposal:
        terms = {token for token in _tokenize(request.goal) if len(token) > 2}
        scored: list[tuple[int, int, SkillCandidate]] = []
        for index, candidate in enumerate(request.candidates):
            haystack = _tokenize(f"{candidate.name} {candidate.description} {candidate.skill_id}")
            overlap = len(terms & haystack)
            if overlap:
                scored.append((-overlap, index, candidate))
        scored.sort()
        selected = [
            SkillProposal(
                skill_id=candidate.skill_id,
                role="general",
                reason=(
                    f"Offline stub provider: {-score} goal term(s) matched this candidate's metadata. "
                    "This is lexical overlap, not semantic judgment."
                ),
                confidence=0.3,
            )
            for score, _, candidate in scored[: self.limit]
        ]
        chosen = {proposal.skill_id for proposal in selected}
        excluded = [
            Exclusion(
                skill_id=candidate.skill_id,
                reason="Offline stub provider: no goal term overlap in the candidate metadata.",
            )
            for candidate in request.candidates
            if candidate.skill_id not in chosen
        ][: self.limit]
        return PlanProposal(
            task_type=["unclassified"],
            risk="medium",
            roles=["general"],
            selected=selected,
            excluded=excluded,
            verification_plan=[
                "Run the project's declared test command.",
                "Confirm the change against the stated goal by direct observation.",
            ],
            human_approval_required=[
                "Skill relevance was not semantically judged; review the selection before executing."
            ],
            notes=(
                "Generated by the offline stub provider. Selection quality is not a Forge quality signal. "
                "Configure a real provider for semantic planning."
            ),
        )


def post_json(
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
    label: str,
    hint: str = "",
) -> dict[str, Any]:
    """One standard-library HTTP POST shared by the network providers.

    Kept as a module function with a per-provider `_post` seam so request shape, error
    handling, and response parsing are testable without a live API key.
    """
    http_request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        suffix = f" {hint}" if hint and error.code == 400 else ""
        raise ProviderError(f"{label} returned HTTP {error.code}: {detail}{suffix}") from error
    except urllib.error.URLError as error:
        raise ProviderError(f"Could not reach {label}: {error.reason}") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise ProviderError(f"{label} response was unusable: {error}") from error


class AnthropicProvider:
    """Anthropic Messages API provider using only the standard library."""

    name = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "claude-sonnet-5",
        max_tokens: int = 4096,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY, or run `forge plan --provider stub` "
                "to use the offline provider."
            )
        self._api_key = key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return post_json(
            self.endpoint,
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": self.api_version,
            },
            payload=payload,
            timeout=self.timeout,
            label="Anthropic API",
        )

    def propose(self, request: PlanRequest) -> PlanProposal:
        payload = self._post(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": build_user_prompt(request)}],
            }
        )
        text = "".join(
            str(block.get("text", ""))
            for block in payload.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text.strip():
            raise ProviderError("Anthropic API returned no text content for the planning request.")
        return parse_proposal(text)


class OpenAIProvider:
    """OpenAI Chat Completions provider using only the standard library.

    Chat Completions rather than the Responses API, because the same request shape works
    against OpenAI-compatible gateways; override `base_url` (or `OPENAI_BASE_URL`) to point
    at one. The provider still only proposes — ADR-006 governs what is admitted.
    """

    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-5.6-luna"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 4096,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        json_mode: bool = True,
    ):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError(
                "No OpenAI API key found. Set OPENAI_API_KEY, or run `forge plan --provider stub` "
                "to use the offline provider."
            )
        self._api_key = key
        self.model = model or os.environ.get("OPENAI_MODEL") or self.default_model
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or self.default_base_url).rstrip("/")
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.json_mode = json_mode

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return post_json(
            self.endpoint,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self._api_key}",
            },
            payload=payload,
            timeout=self.timeout,
            label="OpenAI API",
            hint=(
                "If the endpoint rejected `max_completion_tokens` or `response_format`, it is likely an "
                "older or non-OpenAI gateway; construct OpenAIProvider with json_mode=False, or point "
                "OPENAI_BASE_URL at a compatible endpoint."
            ),
        )

    def propose(self, request: PlanRequest) -> PlanProposal:
        payload: dict[str, Any] = {
            "model": self.model,
            # Reasoning-tier models expect max_completion_tokens; max_tokens is rejected.
            # Unverified against a live endpoint — see the HTTP 400 hint in _post.
            "max_completion_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(request)},
            ],
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = self._post(payload)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("OpenAI API returned no choices for the planning request.")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            finish = first.get("finish_reason") if isinstance(first, dict) else None
            detail = f" (finish_reason: {finish})" if finish else ""
            raise ProviderError(f"OpenAI API returned an empty planning response{detail}.")
        return parse_proposal(content)


PROVIDERS = ("stub", "anthropic", "openai")


def resolve_provider(name: str, *, model: str | None = None) -> PlanProvider:
    normalized = name.strip().casefold()
    if normalized == "stub":
        return StubProvider()
    if normalized == "anthropic":
        return AnthropicProvider(model=model) if model else AnthropicProvider()
    if normalized == "openai":
        return OpenAIProvider(model=model)
    raise ValidationError(
        f"Unknown planning provider: {name}. Available providers: {', '.join(PROVIDERS)}. "
        "A model name is not a provider name; use --provider openai --model <model>."
    )


def _extract_json_object(payload: str) -> dict[str, Any]:
    text = payload.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError("The provider response did not contain a JSON object.") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise ProviderError(f"The provider response was not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ProviderError("The provider response was valid JSON but not a JSON object.")
    return data


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_text(value: Any, *, fallback: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else fallback


def _as_text_list(value: Any) -> list[str]:
    return [item.strip() for item in _as_list(value) if isinstance(item, str) and item.strip()]


def _as_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in "".join(character if character.isalnum() else " " for character in text.casefold()).split()
        if token
    }
