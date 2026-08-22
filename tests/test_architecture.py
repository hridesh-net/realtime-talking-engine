"""Executable SOLID and layering checks (BRD NFR-003).

Architecture rules rot silently unless something fails when they are broken.
Each test below names the principle it defends and fails with the specific
violation, so the fix is obvious from the output alone.

Offline — no model calls, no database, no network.
"""

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

import pytest

from candidate_agent import archetypes as catalog
from candidate_agent.agent import VirtualCandidateAgent
from candidate_agent.archetypes import Archetype, ScorecardSignal
from candidate_agent.session import CandidateSessionAgent
from control_plane import ports
from control_plane.repository import InterviewRepository
from expectation_agent.agent import InterviewExpectationAgent
from llm import factory
from llm.base import ChatModel, RealtimeBroker, StructuredModel
from llm.gemini import GeminiChatModel, GeminiModel
from llm.openai_model import OpenAIChatModel, OpenAIModel
from llm.openai_realtime import OpenAIRealtimeBroker

ROOT = Path(__file__).resolve().parent.parent

#: Every first-party package, in dependency order.
PACKAGES = ["llm", "expectation_agent", "candidate_agent", "control_plane"]

#: package -> packages it is allowed to import from.
#: Enforces one direction: adapters depend on domain, never the reverse.
ALLOWED_IMPORTS: dict[str, set[str]] = {
    "llm": set(),
    "expectation_agent": {"llm"},
    "candidate_agent": {"llm"},
    "control_plane": {"llm", "expectation_agent", "candidate_agent"},
}

#: Vendor SDKs may only be imported inside the llm package.
VENDOR_MODULES = {"google", "openai", "google.genai"}

AGENTS = [InterviewExpectationAgent, VirtualCandidateAgent, CandidateSessionAgent]
BACKENDS = [GeminiModel, OpenAIModel]
CHAT_BACKENDS = [GeminiChatModel, OpenAIChatModel]
REALTIME_BACKENDS = [OpenAIRealtimeBroker]


def _modules(package: str) -> list[Path]:
    return sorted(p for p in (ROOT / package).rglob("*.py") if "__pycache__" not in p.parts)


def _imported_roots(path: Path) -> set[str]:
    """Top-level module names imported by a source file."""
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


ALL_MODULES = [(pkg, path) for pkg in PACKAGES for path in _modules(pkg)]
MODULE_IDS = [str(p.relative_to(ROOT)) for _, p in ALL_MODULES]


# ---------------------------------------------------------------------------
# Dependency inversion — depend on abstractions, not concretions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("pkg", "path"), ALL_MODULES, ids=MODULE_IDS)
def test_dip_vendor_sdks_only_inside_llm(pkg: str, path: Path) -> None:
    """Only the llm package may touch a provider SDK."""
    if pkg == "llm":
        return
    leaked = _imported_roots(path) & VENDOR_MODULES
    assert not leaked, (
        f"{path.relative_to(ROOT)} imports {sorted(leaked)}; provider SDKs belong "
        f"behind llm.base.StructuredModel"
    )


@pytest.mark.parametrize("agent_cls", AGENTS, ids=lambda c: c.__name__)
def test_dip_agents_accept_an_injected_model(agent_cls: type) -> None:
    """An agent must be constructible with any StructuredModel."""
    params = inspect.signature(agent_cls.__init__).parameters
    assert "model" in params, f"{agent_cls.__name__} takes no injectable model"
    assert params["model"].default is None, "the injected model must be optional"


@pytest.mark.parametrize("agent_cls", AGENTS, ids=lambda c: c.__name__)
def test_dip_agents_do_not_read_provider_credentials(agent_cls: type) -> None:
    """Credential handling lives in llm.factory, not in the agents."""
    source = inspect.getsource(sys.modules[agent_cls.__module__])
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        assert var not in source, (
            f"{agent_cls.__module__} reads {var}; provider credentials belong in llm.factory"
        )


def test_dip_handlers_depend_on_ports_not_the_sqlite_adapter() -> None:
    """Route handlers are typed against protocols so storage can be swapped."""
    source = (ROOT / "control_plane" / "api.py").read_text()
    assert "repo: InterviewRepository" not in source, (
        "a handler is typed against the SQLite adapter; use a port from control_plane.ports"
    )


# ---------------------------------------------------------------------------
# Interface segregation — no consumer depends on methods it does not use
# ---------------------------------------------------------------------------

NARROW_PORTS = [
    ports.InterviewStore,
    ports.ExpectationStore,
    ports.CandidateStore,
    ports.SessionStore,
]

COMPOSITION_PORTS = [
    ports.ExpectationWorkflowStore,
    ports.EnrollmentStore,
    ports.SessionWorkflowStore,
    ports.TurnWorkflowStore,
]


@pytest.mark.parametrize("port", NARROW_PORTS, ids=lambda p: p.__name__)
def test_isp_ports_stay_small(port: type) -> None:
    """A port that grows past a handful of methods has stopped being segregated."""
    methods = [m for m in vars(port) if not m.startswith("_")]
    assert len(methods) <= 5, f"{port.__name__} has {len(methods)} methods: {sorted(methods)}"


@pytest.mark.parametrize("port", NARROW_PORTS, ids=lambda p: p.__name__)
def test_isp_ports_do_not_overlap(port: type) -> None:
    """Each storage concern belongs to exactly one narrow port."""
    own = {m for m in vars(port) if not m.startswith("_")}
    for other in NARROW_PORTS:
        if other is port:
            continue
        shared = own & {m for m in vars(other) if not m.startswith("_")}
        assert not shared, f"{port.__name__} and {other.__name__} both declare {sorted(shared)}"


@pytest.mark.parametrize(
    "port",
    [*NARROW_PORTS, *COMPOSITION_PORTS],
    ids=lambda p: p.__name__,
)
def test_isp_sqlite_adapter_satisfies_every_port(port: type) -> None:
    """The adapter implements the ports structurally, without inheriting them."""
    assert isinstance(InterviewRepository(_memory_conn()), port)
    assert port not in InterviewRepository.__mro__, (
        f"{port.__name__} should be satisfied structurally, not by inheritance"
    )


def _memory_conn():
    from control_plane.database import init_db

    return init_db(":memory:")


# ---------------------------------------------------------------------------
# Liskov substitution — implementations are interchangeable
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda c: c.__name__)
def test_lsp_backends_share_the_base_signature(backend: type) -> None:
    """Any StructuredModel can replace any other without changing call sites."""
    assert issubclass(backend, StructuredModel)
    base = inspect.signature(StructuredModel.generate_json)
    impl = inspect.signature(backend.generate_json)
    assert impl.parameters == base.parameters, (
        f"{backend.__name__}.generate_json signature diverges from the base class"
    )
    assert impl.return_annotation == base.return_annotation


@pytest.mark.parametrize("backend", BACKENDS, ids=lambda c: c.__name__)
def test_lsp_backends_implement_the_whole_contract(backend: type) -> None:
    """No implementation may leave an abstract method unimplemented."""
    assert not getattr(backend, "__abstractmethods__", set()), (
        f"{backend.__name__} is still abstract"
    )
    assert isinstance(backend.provider, property)


@pytest.mark.parametrize("backend", CHAT_BACKENDS, ids=lambda c: c.__name__)
def test_lsp_chat_backends_share_the_base_signature(backend: type) -> None:
    """Any ChatModel can replace any other without changing call sites."""
    assert issubclass(backend, ChatModel)
    base = inspect.signature(ChatModel.generate_text)
    impl = inspect.signature(backend.generate_text)
    assert impl.parameters == base.parameters, (
        f"{backend.__name__}.generate_text signature diverges from the base class"
    )
    assert impl.return_annotation == base.return_annotation


@pytest.mark.parametrize("backend", [*BACKENDS, *CHAT_BACKENDS], ids=lambda c: c.__name__)
def test_lsp_every_backend_is_constructed_identically(backend: type) -> None:
    """The factory constructs every provider, on either port, through one call shape."""
    params = list(inspect.signature(backend.__init__).parameters)
    assert params == ["self", "model_id", "temperature", "api_key"], (
        f"{backend.__name__} cannot be built by llm.factory's uniform constructor call"
    )


def test_isp_the_two_model_ports_stay_separate() -> None:
    """A chat model must not drag a JSON-schema method behind it, or vice versa."""
    assert not issubclass(ChatModel, StructuredModel)
    assert not issubclass(StructuredModel, ChatModel)
    assert "generate_json" not in dir(ChatModel)
    assert "generate_text" not in dir(StructuredModel)


def test_isp_the_realtime_broker_is_not_a_model_port() -> None:
    """Voice is a credential-minting job, not a third way to call a model."""
    assert not issubclass(RealtimeBroker, StructuredModel)
    assert not issubclass(RealtimeBroker, ChatModel)
    for leaked in ("generate_json", "generate_text"):
        assert leaked not in dir(RealtimeBroker)


@pytest.mark.parametrize("backend", REALTIME_BACKENDS, ids=lambda c: c.__name__)
def test_lsp_realtime_backends_share_the_base_signature(backend: type) -> None:
    """Any RealtimeBroker can replace any other without changing call sites."""
    assert issubclass(backend, RealtimeBroker)
    base = inspect.signature(RealtimeBroker.mint)
    impl = inspect.signature(backend.mint)
    assert impl.parameters == base.parameters, (
        f"{backend.__name__}.mint signature diverges from the base class"
    )
    assert not getattr(backend, "__abstractmethods__", set()), f"{backend.__name__} is abstract"
    assert list(inspect.signature(backend.__init__).parameters) == [
        "self",
        "model_id",
        "api_key",
    ], f"{backend.__name__} cannot be built by llm.factory's uniform constructor call"


@pytest.mark.parametrize("backend", REALTIME_BACKENDS, ids=lambda c: c.__name__)
def test_realtime_backends_advertise_stable_voices(backend: type) -> None:
    """Voice choice indexes into this tuple, so its order is part of the contract."""
    assert isinstance(backend.voices, property)
    voices = backend.voices.fget(backend.__new__(backend))  # type: ignore[misc]
    assert isinstance(voices, tuple) and voices, f"{backend.__name__} advertises no voices"
    assert len(set(voices)) == len(voices), "duplicate voice names shift persona assignments"


@pytest.mark.parametrize("a", list(catalog.ARCHETYPES.values()), ids=lambda a: a.key)
def test_lsp_every_archetype_honours_the_same_contract(a: Archetype) -> None:
    """Archetypes are substitutable: the agent handles any of them identically."""
    assert set(a.traits) == set(catalog.TRAIT_NAMES)
    assert a.verdict in catalog.VERDICTS
    assert round(sum(s.weight for s in a.must_discover), 4) == 1.0
    assert set(a.speech) == {
        "pace",
        "verbosity",
        "filler_frequency",
        "hesitation_frequency",
        "formality",
        "interrupts_interviewer",
        "tone",
    }
    assert set(a.answer_policy) == {
        "default_answer_depth",
        "on_unknown_question",
        "on_pressure",
        "on_silence",
    }


# ---------------------------------------------------------------------------
# Open/closed — extend by adding, not by editing
# ---------------------------------------------------------------------------


def test_ocp_new_archetype_needs_no_agent_change() -> None:
    """Registering an archetype flows through the agent with no edits to it."""
    key = "ocp_probe_archetype"
    probe = Archetype(
        key=key,
        label="OCP probe",
        description="Temporary archetype registered by the architecture test.",
        verdict="borderline",
        interviewer_challenge="none",
        traits=dict.fromkeys(catalog.TRAIT_NAMES, (5, 5)),
        knowledge_band=(4, 6),
        speech=catalog.get("evasive").speech,
        answer_policy=catalog.get("evasive").answer_policy,
        must_discover=[ScorecardSignal(id="only", signal="s", weight=1.0, how_to_surface="h")],
        interviewer_failure_modes=["none"],
        session_beats=["does the probe thing"],
        stresses={"structure": 2},
    )
    catalog.ARCHETYPES[key] = probe
    try:
        assert catalog.get(key) is probe
        row = next(r for r in catalog.catalog() if r["key"] == key)
        # The picker's two panels come straight off the catalog row, so a new
        # archetype must arrive with them rather than needing a UI edit.
        assert row["session_beats"] == ["does the probe thing"]
        assert row["stresses"] == {"structure": 2}
        # The agent's deterministic half handles it without knowing it exists.
        from candidate_agent.agent import derive_traits

        assert all(v == 5 for v in derive_traits(probe, "seed").values())
        entries = VirtualCandidateAgent._build_knowledge_map({}, probe, ["Go"])
        assert [e.skill for e in entries] == ["Go"]
        assert VirtualCandidateAgent._build_scorecard({}, probe).expected_verdict == "borderline"
    finally:
        del catalog.ARCHETYPES[key]


def test_ocp_realtime_table_is_a_documented_subset() -> None:
    """Realtime voice is optional per provider — but never a provider we do not know.

    Unlike the text tables, ``REALTIME_PROVIDERS`` is deliberately partial: not
    every provider offers speech-to-speech on comparable terms, and shipping a
    Voice button that cannot work is worse than not offering one. What must hold
    is that it names only known providers, and that each has a realtime model id.
    """
    assert set(factory.REALTIME_PROVIDERS) <= set(factory.PROVIDERS), (
        "REALTIME_PROVIDERS names a provider missing from PROVIDERS"
    )
    assert set(factory.REALTIME_PROVIDERS) == set(factory.DEFAULT_REALTIME_MODEL_IDS), (
        "every realtime provider needs a realtime model id; the text model id will not work"
    )


def test_ocp_new_provider_needs_no_agent_change() -> None:
    """Providers are registered in one table, not branched on inside agents."""
    tables = (
        factory.PROVIDERS,
        factory.CHAT_PROVIDERS,
        factory.API_KEY_VARS,
        factory.DEFAULT_MODEL_IDS,
    )
    assert len({frozenset(t) for t in tables}) == 1, (
        "provider tables are out of sync; adding a provider means adding one row to each"
    )
    for module in (*_modules("candidate_agent"), *_modules("expectation_agent")):
        source = module.read_text()
        for provider in factory.PROVIDERS:
            assert f'== "{provider}"' not in source, (
                f"{module.name} branches on the provider name; that belongs in llm.factory"
            )


# ---------------------------------------------------------------------------
# Single responsibility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pkg", ["candidate_agent", "expectation_agent"], ids=str)
def test_srp_generation_does_not_persist(pkg: str) -> None:
    """An agent generates. Storing what it generated is the caller's job."""
    for path in _modules(pkg):
        roots = _imported_roots(path)
        assert "sqlite3" not in roots, f"{path.name} talks to the database"
        assert "control_plane" not in roots, f"{path.name} imports the control plane"


def test_srp_agents_do_not_generate_each_others_documents() -> None:
    """Persona casting and expectation design stay separate services."""
    for path in _modules("candidate_agent"):
        assert "expectation_agent" not in _imported_roots(path) or path.name in {
            "agent.py",
            "prompts.py",
        }, f"{path.name} reaches into the expectation agent"
    for path in _modules("expectation_agent"):
        assert "candidate_agent" not in _imported_roots(path), (
            f"{path.name} reaches into the candidate agent"
        )


def test_srp_prompt_modules_do_not_call_models() -> None:
    """Prompt modules build strings; they never perform I/O."""
    for pkg in ("candidate_agent", "expectation_agent"):
        source = (ROOT / pkg / "prompts.py").read_text()
        for forbidden in ("generate_json", "httpx", "requests", "await "):
            assert forbidden not in source, f"{pkg}/prompts.py performs I/O ({forbidden})"


def test_srp_schema_modules_hold_no_logic() -> None:
    """Schema modules declare shape only — rules live in the rubric or catalog."""
    for pkg in ("candidate_agent", "expectation_agent"):
        tree = ast.parse((ROOT / pkg / "schema.py").read_text())
        functions = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
        assert not functions, f"{pkg}/schema.py defines logic: {functions}"


# ---------------------------------------------------------------------------
# Layering — the dependency graph points one way
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("pkg", "path"), ALL_MODULES, ids=MODULE_IDS)
def test_layering_respects_the_allowed_direction(pkg: str, path: Path) -> None:
    """No package imports a package above it in the stack."""
    allowed = ALLOWED_IMPORTS[pkg] | {pkg}
    violations = (_imported_roots(path) & set(PACKAGES)) - allowed
    assert not violations, (
        f"{path.relative_to(ROOT)} imports {sorted(violations)}; "
        f"{pkg} may only import {sorted(ALLOWED_IMPORTS[pkg]) or 'nothing first-party'}"
    )


@pytest.mark.parametrize(("pkg", "path"), ALL_MODULES, ids=MODULE_IDS)
def test_layering_uses_absolute_imports(pkg: str, path: Path) -> None:
    """Relative imports hide the dependency graph these checks rely on."""
    tree = ast.parse(path.read_text(), filename=str(path))
    relative = [
        n.module or "." for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level
    ]
    assert not relative, f"{path.relative_to(ROOT)} uses relative imports: {relative}"
