# Pivot Plan — Manager Assessment (BRD v3)

**Status:** plan for human review. No code has been changed.
**Spec:** `docs/BRD_Interviewer_Upskilling_v3.html` (authoritative).
**Target (the user's words):** *"let's make it to the point that i can conversate with any of the persona and I can take interview."*
Everything else — billing, wallet, LMS, accounts, dashboards, aggregate reporting, POC packaging — is deferred and appears nowhere in the critical path below.

---

## 0. The shape of the pivot in one paragraph

The assessed subject flips from candidate to hiring manager. The JD-driven
pipeline (job spec → skills → expectation → persona → candidate score) is
replaced by: **fixed 5-criterion rubric** (org-owned config, identical every
session) + **role-agnostic persona library** (each persona stresses one rubric
criterion) + **thin job card** (title, 2–3 lines, role family — context, never
criteria) + **live session** + **evaluation layer** (deterministic signals
counted by code, judge pass for comprehension, analytical report with quoted
evidence, **no pass/fail gate of any kind**). The repo's determinism split
survives intact — it is exactly the BRD's deterministic-signals/judge split.

---

## 1. Module-by-module verdict: survives / changes / deleted

| Module | Verdict | Why |
|---|---|---|
| `llm/` (base, factory, gemini, openai_model) | **Survives; grows one port** | `StructuredModel.generate_json` serves casting and the judge. The live session needs free-text turns, so add a `ChatModel` ABC (`generate_text(*, system, messages) -> str`) beside it, implemented in the same two vendor modules. New factory role prefixes: `SESSION`, `JUDGE`. |
| `candidate_agent/agent.py` | **Changes** | Casting stays (personas still get a name, background, voice from a seeded draft), but its inputs become job card + role family instead of JD + skills. `knowledge_map` keys become role-family talking areas (e.g. "territory management") instead of JD skills. |
| `candidate_agent/archetypes.py` | **Changes — catalog v2.0** | The machinery (trait bounds, seeded RNG, speech spec, answer policy, registration + weight validation, OCP test) is exactly what the BRD's trait bundles need. The *catalog contents* are rewritten to the 8 BRD personas (§3 below). |
| `candidate_agent/engine_contract.py` | **Survives; one addition** | The compiled system prompt, voice directives, turn policy, knowledge ceiling all carry over unchanged to both the text session and the later Go voice engine. Add the **scripted disruption** block (§3.3). Bump `ENGINE_CONTRACT_VERSION` to `v1.1`. |
| `candidate_agent/schema.py` | **Changes** | Trait axes, `SpeechProfile`, `AnswerPolicy`, `EngineContract` survive verbatim. `InterviewerScorecard`/`verdict` are **kept as persona metadata** (they give the persona internal consistency and feed the report's "development plan" section) but are **removed from all scoring paths** — the fixed rubric is the only scoring instrument. |
| `expectation_agent/` (all four files) | **RETIRED — delete the package** | Decisive answer to the big question. It exists to *generate a per-interview rubric from a JD*, which is precisely what v3 forbids: the rubric is now fixed configuration, not generated content, so there is nothing left for this agent to do. It is **not** repurposed into the evaluator: the evaluator reads a *transcript after* a session; the expectation agent authored a *plan before* one — different inputs, schema, prompts, and lifecycle. Reuse would be a rename hiding a rewrite. The only survivor is the *idea* in `rubric.py` (fixed criteria as code), which is reborn as `evaluation_agent/rubric.py` with the five BRD criteria. Delete `expectation_agent/`, its two endpoints, `interview_expectations` table, `ExpectationStore`/`ExpectationWorkflowStore` ports, `tests/test_expectation_agent.py`, and its entries in `scripts/export_schemas.py` and `okf/`. |
| `control_plane/api.py` | **Changes heavily** | Expectation endpoints go. Interview endpoints become role (job card) endpoints. New session, turn, and report endpoints (§6). |
| `control_plane/schemas.py` | **Changes** | `InterviewCreateRequest`/`InterviewResponse` replaced by `RoleCard`/`RoleResponse` (§2). Legacy `CandidatePersona`/`PersonaAttribute` deleted along with `control_plane/persona.py` (already legacy). |
| `control_plane/ports.py` | **Changes** | `InterviewStore` → `RoleStore`; expectation ports deleted; new `SessionStore`, `ReportStore`; compositions rebuilt from the narrow ports (§6). |
| `control_plane/database.py` / `repository.py` | **Changes** | New schema (§7). Pre-production: drop-and-recreate, no migration scripts. |
| `control_plane/persona.py` | **Deleted** | Marked legacy in okf already; superseded twice over. |
| `engine/` (Go) | **Survives untouched, off critical path** | Phase 0 skeleton stays parked. The text session is built to emit the *same* transcript/telemetry shape the engine's session bundle will emit, so the voice path lands later without evaluator rework (§5). |
| `ui/` | **Changes** | Console grows a persona picker, a chat session view, and a report view (§6.3). |
| `tests/test_architecture.py` | **Changes** | `PACKAGES` and `ALLOWED_IMPORTS` gain `evaluation_agent` (imports `llm` only); `expectation_agent` rows removed. The OCP archetype test survives and now proves the persona library is extensible by Atibhee's team without engineering — the BRD's economic requirement. |
| `owner_handover/` + `scripts/export_schemas.py` | **Regenerated** | Every public-model change below triggers this (CLAUDE.md rule). Expectation schemas removed; role card, session, transcript, report schemas added. |
| `okf/` | **Updated per phase** | Every phase ends with concept updates + a `okf/log.md` line (CLAUDE.md rule). |

---

## 2. The new domain model (concrete Pydantic)

All in `control_plane/schemas.py` unless noted. Every model here is public →
`scripts/export_schemas.py` + `owner_handover/` regeneration + okf update on
each change.

```python
ROLE_FAMILIES = ("sales", "marketing", "technical")   # closed list; D-4 may rename the third

class RoleCard(BaseModel):
    """POST /api/v1/roles body. Replaces the job spec entirely."""
    job_title: str
    summary: str = Field(..., description="2-3 lines. Everything the persona knows about the job.")
    role_family: str = Field(..., pattern="^(sales|marketing|technical)$")
    clarity_facts: list[ClarityFact] = Field(default_factory=list)

class ClarityFact(BaseModel):
    """One fact the manager is expected to convey. Ticks the C1 coverage checklist."""
    key: str          # e.g. "targets", "shift", "location", "growth_path", "comp_band", "next_steps"
    statement: str    # the fact itself, e.g. "Monthly target: 40 new activations"

class RoleResponse(RoleCard):
    id: str
    created_at: datetime

class SessionCreateRequest(BaseModel):
    role_id: str
    persona_key: str            # from the v2 catalog
    planned_minutes: int = Field(20, ge=5, le=45)

class Turn(BaseModel):
    index: int
    speaker: str = Field(..., pattern="^(manager|candidate)$")
    text: str
    at: datetime                # server-side timestamp — the evaluation layer's time base
    elapsed_ms: int             # since session start

class SessionResponse(BaseModel):
    id: str
    role_id: str
    persona_key: str
    candidate_id: str           # the cast persona playing this session
    status: str = Field(..., pattern="^(live|completed|abandoned)$")
    modality: str = Field("text", pattern="^(text|voice)$")   # voice arrives with the Go engine
    started_at: datetime
    ended_at: datetime | None
    turns: list[Turn]
    opening_line: str
```

In the new package `evaluation_agent/schema.py`:

```python
RUBRIC_VERSION = "v1.0"

class Criterion(BaseModel):            # evaluation_agent/rubric.py holds the five instances
    id: str                            # "clarity" | "structure" | "bias" | "experience" | "communication"
    label: str                         # "Hiring with Clarity", ...
    weight: float                      # 0.20, 0.25, 0.20, 0.20, 0.15 — loaded from rubric config,
                                       # overridable via RUBRIC_CONFIG_PATH (org-owned, never hardcoded per-session)

class SignalResult(BaseModel):
    id: str                            # "open_closed_ratio", "star_probe_count", "protected_topic_hits", ...
    criterion_id: str
    value: float | int | bool | None   # None ⇒ not measurable in this modality
    modality: str = Field(..., pattern="^(text|voice|both)$")
    evidence_turns: list[int]          # turn indexes that produced the value — auditability

class CriterionAssessment(BaseModel):
    criterion_id: str
    score: float = Field(..., ge=0.0, le=10.0)
    confidence: str = Field(..., pattern="^(high|medium|low)$")   # low when session too short/quiet
    deterministic_signals: list[SignalResult]
    judge_reasoning: str
    quoted_evidence: list[QuotedMoment]

class QuotedMoment(BaseModel):
    turn_index: int
    quote: str
    comment: str

class AssessmentReport(BaseModel):
    """The analytical estimation. NO pass/fail field exists in this model, by design."""
    report_version: str = RUBRIC_VERSION
    session_id: str
    weighted_estimate: float           # 0-10, weighted across criteria — an estimate, not a verdict
    criteria: list[CriterionAssessment]
    done_well: list[QuotedMoment]      # 2-4 moments
    focus_areas: list[FocusArea]       # lowest criteria, each with the moment + what to say instead
    development_plan: DevelopmentPlan  # which persona to practise next, and why
    transcript: list[Turn]             # full, timestamped — the audit record
    raw_judge_output: dict | None
```

Explicitly absent, per the user's correction: no `passed`, no `gate`, no
criterion cap or override anywhere in the schema or the aggregation code. The
schema is aggregation-ready (per-criterion numeric scores, stable signal ids)
so the deferred org-level reporting can be layered on without retrofitting.

---

## 3. Persona library v2 (`candidate_agent/archetypes.py`, `CATALOG_VERSION = "v2.0"`)

> **STATUS 2026-08-22 — catalog half SHIPPED, behavioural half DEFERRED.**
>
> `CATALOG_VERSION = "v2.0"` is live with **seven** personas, taken from the
> design mockup `interview_training_wizard (1).html` rather than the eight in
> §3.1 below. They line up almost exactly under different names — `evasive` ≈
> Vague Responder, `inflated_resume` ≈ Inflated CV, `defensive` ≈ Curt /
> Unprofessional, `comp_first` ≈ Off-Topic Asker, `cooperative_trap` ≈ Bias
> Bait, `nervous_fresher` ≈ Nervous but Capable, `rambler` ≈ Rambler. Only
> **Monosyllabic** is missing; it can be added later without touching anything
> else. `default_keys()` is `["cooperative_trap", "evasive"]`.
>
> §3.2 shipped **partly**: `session_beats` and `stresses` are on `Archetype` and
> validated in `_register`. `disruption` and `candidate_questions` are **not**
> built, so §3.3 did not happen either — `ENGINE_CONTRACT_VERSION` stays `v1.0`
> and the Go engine's pin is untouched.
>
> Beats reach the live persona through the **casting** prompt instead: they are
> rendered into `prompts.py`, the model turns them into `always_does`, and that
> lands verbatim in the compiled `ALWAYS` section. Verified against a live cast.
> **This is model-mediated, not enforced** — a beat is a tendency, not a
> scripted event, and `cooperative_trap` in particular is easier to steer off
> its trap than a `DisruptionSpec` would allow. Finishing §3.2/§3.3 is the
> follow-up.
>
> §3.4 (casting on role family instead of JD skills) is **not** done — that
> belongs with Phase 2's domain pivot, which has not started.


The machinery is reused wholesale; the contents change. The old catalog was
built so an interviewer could practise **judging candidates** (hence
`strong_hire`/`clear_reject` defaults and discovery scorecards). The new one
exists to **stress manager competencies**. The overlap is real but partial:
personas whose difficulty is *behavioural* (vague, inflated, nervous, rambling)
transfer; personas whose point is a *hiring verdict* (strong hire, clear
reject, wrong-stack specialist) do not, because nobody is grading the verdict
any more.

### 3.1 Mapping — decided

| BRD persona | Stresses | Existing archetype | Decision |
|---|---|---|---|
| Vague Responder | C2 | `lazy` | **Retune + rename** → `vague_responder`. Traits to effort 3 · smartness 4 · honesty 6; answer policy: concrete detail only after three probes. |
| Inflated CV | C2 | `resume_inflater` | **Retune** → `inflated_cv`. honesty 3 · preparedness 7 · smartness 5; "we"-claims machinery (`resume_claims` + `probe_that_exposes_it`) already exists and fits perfectly. |
| Curt / Unprofessional | C5, C4 | `disengaged` (partial) | **New** → `curt_unprofessional`. seriousness 3 · interest 4 · `interrupts_interviewer=True`; disruption: dismissive remark mid-session. |
| Off-Topic Asker | C1, C4 | none | **New** → `off_topic_asker`. preparedness 3 · interest 7; disruption: salary question in minute two. Needs the one genuinely new behaviour: the persona *asks questions* (a `candidate_questions` list on the archetype, injected into the system prompt). |
| Bias Bait | C3 | none | **New** → `bias_bait`. honesty 8 · nervousness 6; disruption: volunteers protected-category info (marriage plans, native place) at a scripted point. **The most important persona — build and tune it first among the new ones.** |
| Nervous but Capable | C4 | `nervous_but_capable` | **Reuse, retune traits** to nervousness 8 · smartness 7 · effort 7. Closest to as-is. |
| Rambler | C5, C2 | `rambler` | **Reuse, minor retune** (verbosity high · seriousness 6). |
| Monosyllabic | C4, C2 | none (nearest: `disengaged` speech) | **New** → `monosyllabic`. effort 2 · nervousness 5 · interest 4; speech terse; `on_silence: stays silent`. |

**Retired archetypes:** `strong_hire`, `clear_reject`, `smart_but_lazy`,
`disengaged`, `eager_underqualified`, `confident_bluffer`, `specialist_mismatch`
— all exist to be *judged as candidates*. Delete them from the v2 catalog (git
history keeps them). `default_keys()` becomes `["bias_bait", "vague_responder"]`.

### 3.2 Archetype dataclass additions

```python
stresses: list[str]                 # rubric criterion ids, e.g. ["bias"] — validated against evaluation_agent.rubric
disruption: DisruptionSpec | None   # (stage: str, behavior: str) — scripted, not random (BRD §6)
candidate_questions: list[str]      # questions this persona will ask, verbatim-ish
```

`_register` gains validation that every `stresses` id exists in the rubric.
Note: `archetypes.py` referencing rubric ids must NOT import `evaluation_agent`
(siblings never import each other) — the criterion ids are re-declared as a
frozen tuple constant in `candidate_agent`, and a *control-plane test* asserts
the two lists agree.

### 3.3 Engine contract addition (version → v1.1)

`EngineContract` gains `disruption: dict | None` and
`candidate_questions: list[str]`; `_compile_system_prompt` gains a SCRIPTED
MOMENT section. Byte-stability test fixtures regenerate; `ENGINE_CONTRACT_VERSION`
bump keeps the Go engine's pin honest.

### 3.4 Casting changes

`VirtualCandidateAgent.generate` signature becomes
`(role_id, archetype_key, job_title, summary, role_family, planned_minutes, seed_override, avoid_names)`.
The prompt grounds name/background/tics in the **role family vocabulary**
(sales: targets, territory, channel partners; technical: field equipment,
tickets, uptime) instead of JD skills. `knowledge_map` is keyed on 3-4
role-family topic areas generated within the archetype's `knowledge_band` —
ceilings still clamped in code.

---

## 4. The evaluation layer — new package `evaluation_agent/`

Placement: a **sibling agent package** (`llm` ← `evaluation_agent` ←
`control_plane`), added to `ALLOWED_IMPORTS`. It never imports `sqlite3` or
`control_plane`, never persists, takes injected models — all the existing
architecture tests extend to it automatically once it's in `PACKAGES`.

```
evaluation_agent/
  schema.py      # §2 models + TRANSCRIPT input shape (list[Turn]-compatible plain dicts)
  rubric.py      # the five Criterion instances; load_weights(path|None) -> validates sum==1.0
  signals/
    __init__.py  # extract_all(transcript, clarity_facts, telemetry|None) -> list[SignalResult]
    questions.py # open vs closed ratio, STAR-eliciting count, probing follow-up count
    bias.py      # protected-topic lexicon detector over manager turns (marital, children,
                 # pregnancy, age, religion, caste/community, native place, gender roles,
                 # disability, "will your family allow", "adjust")
    coverage.py  # C1 clarity-fact checklist (keyword match per fact) + candidate-question answer rate
    experience.py# greeting/self-intro/agenda ticks, time-to-first-invite, abrupt-end detector
    delivery.py  # talk-to-listen (word share in text), longest monologue, filler density,
                 # WPM / interruptions / silence-handling — voice-only, return value=None in text mode
  judge.py       # EvaluationJudge(model: StructuredModel) — one call per session, temperature 0.1,
                 # input: transcript + deterministic SignalResults + rubric; output: per-criterion
                 # score/reasoning/quotes against a strict JSON schema
  report.py      # assemble(session, signals, judge_out) -> AssessmentReport; the weighted_estimate
                 # is computed HERE in code (sum(score*weight)), never by the model; judge scores
                 # clamped to [0,10]; confidence downgraded by code when a criterion has <N evidence turns
  prompts.py     # judge system/user prompts; no I/O (SRP test applies)
```

Determinism split, restated for this component: **code owns** the signal
counts, the rubric ids and weights, the weighted aggregation, and confidence
downgrades; **the model owns** per-criterion reasoning, quote selection,
done-well/focus-area prose, and the development-plan recommendation (validated:
recommended persona must be a real catalog key, else replaced by the
lowest-criterion's designated persona in code). Every signal is reproducible
from the stored transcript — rerunning extraction on an old session must give
identical numbers (test this).

Modality honesty: each signal declares `text | voice | both`. In text sessions
the voice-only signals return `value=None` and the report prints "not
measurable in a text session" rather than a fake zero.

---

## 5. How the user converses — decided: text-first, voice later

**Decision: build a text chat session in the Python control plane now. Do not
wait for the Go engine.** The engine is at Phase 0 of a 15-section plan with a
<800ms voice budget — weeks away. A text loop against a new `ChatModel` port in
`llm/` is days away, and it produces the exact artifact the entire evaluation
layer needs (a timestamped turn transcript). Every persona also needs
conversational tuning that is far cheaper to iterate in text (BRD §8: "a
persona can read convincingly on paper and fall apart in conversation").

**What is lost in text mode, said plainly:** WPM, manager filler density,
interruptions, silence handling, pause behaviour, tone-of-voice — the
voice-only C4/C5 signals — plus overall realism (typing an interview is not
giving one). Talk-to-listen degrades to word-share. The report says so
explicitly per signal (§4).

**Why voice lands later without rework:** the session loop is built behind the
same `EngineContract` the Go engine pins; `modality` is a session field; the
evaluation layer consumes `(transcript, telemetry|None)` where telemetry is
exactly the engine plan's session-bundle turn metadata (aligned transcripts,
timings, interruptions). When the engine ships, it POSTs its bundle to the
same session-completion path, `modality="voice"`, the `None`-valued signals
light up, and nothing in `evaluation_agent/` changes shape.

Mechanics: `candidate_agent/session.py` — `CandidateSessionAgent(model: ChatModel)`
with `async def reply(contract: EngineContract, turns: list[Turn]) -> str`.
Stateless; control plane owns state and persistence (SRP intact). Session model
role prefix `SESSION_MODEL` / `SESSION_PROVIDER` in `.env.example`. Disruption
scheduling is deterministic: the control plane injects the scripted-disruption
directive into the context when the session crosses the archetype's stage
boundary (turn count / elapsed fraction), so two managers meet the same moment.

---

## 6. Endpoints, ports, and the operator UI

### 6.1 REST (replaces the interview/expectation surface)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/roles` | Create a job card |
| GET | `/api/v1/roles`, `/api/v1/roles/{id}` | List / fetch |
| GET | `/api/v1/personas` | The v2 catalog: key, label, trait signature, stresses, what-the-manager-must-do |
| POST | `/api/v1/sessions` | `{role_id, persona_key, planned_minutes}` → casts (or reuses) the persona, opens the session, returns `opening_line` |
| POST | `/api/v1/sessions/{id}/turns` | `{text}` → stores manager turn, generates + stores candidate turn, returns it |
| POST | `/api/v1/sessions/{id}/end` | Close the session (`completed`); an abrupt end here is itself a C4 signal |
| GET | `/api/v1/sessions/{id}` | Session with full transcript |
| POST | `/api/v1/sessions/{id}/report` | Run signals + judge + assembly; persist; idempotent (returns stored report on re-call unless `?regenerate=true`) |
| GET | `/api/v1/sessions/{id}/report` | Fetch stored report |
| Kept | `/api/v1/candidates/{id}`, `/engine-contract` | Unchanged — the Go engine's pull path |

### 6.2 Ports (`control_plane/ports.py`)

`RoleStore` (create/get/list) · `CandidateStore` (unchanged) · `SessionStore`
(create_session/get_session/append_turn/end_session) · `ReportStore`
(save_report/get_report). Compositions: `SessionWorkflowStore = Role + Candidate + Session`,
`ReportWorkflowStore = Session + Report`. Each handler takes the narrowest
port; the turn handler needs only `SessionStore`.

### 6.3 UI flow (what a person clicks)

1. **Roles tab** — create a job card (title, summary, family dropdown, optional clarity facts). One seeded card per family via a "seed examples" button.
2. **Personas tab** — 8 cards showing label, trait signature, "stresses C3", "what you'll have to do". Click **Start interview** → pick role → session opens.
3. **Session view** — chat pane; candidate's opening line pre-filled; manager types turns; elapsed-time header; **End interview** button.
4. **Report view** — weighted estimate dial, five criterion rows (score + the deterministic counts + judge reasoning, expandable), done-well / focus-areas quotes, development plan, full transcript. No pass/fail badge anywhere.

Implementation: extend `ui/src/api.js`; split `App.jsx` into
`RolesView / PersonaPicker / SessionView / ReportView` components.

---

## 7. Database — pre-production, break it

No migrations. Delete `control_plane.db` (gitignored), new `_SCHEMA`:

- **Drop:** `interview_expectations`, `interview_assignments`, `ai_personas`.
- **Replace:** `interviews` → `roles` (`id, job_title, summary, role_family CHECK(...), clarity_facts TEXT json, created_at`).
- **Keep, rekey:** `virtual_candidates` — `interview_id` → `role_id`, UNIQUE `(role_id, archetype)`.
- **Add:** `sessions` (`id, role_id FK, candidate_id FK, persona_key, status CHECK(live|completed|abandoned), modality, planned_minutes, started_at, ended_at, created_at`), `session_turns` (`session_id FK, idx, speaker, text, at, elapsed_ms, PRIMARY KEY(session_id, idx)`), `reports` (`session_id PK FK, report_version, report_json, model_used, created_at`).

`repository.py` rewritten to match; the ISP/port-satisfaction architecture
tests keep it honest.

---

## 8. Ordered ToDos

Dependencies: each item depends on the unchecked items above it in its phase
unless a `dep:` says otherwise. Phases 1 is the shortest honest path to a live
conversation and comes before any pivot polish on purpose — it converses using
the **existing** interview/archetype machinery, then Phases 2–5 pivot the
domain underneath it.

### Phase 1 — Talk to a persona (critical path, existing domain model) — **DONE 2026-08-22**

- [x] **1. `ChatModel` port in `llm/`.** Add `ChatModel` ABC (`generate_text(*, system, messages: list[dict]) -> str`) to `llm/base.py`; implement in `llm/gemini.py` + `llm/openai_model.py`; factory roles `SESSION`/`JUDGE` + `.env.example` entries (`SESSION_PROVIDER/MODEL`, `JUDGE_PROVIDER/MODEL`).
  *Done when:* architecture tests pass (vendor SDKs still only in `llm/`); a live smoke script gets a text reply from both providers.
- [x] **2. `CandidateSessionAgent`.** `candidate_agent/session.py`: stateless `reply(contract, turns) -> str` using the contract's `system_prompt` verbatim plus a short text-mode preamble ("this is a typed conversation — write as you would speak, fillers included").
  *Done when:* offline unit test with a fake `ChatModel` proves the system prompt is passed verbatim and history is ordered; SRP scan passes (no persistence, no `control_plane` import).
- [x] **3. Session storage.** `sessions` + `session_turns` tables, `SessionStore` port, repository methods. (Runs against the *current* `interviews` table via a nullable `role_id`-vs-`interview_id` — simplest: add `sessions.interview_id` now, renamed in task 12.)
  *Done when:* port-satisfaction and ISP tests green.
- [x] **4. Session endpoints.** `POST /sessions`, `POST /sessions/{id}/turns`, `POST /sessions/{id}/end`, `GET /sessions/{id}` per §6.1, narrowest ports, server-side timestamps on every turn.
  *Done when:* curl transcript: create interview → enroll `nervous_but_capable` → open session → three turns → end → GET returns the full timestamped transcript.
- [x] **5. Chat UI.** `SessionView` in `ui/`: persona list → start → chat pane → end.
  *Done when:* **the user conducts a full text interview against any existing archetype from the browser.** ← the milestone the user asked for
- [x] **6. okf + handover for Phase 1.** Update `llm-port`, `candidate-agent`, `control-plane`, `rest-api`, `database-schema` concepts; `okf/log.md` line; `scripts/export_schemas.py` run for the new session schemas.
  *Done when:* `scripts/check.sh` green; log line present.

### Phase 2 — The pivot: job card in, expectation agent out

- [ ] **7. Retire `expectation_agent/`.** Delete the package, its endpoints, ports, table, `tests/test_expectation_agent.py`; purge from `PACKAGES`/`ALLOWED_IMPORTS`, `export_schemas.py`, `.env.example` (`EXPECTATION_*`).
  *Done when:* `scripts/check.sh` green with the package gone; grep for `expectation` finds only okf history and this plan.
- [ ] **8. `evaluation_agent/rubric.py` + package skeleton.** New package with `rubric.py` (five criteria, weights .20/.25/.20/.20/.15, `load_weights()` with `RUBRIC_CONFIG_PATH` override, sum==1.0 validation) and `schema.py` stubs; add to `PACKAGES`/`ALLOWED_IMPORTS`.
  *Done when:* architecture tests cover the new package; unit test rejects weights that don't sum to 1.
- [ ] **9. Role card schema + endpoints.** `RoleCard`/`ClarityFact`/`RoleResponse`; `roles` table replaces `interviews`; `/api/v1/roles` endpoints; delete `control_plane/persona.py` and legacy schema classes.
  *Done when:* create/list/fetch round-trips; old interview endpoints removed; `export_schemas.py` regenerated.
- [ ] **10. Recast casting.** `VirtualCandidateAgent.generate` takes job card + role family (§3.4); prompts rewritten for role-family vocabulary; knowledge map keyed on topic areas.
  *Done when:* offline rubric tests (clamping, seeded traits, fingerprints) green against the new signature; one live cast per role family reads plausibly.
- [ ] **11. Session endpoints onto roles.** `sessions.role_id`, `POST /sessions` takes `{role_id, persona_key}` and auto-casts on first use (no separate enroll step in the happy path).
  *Done when:* the Phase-1 UI flow works end-to-end on a job card.
- [ ] **12. DB reset + repository cleanup.** Final §7 schema; drop-and-recreate; remove dead repository code.
  *Done when:* fresh DB boots; all ports satisfied; check.sh green.
- [ ] **13. okf + handover for Phase 2.** Retire expectation concepts (mark superseded, don't silently delete pages), new role-card and evaluation-skeleton concepts, log line, handover regeneration.

### Phase 3 — Persona library v2

- [ ] **14. Archetype dataclass additions.** `stresses`, `disruption`, `candidate_questions`; `_register` validation; criterion-id constant + control-plane agreement test (§3.2).
  *Done when:* validation rejects an unknown criterion id in a unit test.
- [ ] **15. Engine contract v1.1.** Disruption + candidate-questions in `EngineContract` and the compiled prompt; bump `ENGINE_CONTRACT_VERSION`; regenerate byte-stability fixtures.
  *Done when:* `test_system_prompt_is_byte_stable` green on new fixtures.
- [ ] **16. The four retunes/reuses.** `vague_responder` (from `lazy`), `inflated_cv` (from `resume_inflater`), `nervous_but_capable`, `rambler` to BRD trait signatures; retire the seven candidate-judgement archetypes; `CATALOG_VERSION = "v2.0"`; `default_keys()` → `["bias_bait", "vague_responder"]` (dep: 17 for bias_bait key existing — do keys in one commit).
- [ ] **17. The four new personas.** `bias_bait` first, then `curt_unprofessional`, `off_topic_asker`, `monosyllabic`, each with scripted disruption and scorecard-weight sums valid.
  *Done when (16+17):* catalog holds exactly the 8 BRD personas; parametrized LSP/rubric tests green across all 8.
- [ ] **18. Disruption scheduling in the session loop.** Control plane injects the scripted moment at the archetype's stage boundary, deterministically.
  *Done when:* two replayed sessions with the same persona hit the disruption at the same turn window.
- [ ] **19. Conversation-tune all 8.** Interview each persona in the UI; adjust traits/policies/prompts until each demonstrably stresses its criterion (BRD §8's whole point). Budget real time here.
  *Done when:* a short tuning note per persona records what was checked (bias_bait volunteers protected info unprompted; monosyllabic never exceeds ~2 sentences; etc.).
- [ ] **20. okf + handover for Phase 3.** Catalog concept rewrite, contract version note, log line, handover regeneration.

### Phase 4 — Evaluation layer

- [ ] **21. Transcript + report schemas.** `evaluation_agent/schema.py` per §2 (SignalResult, CriterionAssessment, AssessmentReport, QuotedMoment, FocusArea, DevelopmentPlan).
  *Done when:* schemas exported; no pass/fail-shaped field exists (add a test asserting the schema has no such field — cheap insurance against regression).
- [ ] **22. Signal extractors: questions.** Open/closed ratio, STAR-eliciting lexicon count, probing follow-up count.
  *Done when:* golden-transcript fixtures (hand-written) produce exact expected counts; rerun is byte-identical.
- [ ] **23. Signal extractors: bias.** Protected-topic lexicon over manager turns, per BRD's exact list, with evidence turn indexes.
  *Done when:* fixture with 6 planted violations yields exactly 6 hits, zero false positives on the clean fixture.
- [ ] **24. Signal extractors: coverage + experience + delivery.** Clarity-fact checklist, answer rate, greeting/agenda ticks, time-to-first-invite, abrupt-end detector, word-share, longest monologue; voice-only signals return `value=None, modality="voice"`.
  *Done when:* golden fixtures pass; a text-mode run contains explicit `None` signals, never zeros.
- [ ] **25. Judge pass.** `judge.py` + `prompts.py`: one `StructuredModel` call, temp 0.1, strict JSON schema, input includes the deterministic counts (the judge explains, it does not recount).
  *Done when:* offline test with fake model validates clamping and schema enforcement; one live run reads sensibly.
- [ ] **26. Report assembly.** `report.py`: weighted estimate in code, confidence downgrades in code, development-plan persona validated against the catalog.
  *Done when:* property test — report total always equals `sum(score*weight)` regardless of judge output.
- [ ] **27. Report endpoints + persistence.** `reports` table, `ReportStore`, `POST/GET /sessions/{id}/report`, idempotent.
  *Done when:* end interview → generate → fetch round-trips; regenerate flag works.
- [ ] **28. Report UI.** `ReportView` per §6.3.
  *Done when:* **the user takes an interview and reads the full analytical report in the browser** — the complete BRD §8 milestone.
- [ ] **29. okf + handover for Phase 4.** New evaluation subsystem/contract concepts, determinism concept extended with the signals/judge split, log line, handover regeneration.

### Phase 5 — Hardening (still pre-POC, still no deferred scope)

- [ ] **30. Live scenario tests under `--live`.** One scripted session per persona (canned manager turns) asserting the persona held character and the report generated.
- [ ] **31. Determinism regression suite.** Re-extract signals from stored Phase-4 transcripts; assert identical `SignalResult`s. Seeded persona re-cast asserts stable `seed_fingerprint`.
- [ ] **32. `.gitignore` fix.** `docs/` and `owner_handover/` are currently ignored despite the "tracked on purpose" comment (okf found this) — **this plan file itself is untracked until fixed**. Exclude `okf/` correctly too. Commit the deliverables.
- [ ] **33. Voice landing pre-work (engine plan §8 refresh only).** Update `docs/ENGINE_IMPLEMENTATION_PLAN.md` §8 so the engine posts its session bundle to `POST /sessions/{id}/...` as `modality="voice"`. No Go code.
- [ ] **34. Final okf sweep.** `project-overview`, `repo-map`, `glossary` (retire "expectation", "verdict"-as-score; add "rubric", "signal", "judge pass", "job card"), log line.

**Total: 34 ToDos.** User-visible conversation lands at **task 5**; the full
BRD first-runnable milestone at **task 28**.

---

## 9. Risks and open questions needing a human decision

1. **Language / code-mixing (BRD D-6) — the biggest engineering risk.** Hindi or Hinglish sessions break the question classifier, STAR lexicon, protected-topic detector, and filler counting simultaneously. This plan builds English-only detectors. **Decision needed before Phase 4 hardening:** confirm English-only for the POC, or Phase 4 needs a re-scope (multilingual lexicons at minimum, likely judge-side classification instead of lexicons).
2. **Deterministic detectors are lexicon-based and will miss paraphrase.** An open/closed classifier and a protected-topic detector built from patterns have known false-negative rates ("So you're married, settled here?" contains no lexicon word). Mitigation is designed in — the judge pass cross-checks and quotes — but the "deterministic = auditable" claim only covers what the lexicons catch. Accepting that gap (vs. adding a per-turn classifier model call, which costs latency and money) is a product call.
3. **Persona believability is empirical, not specifiable.** Phase 3 task 19 is the only honest test, and it may loop several times — especially `bias_bait`, which must volunteer sensitive information naturally without becoming a caricature, and `monosyllabic`, which chat models resist playing. Budget tuning time; do not promise client dates from this plan before task 19 completes.
4. **Rubric weights and band names are Atibhee's (BRD D-1/D-2).** Built as config (`RUBRIC_CONFIG_PATH`) so their answer changes a file, not code — but the report's presentation bands ("developing / solid / strong"?) need their naming before anything client-facing.
5. **Judge score stability.** Same transcript, two judge runs, different scores by ±1 is likely even at temp 0.1. If comparability across managers is the selling point, consider pinning the judge model id per rubric version and noting model+version in every report (the plan stores `model_used`; pinning policy is a human decision).
6. **Scorecard/verdict retention.** This plan keeps `InterviewerScorecard`/`verdict` as non-scoring persona metadata. If the user prefers a cleaner cut (delete them, `PERSONA_VERSION v2.0`, bigger diff in agent + tests), say so before Phase 3 — it is cheap there and expensive after.
7. **D-8 (does the report reach the boss)** doesn't change this codebase yet, but it changes what managers do in sessions and therefore what tuned personas see. Flag to Atibhee early, as the BRD itself urges.
