"""Offline tests for second-credential failover.

No vendor, no network, no key. Everything failover decides — whether an error is
about the credential or the request, which key to try next, which key to prefer
afterwards — is decided before any SDK is involved, so it is all testable here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm import factory, failover
from llm.base import ChatMessage, ChatModel, ModelError, StructuredModel
from llm.failover import FailoverStructuredModel, looks_like_a_key_failure


@pytest.fixture(autouse=True)
def _forget_which_key_worked():
    """Stickiness is process-wide, so it would leak between tests."""
    failover.reset_preferences()
    yield
    failover.reset_preferences()


class _CountingModel(StructuredModel):
    """Raises what it is told to, and counts how often it was asked."""

    def __init__(self, label: str, raises: Exception | None = None) -> None:
        super().__init__("fake-model-1", 0.35)
        self.label = label
        self.calls = 0
        self._raises = raises

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_json(self, *, system: str, prompt: str, schema: dict) -> dict[str, Any]:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return {"answered_by": self.label}


def _wrapped(*models: _CountingModel) -> FailoverStructuredModel:
    return FailoverStructuredModel("gemini", list(models))


async def _ask(model: StructuredModel) -> dict[str, Any]:
    return await model.generate_json(system="s", prompt="p", schema={})


# ---------------------------------------------------------------------------
# Classification — the decision that keeps this from being a blind retry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "gemini call failed: 429 RESOURCE_EXHAUSTED. Quota exceeded for quota metric",
        "gemini call failed: 403 PERMISSION_DENIED",
        "gemini call failed: 400 API key not valid. Please pass a valid API key.",
        "gemini call failed: API_KEY_INVALID",
        "gemini call failed: Rate limit reached for requests",
        "openai call failed: 401 Unauthenticated",
        "gemini call failed: your api key expired on 2026-01-01",
    ],
)
def test_a_key_shaped_failure_is_recognised(message):
    assert looks_like_a_key_failure(ModelError(message))


@pytest.mark.parametrize(
    "message",
    [
        # The exact shape that must never fail over: the request is wrong, and
        # it will be just as wrong on the second key.
        "gemini call failed: 400 INVALID_ARGUMENT: request contains an invalid argument",
        "model returned invalid JSON: Expecting value: line 1 column 1",
        "model returned an empty reply",
        "gemini call failed: 500 INTERNAL",
        "gemini call failed: 503 UNAVAILABLE: model is overloaded",
    ],
)
def test_a_request_shaped_failure_is_not(message):
    assert not looks_like_a_key_failure(ModelError(message))


def test_the_word_rate_alone_does_not_trigger_a_failover():
    """`generate_content` contains "rate".

    A naive substring match on it classifies *every* Gemini error as key-shaped,
    which would fail over on malformed requests too — the one thing this must
    not do.
    """
    assert not looks_like_a_key_failure(
        ModelError("gemini call failed: generate_content() got an unexpected keyword argument")
    )


def test_a_status_code_on_the_wrapped_vendor_error_is_enough():
    """Classification does not depend on the vendor phrasing its own message."""

    class _VendorError(Exception):
        code = 429

    wrapped = ModelError("gemini call failed: something terse")
    try:
        raise wrapped from _VendorError("terse")
    except ModelError as exc:
        assert looks_like_a_key_failure(exc)


# ---------------------------------------------------------------------------
# Failover behaviour
# ---------------------------------------------------------------------------


async def test_a_rate_limited_primary_falls_over_to_the_second_key():
    primary = _CountingModel("key1", ModelError("gemini call failed: 429 RESOURCE_EXHAUSTED"))
    fallback = _CountingModel("key2")

    assert await _ask(_wrapped(primary, fallback)) == {"answered_by": "key2"}
    assert (primary.calls, fallback.calls) == (1, 1)


async def test_the_next_call_goes_straight_to_the_key_that_worked():
    """A dead primary is paid for once per process, not once per call."""
    primary = _CountingModel("key1", ModelError("gemini call failed: 429 RESOURCE_EXHAUSTED"))
    fallback = _CountingModel("key2")
    model = _wrapped(primary, fallback)

    await _ask(model)
    await _ask(model)
    await _ask(model)

    assert primary.calls == 1, "the dead key was retried after it had already failed"
    assert fallback.calls == 3


async def test_stickiness_survives_a_rebuild():
    """A rebuild starts where the last one left off.

    `build_model` is called per agent, so per-instance memory would forget the
    switch immediately.
    """
    first_primary = _CountingModel("key1", ModelError("gemini call failed: 429 quota exceeded"))
    await _ask(_wrapped(first_primary, _CountingModel("key2")))

    second_primary = _CountingModel("key1")
    second_fallback = _CountingModel("key2")
    assert await _ask(_wrapped(second_primary, second_fallback)) == {"answered_by": "key2"}
    assert second_primary.calls == 0


async def test_a_non_key_error_propagates_and_never_touches_the_second_key():
    """A malformed request fails identically on every key.

    Running it twice doubles the latency and the bill to reach the same
    exception.
    """
    primary = _CountingModel("key1", ModelError("model returned invalid JSON: line 1"))
    fallback = _CountingModel("key2")

    with pytest.raises(ModelError, match="invalid JSON"):
        await _ask(_wrapped(primary, fallback))
    assert fallback.calls == 0


async def test_the_last_keys_failure_is_raised_unchanged():
    """No key left to try.

    The caller sees the vendor's own `ModelError`, because the port's contract
    says failures arrive as `ModelError`.
    """
    primary = _CountingModel("key1", ModelError("gemini call failed: 429 first"))
    fallback = _CountingModel("key2", ModelError("gemini call failed: 429 second"))

    with pytest.raises(ModelError, match="429 second"):
        await _ask(_wrapped(primary, fallback))
    assert (primary.calls, fallback.calls) == (1, 1)


async def test_the_wrapper_reports_the_inner_models_identity():
    """Nothing downstream should be able to tell it is talking to a wrapper."""
    model = _wrapped(_CountingModel("key1"), _CountingModel("key2"))
    assert model.provider == "gemini"
    assert model.model_id == "fake-model-1"
    assert model.temperature == 0.35


# ---------------------------------------------------------------------------
# The factory — one key builds no wrapper at all
# ---------------------------------------------------------------------------


class _FakeChat(ChatModel):
    def __init__(self, model_id: str, temperature: float, api_key: str) -> None:
        super().__init__(model_id, temperature)
        self.api_key = api_key

    @property
    def provider(self) -> str:
        return "fake"

    async def generate_text(self, *, system: str, messages: list[ChatMessage]) -> str:
        return "ok"


@pytest.fixture
def _fake_gemini_chat(monkeypatch):
    monkeypatch.setitem(factory.CHAT_PROVIDERS, "gemini", _FakeChat)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "primary")
    monkeypatch.delenv("SESSION_PROVIDER", raising=False)
    monkeypatch.delenv("SESSION_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)


def test_a_single_key_build_returns_the_bare_adapter(monkeypatch, _fake_gemini_chat):
    monkeypatch.delenv("GEMINI_API_KEY2", raising=False)
    model = factory.build_chat_model("session", 0.8)
    assert isinstance(model, _FakeChat)
    assert model.api_key == "primary"


def test_a_second_key_builds_one_adapter_per_key_in_order(monkeypatch, _fake_gemini_chat):
    monkeypatch.setenv("GEMINI_API_KEY2", "secondary")
    model = factory.build_chat_model("session", 0.8)
    assert isinstance(model, failover.FailoverChatModel)
    assert [inner.api_key for inner in model._instances] == ["primary", "secondary"]
    assert model.provider == "gemini"


def test_a_blank_second_key_is_not_a_key(monkeypatch, _fake_gemini_chat):
    """A declared-but-blank variable is not a key.

    An env file carrying `GEMINI_API_KEY2=` must not build a wrapper around an
    empty credential that would fail every failover.
    """
    monkeypatch.setenv("GEMINI_API_KEY2", "   ")
    assert isinstance(factory.build_chat_model("session", 0.8), _FakeChat)


def test_the_fallback_key_alone_is_not_a_configuration(monkeypatch):
    """A fallback key does not configure a provider.

    `resolve_provider` decides whether a provider exists and reads only the
    primary, so a deployment holding key2 and nothing else has no Gemini.
    """
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY2", "secondary")
    with pytest.raises(ModelError, match="no provider credentials"):
        factory.resolve_provider("session")
    assert factory.realtime_providers_available() == []


def test_only_gemini_declares_a_fallback_today():
    """One table, one row per provider that has a second key.

    Adding a row is the whole cost of extending this; nothing branches on the
    provider name.
    """
    assert set(factory.FALLBACK_API_KEY_VARS) <= set(factory.API_KEY_VARS)
    assert factory.FALLBACK_API_KEY_VARS["gemini"] == ("GEMINI_API_KEY2",)


@pytest.mark.parametrize(
    "message",
    [
        # The vendor sometimes flattens to a bare status with no status name.
        "gemini call failed: 429",
        "openai call failed: 403",
    ],
)
def test_a_bare_status_number_still_classifies(message):
    assert looks_like_a_key_failure(ModelError(message))


@pytest.mark.parametrize("message", ["request 4291 failed", "call id 140329 failed"])
def test_a_status_number_inside_a_longer_run_of_digits_does_not(message):
    """A request id must not masquerade as a 429."""
    assert not looks_like_a_key_failure(ModelError(message))
