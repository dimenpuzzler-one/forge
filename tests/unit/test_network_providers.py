"""Network provider tests.

No live API call is made. Each test replaces the provider's `_post` seam, so request shape,
response parsing, and failure handling are verified without a key. What these tests cannot
prove is that a real endpoint accepts the request; that needs a key and a live run.
"""

import json
import os
import unittest
import urllib.error
from unittest import mock

from forge_core.errors import ValidationError
from forge_planner.provider import (
    AnthropicProvider,
    OpenAIProvider,
    PlanRequest,
    ProviderError,
    SkillCandidate,
    post_json,
    resolve_provider,
)

VALID_PLAN = json.dumps(
    {
        "taskType": ["visual-design"],
        "risk": "low",
        "roles": ["design"],
        "selected": [{"id": "a/b/c", "role": "design", "reason": "fits the goal", "confidence": 0.8}],
        "excluded": [{"id": "a/b/d", "reason": "not needed"}],
        "verificationPlan": ["run the suite"],
        "humanApprovalRequired": [],
    }
)

REQUEST = PlanRequest(
    goal="redesign the landing page",
    project_context={"name": "demo", "stack": ["react"], "languages": ["typescript"]},
    candidates=[SkillCandidate("a/b/c", "CRO", "a/b", "conversion work")],
)


class OpenAIProviderTests(unittest.TestCase):
    def _provider(self, **kwargs) -> OpenAIProvider:
        return OpenAIProvider(api_key="test-key", **kwargs)

    def test_request_shape_targets_chat_completions_with_json_mode(self) -> None:
        provider = self._provider(model="gpt-5.6-luna")
        seen: dict = {}

        def fake_post(payload):
            seen.update(payload)
            return {"choices": [{"message": {"content": VALID_PLAN}}]}

        provider._post = fake_post
        proposal = provider.propose(REQUEST)

        self.assertEqual("https://api.openai.com/v1/chat/completions", provider.endpoint)
        self.assertEqual("gpt-5.6-luna", seen["model"])
        self.assertEqual({"type": "json_object"}, seen["response_format"])
        self.assertIn("max_completion_tokens", seen)
        self.assertNotIn("max_tokens", seen, "reasoning-tier models reject max_tokens")
        self.assertEqual(["system", "user"], [message["role"] for message in seen["messages"]])
        self.assertEqual(["a/b/c"], [item.skill_id for item in proposal.selected])

    def test_skill_file_contents_are_never_sent(self) -> None:
        provider = self._provider()
        seen: dict = {}

        def fake_post(payload):
            seen.update(payload)
            return {"choices": [{"message": {"content": VALID_PLAN}}]}

        provider._post = fake_post
        provider.propose(
            PlanRequest(
                goal="g",
                project_context={"name": "demo"},
                candidates=[SkillCandidate("a/b/c", "N", "a/b", "just a description")],
            )
        )

        body = json.dumps(seen)
        self.assertIn("just a description", body)
        self.assertNotIn("SKILL.md", body)

    def test_json_mode_can_be_disabled_for_incompatible_gateways(self) -> None:
        provider = self._provider(json_mode=False)
        seen: dict = {}
        provider._post = lambda payload: (seen.update(payload), {"choices": [{"message": {"content": VALID_PLAN}}]})[1]
        provider.propose(REQUEST)

        self.assertNotIn("response_format", seen)

    def test_base_url_override_supports_compatible_gateways(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_BASE_URL": "https://gateway.example/v1/"}, clear=False):
            provider = OpenAIProvider(api_key="k")
        self.assertEqual("https://gateway.example/v1/chat/completions", provider.endpoint)

        explicit = OpenAIProvider(api_key="k", base_url="https://other.example/v1")
        self.assertEqual("https://other.example/v1/chat/completions", explicit.endpoint)

    def test_model_resolution_prefers_argument_then_env_then_default(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "from-env"}, clear=False):
            self.assertEqual("explicit", OpenAIProvider(api_key="k", model="explicit").model)
            self.assertEqual("from-env", OpenAIProvider(api_key="k").model)
        environment = {key: value for key, value in os.environ.items() if key != "OPENAI_MODEL"}
        with mock.patch.dict(os.environ, environment, clear=True):
            self.assertEqual("gpt-5.6-luna", OpenAIProvider(api_key="k").model)

    def test_missing_key_names_the_offline_escape_hatch(self) -> None:
        environment = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(ProviderError) as caught:
                OpenAIProvider()
        self.assertIn("OPENAI_API_KEY", str(caught.exception))
        self.assertIn("--provider stub", str(caught.exception))

    def test_empty_choice_reports_finish_reason(self) -> None:
        provider = self._provider()
        provider._post = lambda payload: {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}

        with self.assertRaises(ProviderError) as caught:
            provider.propose(REQUEST)
        self.assertIn("length", str(caught.exception))

    def test_missing_choices_is_an_actionable_error(self) -> None:
        provider = self._provider()
        provider._post = lambda payload: {"error": {"message": "nope"}}

        with self.assertRaises(ProviderError):
            provider.propose(REQUEST)


class AnthropicProviderTests(unittest.TestCase):
    def test_request_shape_and_text_block_extraction(self) -> None:
        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-5")
        seen: dict = {}

        def fake_post(payload):
            seen.update(payload)
            return {"content": [{"type": "thinking", "text": "ignored"}, {"type": "text", "text": VALID_PLAN}]}

        provider._post = fake_post
        proposal = provider.propose(REQUEST)

        self.assertEqual("claude-sonnet-5", seen["model"])
        self.assertIn("system", seen)
        self.assertEqual(["a/b/c"], [item.skill_id for item in proposal.selected])

    def test_no_text_block_is_an_actionable_error(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        provider._post = lambda payload: {"content": [{"type": "thinking", "text": "only thinking"}]}

        with self.assertRaises(ProviderError):
            provider.propose(REQUEST)


class HttpErrorTranslationTests(unittest.TestCase):
    def test_http_400_includes_the_compatibility_hint(self) -> None:
        error = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
        error.read = lambda: b'{"error":"unknown parameter max_completion_tokens"}'
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                post_json(
                    "https://x/v1/chat/completions",
                    headers={},
                    payload={},
                    timeout=1.0,
                    label="OpenAI API",
                    hint="try json_mode=False",
                )
        message = str(caught.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("try json_mode=False", message)

    def test_non_400_errors_omit_the_hint(self) -> None:
        error = urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
        error.read = lambda: b"bad key"
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                post_json("https://x", headers={}, payload={}, timeout=1.0, label="OpenAI API", hint="hint-text")
        self.assertIn("HTTP 401", str(caught.exception))
        self.assertNotIn("hint-text", str(caught.exception))

    def test_unreachable_endpoint_is_translated(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with self.assertRaises(ProviderError) as caught:
                post_json("https://x", headers={}, payload={}, timeout=1.0, label="OpenAI API")
        self.assertIn("Could not reach", str(caught.exception))


class ProviderResolutionTests(unittest.TestCase):
    def test_openai_is_registered(self) -> None:
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=False):
            provider = resolve_provider("openai", model="gpt-5.6-luna")
        self.assertIsInstance(provider, OpenAIProvider)
        self.assertEqual("gpt-5.6-luna", provider.model)

    def test_a_model_name_used_as_a_provider_name_says_so(self) -> None:
        with self.assertRaises(ValidationError) as caught:
            resolve_provider("gpt-5.6-luna")
        message = str(caught.exception)
        self.assertIn("stub, anthropic, openai", message)
        self.assertIn("A model name is not a provider name", message)


if __name__ == "__main__":
    unittest.main()
