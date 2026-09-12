# Directory Update Log

## 2026-08-21
* **Creation**: hand-curated OKF v0.2 bundle authored from the source tree at commit `802c842`.
* **Change**: `scripts/check.sh` go block targets `engine/` (adds `go build`, `go test -race`, guarded arch gate, `//go:build live` under
  `--live`); `pyproject.toml` excludes `okf/`/`docs/` from ruff. Additions: `docs/ENGINE_IMPLEMENTATION_PLAN.md` (8 phases, 58 ToDos),
  `concepts/subsystems/engine.md`, `docs/ENGINE_ONE_BRAIN_TWO_PARTS.html`, `LICENSE` (proprietary).
* **Change (engine phase 0)**: module skeleton + `internal/{ports,contract,config,fakes,arch,session}`, `cmd/engined`. Two fixes:
  `contract.Parse` wraps `ErrInvalidContract` on decode failure (malformed JSON was surfacing as 5xx); `engined` refuses to boot without
  `-dev-sample-contract`.
* **BRD v3** (`docs/BRD_Interviewer_Upskilling_v3.{html,pdf}`, supersedes v2): assessed subject flips candidate → hiring manager; JD no longer
  drives the rubric; **removed the Unconscious Bias critical-fail gate — no criterion caps, fails or overrides the result.** No code changes.
* **Fix**: `.gitignore` was ignoring `owner_handover/` and `docs/` despite the "tracked on purpose" comment (untracked
  `engine_contract_schema.json`, `GO_ENGINE_CONTRACT.md`). Rules removed.
* **Addition**: `docs/PIVOT_PLAN_MANAGER_ASSESSMENT.md` (5 phases, 34 ToDos). Decides: retire `expectation_agent/`, build a text-first session
  in Python rather than wait on the Go voice engine.
* **Addition — Phase 1 live text session**: `ChatModel` port in `llm/base.py` (Gemini/OpenAI adapters, `CHAT_PROVIDERS`,
  `build_chat_model()`); stateless `CandidateSessionAgent`; `sessions`/`session_turns` tables + `SessionStore`; `POST /sessions`, `.../turns`,
  `.../end`, `GET`; `SessionView.jsx`; `tests/test_session.py`. **Decisions worth carrying forward**: the speaker enum is `manager|candidate`
  (BRD flip needs no transcript rename); turn indexes and timestamps are assigned by the repository, never the caller.
* **Addition — voice mode** (WebRTC to OpenAI Realtime, 🎙 Voice button): `RealtimeBroker` port — mints a short-lived credential the browser
  redeems, so 24 kHz audio never enters this process. `llm/openai_realtime.py`, `candidate_agent/voice.py`, `POST
  /sessions/{id}/realtime`/`transcript`, `GET /voice-capability`, `VoiceSessionView.jsx`. **Decisions worth carrying**: (1) the browser is
  never sent `instructions` — sealed vendor-side, test asserts the prompt appears nowhere; (2) a `modality='voice'` session writes **no turn
  0** (persona speaks its opening line, browser reports it back); (3) `REALTIME_PROVIDERS` is a deliberate subset of `PROVIDERS`
  (OpenAI-only), with its own subset test; (4) voice hashed from `candidate_id`, making the vendor's voice ordering part of the contract.
  **Honest gap**: this is Speaker-only — no deterministic pre-gate until the Go Thinker lands. Vendor facts verified live 2026-08-22 in
  `contracts/realtime-voice.md`. New: `contracts/realtime-voice.md`, `modules/candidate-agent-voice.md`.

## 2026-08-22
* **Change**: console aligned to the SkillBrew.AI mockup (`interview_training_wizard (1).html`, the finished-product UI). Built
  `ui/src/index.css` + `Shell`/`InterviewList`/`Wizard`/`PersonaPicker`/`InterviewDetail`. **Not built, by decision**: manager cohort
  readiness/bias flags, report toggles, CSV upload (no endpoint produces them — invented numbers would be the most convincing thing on the
  page). The mockup's `Fair & Inclusive · Critical` gate was **not ported** (contradicts the no-hard-limit rule), flagged on the UI page.
* **Catalog v1.0 → v2.0**: the eleven candidate-judging archetypes replaced by seven manager-stressing ones — `cooperative_trap`, `evasive`,
  `nervous_fresher`, `inflated_resume`, `comp_first`, `defensive`, `rambler`. `Archetype` gains `session_beats` + `stresses` (criterion→1-4).
  `RUBRIC_CRITERIA` declared in `candidate_agent`, not imported from a sibling. `test_ocp_new_archetype_needs_no_agent_change`.
* **Decisions worth carrying forward**: (1) `session_beats` reach the persona through the **casting** prompt, not the engine contract —
  model-mediated, **not enforced**; no `ENGINE_CONTRACT_VERSION` bump; deterministic scripting (`DisruptionSpec`) deferred to Phase 3.2. (2)
  `GET /interviews/{id}/sessions` returns `SessionSummary`, not `SessionResponse`. (3) the catalog endpoint ships
  `rubric_criteria`/`stress_labels`. (4) the Readiness tile renders `—` "no evaluation layer yet" rather than being omitted.
* **Change — Phase 0 MVP milestone M1 (interview config completeness)**: the wizard HTML is the manager's *requirements*, not a design
  reference. `InterviewCreateRequest`/`interviews` gain `location`, `department`, `manager_level`, `language`, `proctoring`,
  `candidate_notes`, `clarity_facts`, `report_sections`; vestigial `config.language` removed. **New package `evaluation_agent/`** (imports
  `llm` only): `rubric.py` (four criteria — Clarity 25, Structured 30, Fair & Inclusive 25, Communication & Presence 20 — with bands and
  `load_rubric(path)`), `schema.py` (`CLARITY_FACT_KEYS`, six role facts), `role_facts.py` (drafts wording at temp 0.1).
* **Decisions worth carrying forward**: (1) **rubric criteria are the manager's four, not the BRD's five** (mockup is the newer artefact);
  `test_rubric_vocabulary_agrees_across_the_two_agents`. (2) the critical-fail gate is knowingly not implemented;
  `test_the_rubric_has_no_critical_fail_gate`. (3) **role-fact keys are fixed in code, the model only drafts statements** (a hallucinated
  seventh is discarded, a skipped key returns empty). (4) auto-fill is a wizard button (`POST /role-facts`); `POST /interviews` stays
  model-free.
* **`language` is behaviour**: it reaches the casting prompt, the compiled `HOW YOU TALK` section, and the realtime transcription hint — that
  last is a prompt change, so **`ENGINE_CONTRACT_VERSION` is now `v1.1`** (engine parses by major, retains minor). `hinglish` sends **no**
  transcription hint — the vendor's `languages` plural is rejected by every transcribe model (verified live).
* **`candidate_notes` is the first unstructured operator text to reach casting** — subordinated in the prompt, guarantees re-enforced after
  it; `test_operator_notes_cannot_override_the_archetype`. **`proctoring` is recorded and never enforced** (wizard says so on screen).
* **Verification pass (OKF catch-up)**: module level had lagged the subsystem/contract level; new module cards
  `evaluation-agent-{rubric,role-facts}.md`. Note recorded: v1.1 is taken by the language line, so behavioural fields would be v1.2.

## 2026-08-23
* **Addition — dynamic persona composition** (branch `feature/dynamic-persona-composition`, rebased onto v2.0):
  `candidate_agent/trait_dimensions.py` with `compose_archetype`/`register_dynamic` (an `Archetype` from generic presets) and
  `compose_human_traits` (a `HumanTraitProfile` taxonomy: affect, verbal style, language & literacy, comprehension, integrity, motivation,
  negotiation, compliance traps, environment, profile). `HumanTraitProfile`+`EnvironmentProfile` added as optional `human_traits` on
  `VirtualCandidate` (`PERSONA_VERSION`/`ENGINE_CONTRACT_VERSION` v1.0 → v1.1); optional "REALISM & COMPLIANCE LAYER" section, byte-identical
  when absent. `GET /api/v1/trait-dimensions`, `custom_personas` on `CandidateEnrollRequest`, content-addressed `dyn-<hash>` key (422 before
  any model call if malformed). Two Airtel archetypes added content-only, no `CATALOG_VERSION` bump. `PersonaComposer.jsx` + inline-SVG radar.
* **Rebase onto v2.0**: `Archetype` gained required `session_beats`/`stresses`; both frontline archetypes and `compose_archetype` failed to
  register until updated (both derived from the same presets, not a relaxed subset). Two tests referenced removed keys → now read
  `default_keys()`/any registered key. 300 tests pass.
* **Fix** (pre-rebase): `HumanTraitProfile.compliance_traps`/`.integrity_red_flags` unconstrained → `StringConstraints`;
  `compose_human_traits` raises when `volunteers_protected_info` present without `protected_info_type`, treats `""` as "not set". Regression
  tests in `test_trait_dimensions.py`/`test_control_plane_candidates_api.py`.
* **Env** (not code, `.env` gitignored): `EXPECTATION_MODEL`/`CANDIDATE_MODEL`/`SESSION_MODEL` moved off retired `gemini-2.5-flash` to
  `gemini-3.6-flash`.
* **Addition**: wizard step 2 "Pick from catalog" / "Compose custom" toggle; `createFromWizardCustom` composes-and-casts through enrollment
  first (so `human_traits` carries through).
* **Addition**: `tests/test_custom_persona_integration.py` (12 cases) — proves a composed persona *enacts* as defined, driving the full
  `generate()` pipeline against an adversarial fake model; parametrized across bias traps, compliance traps, a 25-seed bounds sweep. Plus
  `test_session_round_trip_with_a_custom_composed_persona`.
* **Addition**: `tests/test_full_interview_pipeline_integration.py` (12 cases) — full manager-facing HTTP flow across a 5-persona matrix
  against fake models. **Gap surfaced**: there is **no post-session judge or grader** — `JUDGE_MODEL`'s prefix and the Go `Judge` port are
  reserved but unimplemented in Python, so the only "report" today is the scorecard's casting-time answer key, not a score of the
  conversation. Documented on `subsystems/candidate-agent.md`.
* **Fix**: radar chart (`PersonaComposer.jsx`) — three separate bugs (near-invisible strokes; label offset/anchor clipping; top-axis
  label/value order reversed). Then the radar was made to plot all six axes (Competence, Effort, Composure, Honesty, Comprehension, Fluency)
  built live from the selected presets; `dimension_catalog()` attaches a 0-10 `score` per preset (kept as a separate mapping merged at
  serialization). `test_dimension_catalog_scores_are_present_and_ordered_with_their_presets`. 326 tests.
* **Fix (sweep, adversarial review + live Playwright)**: (a) `generate_expectation`/`enroll_candidates`/`start_session` didn't catch
  `ModelError` → raw 500; now `except ModelError → HTTPException(502)`; `tests/test_model_error_surfacing.py` (4 cases). (b) client-side:
  shared `personaSpecError(spec)` blocks the `volunteers_protected_info`-without-type 422; `setNumber` coerces the "Offers in hand" input;
  radar guard tightened to `Number.isFinite`. 330 tests.

## 2026-08-23 (control plane, custom personas)
* **Fix (blocking)**: a custom persona became unusable after any restart — `_register_custom_persona` wrote into module-level `ARCHETYPES` at
  request time and `start_session` checked it before the DB, so the archetype didn't survive restart. Composed archetypes are now **validated
  but never registered** (`_register` split into public `validate_archetype` + private registrar; `register_dynamic` deleted; `agent.generate`
  gained `archetype=`); `start_session` resolves from the DB first. Also fixes unbounded catalog growth and cross-interview leakage.
  Regression: `test_a_custom_persona_survives_a_process_restart`.
* **Fix (blocking)**: six profile fields (`seniority`, `function`, `region`, `gender_presentation`, `age_band`, `notice_period`) were
  unvalidated `str` f-string-interpolated **after** `HARD RULES`, so Region text could displace `UNIVERSAL_FORBIDDEN`. Four are now closed
  vocabularies; `function`/`region` stay free text via `schema.PROFILE_TEXT_PATTERN`, rendered quoted; the realism layer now sits **before**
  `HARD RULES`. `CustomPersonaSpec.label` capped.
* **Fix**: the realism layer emitted raw vocabulary tokens (`flirtatious_inappropriate`, floats) — persona design delegated to the model.
  Every value now compiles through directive tables in `engine_contract` (`AFFECT_DIRECTIVES`, `VERBAL_STYLE_DIRECTIVES`, …,
  `_accent_directive`/`_code_switch_directive`); the tables are the vocabulary's single source of truth and `test_architecture.py` asserts no
  directive restates its own key.
* **Fix**: `compose_archetype` returned a constant `stresses` map while claiming derivation; `_derive_stresses` now sums and clamps per-preset
  pressure.
* **Fix (typing)**: nine preset tables were `dict[str, dict]` merged behind `# type: ignore` (a misspelt key composed silently); now
  TypedDicts, ignores gone, `validate_archetype` checks runtime shape, `_register` refuses a duplicate key.
* **Fix (layering)**: `trait_dimensions` imported private `archetypes._register`; composition moved behind `compose_custom_persona(...)`,
  handler reduced to exception translation, `api.py` drops `hashlib`/`json`.
* **Fix (CI)**: five test files (~1,400 lines) were never run by `check.sh`'s explicit file list. All wired;
  `test_every_test_file_is_wired_into_the_gate` fails the build if a sixth is added unwired. Wiring exposed two assertions with drifted prompt
  prose.
* **Correction**: the taxonomy was cited throughout as "BRD §3.2" — it is not (no doc in `docs/` contains its terms). Citation removed
  everywhere; **provenance still open, needs the author.**
* **Not changed, needs a product decision**: the two Airtel archetypes take the catalog 7 → 9 with no `CATALOG_VERSION` bump; custom
  composition is not in the Phase 0 spec; `affect="flirtatious_inappropriate"` — a call for the manager.
* **Merge (M1 → this branch)**: 16 textual conflicts across ten files, all resolved by keeping both. **Semantic merge (the dangerous one)**:
  M1 narrowed `RUBRIC_CRITERIA` five → four (`bias`→`fairness`, experience folded into communication) while this branch added 22 preset stress
  contributions against the old five; `validate_archetype` raised at import. Remapped all 29 sites.
* **Contract**: `ENGINE_CONTRACT_VERSION` → **v1.2** — both branches bumped to v1.1 for different prompt changes, the merged prompt is a third
  shape. `HARD RULES` moved to the end of the prompt (affects every persona). No engine change. 372 offline tests.
* **Live verification**: code-owned verdict/trait bounds survive a real cast; knowledge ceiling holds above-band; `UNIVERSAL_FORBIDDEN` holds
  against a break-character probe; `hinglish` code-switches; composed personas enact directives verbatim; the compliance trap fires in
  character; a composed persona survives a real restart.
* **Fix**: `protected_info_type` interpolated verbatim ("volunteer your marital_status") — humanised at the render site;
  `test_protected_info_type_reaches_the_prompt_as_english`.
* **Open (design gap, not a regression)**: `human_traits` reach the compiled engine prompt but **never the casting prompt**, so
  `opening_line`/`sample_phrases`/`verbal_tics`/`always_does` are authored blind to the realism layer (observed live: a persona told it joined
  late opened as if on time). Worth routing through casting like `session_beats`, with a `PERSONA_VERSION` bump when it is.

## 2026-08-23 (control plane, persona coherence)
* **Fix (coherence, matters for bake-once)**: implements the gap above — a persona is compiled once and replayed, so casting authored blind to
  the realism layer was baked in. `engine_contract.casting_realism_note(traits)` renders the directive tables for the casting side;
  `agent.generate` passes it through. `PERSONA_VERSION` v1.1 → **v1.2**; contract shape unchanged so `ENGINE_CONTRACT_VERSION` stays v1.2.
* **Fix (found by the above)**: the casting model also picks the persona's **name** blind (a `gender_presentation="woman"` spec cast *Manish
  Kumawat*). Profile facts now go into the casting note; re-cast as *Pooja Sharma*.
* **Fix**: `_english()` no longer emits closed-vocabulary keys with underscores (`30_days`, `non_binary`). Same defect as `marital_status`,
  generalised and tested.
* **Change**: default Gemini model moves to **`gemini-3.7-flash`**, pinned to an explicit version not `-latest` **on purpose** (a persona is
  compiled once and replayed — a silently-changing casting model is the drift this codebase prevents). Swept `okf/` and `.env.example`.

## 2026-08-23 (engine, phases 0–4 — build milestones)
The engine build milestones, collapsed. Each bullet keeps its version/fix/gap; full detail in [Live-session
engine](/concepts/subsystems/engine.md).

* **Phase 4 task 32 — contract v1.3, dual-model runtime fields**: `EngineContract` gains `precompiled_beliefs[]`, `stall_phrases[]`,
  `pregate_lexicon{}`, `unlock_spec`, `tts_voice_id`; `SkillKnowledge` gains `belief_elaborations`/`vague_deflections`/`probe_aliases`
  (model-authored at cast, casting rules 5a–5c). **`ENGINE_CONTRACT_VERSION` v1.2 → v1.3**; all fields optional so v1.0–v1.2 still parse and
  degrade to single-model. Determinism: `claim_id`s assigned by code in `knowledge_map` order (a runtime-invented belief would void
  `seed_fingerprint`). `pick_voice` moved to `engine_contract.py`. **Fix (live)**: `compile_unlock_spec` matched never-markers with
  `startswith` → "He never reveals…" compiled to `conditional`; now whole-prose with a trigger-word exception. Go types extended; parses by
  major, no engine change. 391 tests.
* **Phase 1 turn loop (tasks 9–14)**: `state.go` (eleven states as a testable transition **table**; barge-in/wind-down applied on top),
  `obs/events.go` (JSONL from the **injected clock** for byte-identical FakeClock logs), `timers.go` (six alarms, each arming carries a
  **generation** so a stale fire is discarded — the ghost-utterance class), `playout.go` (heard-time from 250 ms heartbeats, capped at
  bytes-sent, monotonic), `actor.go` (priority nested select: control/timers drain first, media drop-oldest, heartbeats newest-wins). **Fix
  (goleak)**: timer waiter leaked per cancelled alarm → selects on its own stop channel. **Fix (arch gate)**: `time.After` banned in
  `internal/session`. **Verification** re-introduced both bugs; found a third — `TestThousandSessionChurnLeavesNothingBehind` armed no alarms
  so it couldn't fail; now arms every alarm per cycle. 41 tests.
* **Phase 1 task 15 — confident turn path**: `turn.go` records the §8.2 ingest shape (`probed_skill`, `deferred`, `fallback_used`, `trimmed`,
  `barged_in`, `heard_ms`); interviewer turn opens on their **first** partial. Sentence bounds enforced by trimming (layer 5), with a grace
  clause so a cut never lands mid-sentence. **Fix (done-when test)**: `handlePregate` checked state (still `LISTENING` at end-of-turn) so
  every verdict filed "pending" and fell through to fallback; now keys off the pre-gate deadline being armed, and the pending verdict is no
  longer compared against an incremented `a.turn`.
* **Phase 4 task 33 — claims ledger (`internal/ledger`)**: seeded from `precompiled_beliefs` at turn 0, single-writer, `b*`/`r*` ids (designed
  vs runtime), walk-backs supersede rather than delete. Contradiction detection is deterministic (canonical forms + negation parity), and
  **honest about its limits — it does not catch semantic contradiction between differently-worded claims; that is the async Judge's job (layer
  6).** **Fix**: canonicalization missed inflected negation ("fixes"/"does not fix") — now stems trailing s/es/ies and drops do/does/did; a
  hedge is checked before polarity. 45 session, 13 ledger tests.
* **Phase 3 task 27 + Phase 4 tasks 34–36 — reasoning model in the loop**: `internal/gate` deterministic pre-gate over **partial** transcripts
  (a defer must reach the wire within 50 ms); word-boundary alias match, longest wins, totally ordered (Go randomises map iteration). Full
  defer flow: pre-gate → DEFERRED → stall + `RequestNote(700 ms)` → note injected as a system item. A missed deadline falls back to
  `on_unknown_question` (layer-3 floor), marked on the record. Ledger → both models (34); ceiling re-assertion (35) on cadence and immediately
  on any probe at ceiling ≤ 3; unlock (36): the Thinker assesses, **the actor decides**, monotonic, and a `kind:"never"` persona can't be
  talked into unlocking. **Design**: ledger/pre-gate reach the actor as **ports** (`ports.ClaimLedger`, `ports.PreGate`); a nil collaborator
  degrades to single-model. **Fix (goleak)**: the note pump exited only on session-context cancellation → per-turn gate closed by every
  turn-ending path. 55/13/10 tests.
* **Phase 3 task 29 — Thinker adapter (`internal/vendors/thinkerllm`)**: real reasoning model over Gemini REST (`net/http`+`encoding/json`, no
  new dep). Runs **speculatively** (each partial supersedes the last guess); short partials ignored; `RequestNote` joins the flight and closes
  at the deadline without a note. `responseSchema`-enforced output, temperature 0.2 (this layer retrieves, creativity = invention voids
  `seed_fingerprint`); nil unlock = "no opinion"; claims bounded. **Fix (structural, from Phase 0)**: Go reserves any dir named `vendor` →
  renamed `internal/vendors/`; would have blocked every adapter, invisible while all six were `doc.go` stubs. **Fix (tests)**: race on
  `FeedPartial`. **Wiring**: builds Thinker when configured, else single-model with a warning. 11 tests.
* **Phase 2 M1 — arch guards**: **Fix (guard not guarding)**: rule 1 had been **inert for the whole vendors tree** since the
  `vendor`→`vendors` rename (`forbiddenPackagePrefixes` still read `internal/vendor`); proof — `thinkerllm`/`judgellm` imported a forbidden
  `geminijson` while the arch test passed. **Fix (same shape)**: `CheckRestrictedImports` matched `rel == p` not `under()` — would go inert on
  any `internal/session/foo` split. `geminijson` moved to `internal/vendors/shared/`; **shared-only** carve-out (not same-tree siblings) + new
  rule 7. **Verification** re-introduced both. **Config**: 13 deployability vars added; `.env.example` now lists all 32 engine vars (was 2 of
  19) with a test. **Fix**: `BindFlags` advertised required-variable flags that couldn't satisfy them → `ResolveFlagOverrides`, explicit
  `flagEnvKeys` table. **Spike (live `gemini-3.1-flash-live-preview`)**: manual activity control works; input transcription fires with
  automatic VAD off; **audio sent outside an activity window is discarded silently** (no bytes/transcription/error). **Design (not build)**: a
  `[[DIRECTION]]` marker convention *causes* the leak it was meant to prevent (model emits fabricated spans); a plain parenthetical is obeyed
  and unspoken — no prompt change, no version bump. **Residual risk**: `OutputTranscriptDelta` is not guaranteed to equal what was spoken, and
  it feeds `max_sentences` and the grading ground truth. **Fix (this file)**: three headings dated 2026-08-24/25 (future) re-dated to
  2026-08-23.
* **M1.2 sample regeneration**: **Fix (silent contract-staleness)** — both `engine_contract_sample.json` files were still `v1.0` with all five
  v1.3 fields absent while `ENGINE_CONTRACT_VERSION` was `v1.3`; `--check` validated schemas only, so the pre-gate compiled empty, the ledger
  seeded zero beliefs, and `fakes.NewSampleContractSource()` served an unexercisable persona. `scripts/export_engine_contract_sample.py`
  regenerates both deterministically (proven by byte-diff on a double run); `export_schemas.py --check` now asserts the version matches and
  the fields are non-empty. `GEMINI_TTS_VOICES` Python mirror of Go `defaultTTSVoices` (30 voices, append-only — `pick_voice` is `hash %
  len`). v1.0 fixture retained as `engine_contract_sample_v1_0.json` + `TestParse_ToleratesAV1_0ContractAndDegradesToTheSingleModelPath`.
  **Fix (docs)**: `barge_in_allowed` vs `may_interrupt` now documented side by side.
* **M1.7 Judge adapter tests (`internal/vendors/judgellm`)**: 11 tests + a 25-case offline fixture that pins parsing and **explicitly does not
  measure real model judgement quality**. **Fix (hung not failed)**: `stallServer` parked on `Context().Done()` without reading the request
  body — `net/http` starts disconnect detection only after the body is consumed — so the handler outlived the test and `httptest.Server.Close`
  blocked; one `io.Copy(io.Discard, r.Body)`, reason recorded. **Fix (goroutine per turn)**: `reviewCtx()` spawned an uncancelled watcher per
  review → one Judge-lifetime context; `Close` closes `stop` **then** cancels. **Fix (silent gap)**: a vendor-unanswered review dropped with
  bare `continue` → `Failed()` counted separately from `Dropped()`. **Fix (select outran stop)**: `stop` now checked in its own non-blocking
  select first. `geminijson` gets its own tests including the **bounded read** (`io.LimitReader(1<<20)`; removing it consumes 32 MiB). **Fix
  (docs)**: the engine page called the dual-model fields a hypothetical v1.2 — they shipped as **v1.3**.
* **M1 — lint standard raised**: five linters added (`exhaustive`, `noctx`, `durationcheck`, `nilnil`, `predeclared`). `exhaustive`
  mechanically found the timer switch missing `timerStall` (three timers never armed → no abandonment/duration cap) and the command switch
  missing three cases. `default-signifies-exhaustive` deliberately off. **Fix**: `arch.LoadPackages` ran `go list` with no context (could hang
  CI on an unreachable proxy) → `CommandContext` 2-min. **Fix**: `RequireMinor`/`truncate` shadowed `min`/`max` builtins → `want`/`limit`.
  Note: `contextcheck` trialled, left off. The session findings are the spec for M1.6.
* **M1.5 — failable connect + Speaker event pump**: `DepsFactory` replaces the infallible `newDeps`; failure is **classified** —
  Speaker/Transport fatal, Transcriber/Thinker/StallBank each nil their field and record `degraded:*` (plan §11 degrade-don't-refuse). `POST
  /v1/sessions/{id}/transport` routed. `Transport.Accept` runs outside the connect budget. Pump split: `AudioDelta` to a drop-oldest ring,
  everything else never-dropped, every blocking send with a `ctx.Done()` escape (verified by re-introduction). **Fix**:
  `handleAttachTransport`'s fatal branch called `windDown` but the loop kept running.
* **M1.6 — the actor's dead code and wrong flags**: **Fix**: the greeting dead-ended every real session — SPEAKING's only exit is
  `ResponseDone` but the opening line is pre-synth audio, so none ever came (a hand-injected one hid it in tests). New `timerPlayout` armed
  for the clip's duration. **Fix**: `timerSilence`/`timerSession` now armed, so abandonment and the hard duration cap **exist for the first
  time** (zero means not-armed, not fire-immediately). `timerStall` **deleted** (dead three ways; its job is `timerThinker`'s). **Fix**:
  barge-in keyed off `voice_directives.may_interrupt` — the **opposite** meaning; `turn_policy.barge_in_allowed` was read nowhere. Both now
  read `barge_in_allowed`, gate applies across every speaking-ish state; the test helper sets `may_interrupt` **opposite** on purpose so a
  re-conflation fails. **Fix**: playout measured a sample count over one fixed rate → per-frame declared rate in microseconds. **Fix**:
  `handleSpeakerEvent`/`handlePartial` had no default (silent drops of `InputTranscript`/`ToolCall`/`SpeakerError`). Verification
  re-introduced every fix.
* **M2.1 — the sample domain (`internal/audio`)**: PCM16, a polyphase rational resampler, speech-onset detection, a receive jitter buffer, the
  send ring. 21 tests. **D7 measured, not asserted**: 87–88 dB SNR per rate pair, 111 dB rejection, p99 70 µs/frame against a 1 ms budget (the
  latency bound is a **test**). `tapsPerPhase` 64 and cutoff 0.45 Nyquist were arrived at by measurement. **Fix**: priming-history
  off-by-(K−1) produced a stable **wrong** answer (first SNR run −3 dB while continuity passed — only an absolute measurement catches it).
  Note: a later 14.2/23.7 dB reading was a measurement artefact (fractional group delay), the resampler was correct. **Design**: VAD onset is
  load-bearing, offset is the degraded fallback (D6 gives end-of-turn to the Transcriber); send ring drop-oldest + generation counter for O(1)
  barge-in; jitter buffer three frames, and a **dry** buffer is not a concealed loss. Verification: seven faults. **Fix (lint)**: nine gosec
  G115 → one `decodeSample`/`encodeSample` pair.
* **M2.2 — the WebSocket/PCM transport (`internal/transport/wsfallback`)**: a working media plane, 9 tests over a real socket, one dep
  (`github.com/coder/websocket`). It needs **no CGo and no ICE** (the fallback; raw PCM degrades into latency not glitches). Accept and attach
  are separate; tickets are **single-use** and expire. **Fix**: `MediaConn.Control()` returned one bidirectional channel (races its own
  consumer) → receive-only `Control()` + `SendControl`. **Fix (gosec)**: itemID length written as `byte(len(...))` truncated the identifier
  the browser echoes → checked two-byte field. **Design**: nothing on the audio path blocks (both directions shed and count). Verification:
  five faults. **Fix (tests)**: `defer goleak` ran before `t.Cleanup`'s close → registered goleak first with `t.Cleanup`. **Wiring**:
  smoke-tested — winds down fatally with `no speaker configured`, the honest state (media path, still no mouth).
* **M3 — the mouth, and the first end-to-end session (`internal/vendors/gemini`)**: Speaker over Gemini Live, 15 offline + the repo's first
  `//go:build live` tests; `geminitts` + `internal/stall`. **Decision (recorded reversal of D3)**: the adapter speaks the wire protocol
  directly, not the genai SDK (SDK needs Go 1.24, pulls gRPC/protobuf for a JSON WebSocket, and would leave two ways to call one vendor); the
  whole adapter runs against a local WebSocket offline. **Spike (live)**: a bare `activityStart` is how you cancel a response (no cancel RPC)
  — measured `interrupted` at 90 ms, zero further audio. **Guard**: one live session returned a 1050-char transcript with **zero audio** →
  `SpeakerError{Code:"silent_turn"}`. **Design**: per-turn ids minted by the adapter. **Fix**: a deadlock test used `CloseRead` (keeps
  draining) so it couldn't fail; rewritten, and the write queue that **blocked when full** now sheds. **Fix**: arch rule 5 flagged the bare
  `"models/"` prefix → requires something after the slash (verified it still bites). **Fix (three dead paths, found by running the binary)**:
  (1) nothing pumped the media conn into the actor; (2) `cmdInterviewerJoined` had no producer, so CONNECTING was terminal; (3) plan §11 row 4
  didn't exist — the energy detector now supplies the degraded-path boundary. **Fix**: GREETING was counted speaking-ish → the first word
  registered as barge-in and a `barge_in_allowed=false` persona never heard the first question. **Fix**: the connector marked the **Speaker**
  failed on any timeout, overwriting a Speaker that connected in 847 ms — a slow stall bank ended the interview and the log blamed the mouth.
  **Fix**: stall-bank warm was serial (blew the 15 s budget) → concurrent in contract order, one retry. **Fix**: the clip was never sent to
  the transport → sent as one frame (the ring is half a second, drop-oldest). **Result**: a live session runs end to end against the real
  binary and API — **7.1 s of persona audio captured off the wire** in the frozen voice. Bundle: the engine page corrected (no longer "no
  audio path"; documents what a session does and doesn't — no recording, every session `degraded:asr` — plus a live-verified vendor-facts
  section); `project-overview`, `checks` (SKIP vs NOT RUN), `test-suite` (the re-introduce-the-fault discipline), `repo-map` updated.

## 2026-08-23 (control plane, session recording)
* **Addition — browser-produced session recording** (voice only). Recorded in the **browser**, not the Go engine (`engine/internal/record/`
  and `store/s3/` are still `doc.go` stubs; building it there would record nothing). New table `session_recordings`, **`session_id` as primary
  key**, `status ∈ (recording,complete)`, `producer ∈ (browser,engine)` default browser, `channel_layout = 'manager_left_candidate_right'`.
  New port `RecordingStore` + composition `RecordingWorkflowStore` (fifth narrow port); `RecordingMeta` (`storage_key` deliberately not on
  it). Endpoints: `POST .../recording/chunks?seq=N` (`seq` must equal `next_seq`; 409 on wrong seq/finalized/non-voice), `.../finalize`
  (idempotent), `GET .../recording` (serves a **partial** — `status='recording'` is not a 404). Browser: a `ChannelMergerNode` puts mic left /
  persona right; `MediaRecorder` chunks every 10 s on its own ordered queue; teardown runs alongside, never gating, the transcript drain.
* **Decisions stated loudly (vetoable)**: bytes land on the operator's host in `RECORDINGS_DIR`, never a third party; the connecting screen is
  the consent event; retention is indefinite/manual; `GET` has no auth (the whole API is open — gating one would be theatre). Text sessions
  get no row (chunks → 409 by decision). Verified end to end against a running server. New: `contracts/session-recording.md`.

## 2026-08-26 (report engine)
* **Addition — `report_engine/`**, the standalone manager-assessment report engine, + `docs/REPORT_ENGINE_SCORING_SPEC.md`. Phases 1–5: bundle
  in, deterministic JSON + self-contained HTML out. No judge pass, no audio module yet. **It imports no first-party package** —
  `ALLOWED_IMPORTS["report_engine"] = set()`, the only such entry — the rubric **travels in the input bundle**; `scripts/make_bundle.py` does
  the importing.
* **Comparability is the persona, not the job card**: archetypes carry `must_discover` (weights summing to 1.0), the fixed denominator
  "comparable across 3,000 managers" needs; `discovery_attempted` is computed against it (surfaced vs asked-about are named differently on
  purpose).
* **New unit — the question act (`acts.py`)**: typed by rule in strict precedence (`leading > double_barrelled > behavioural > situational >
  closed > open_other`), probe-tagged by overlap, clustered into topics. No model call → reproducible counts.
* **Thresholds tagged `SOURCED`/`CALIBRATION`**. Three research results encoded against intuition: filled-pause rate rises with proficiency (r
  = −.08) so fillers are measured and **never scored**; Huffcutt & Arthur's Level III→IV gain is +.01 so probing is never penalised; the
  four-fifths rule is undefined for one interview so adverse impact is a cohort metric only.
* **Two operator toggles that break comparability (stamped on `Provenance`)**: `scoring_options.english_weight` (a float adds a fifth
  criterion, scales the four by `1 − w`) and `scoring_options.language_gate` (BRD **D-6** — refuse vs warn; the mix is always detected and
  reported).
* **Three invariants the tests enforce**: an unmeasurable signal carries `value=None` + a reason, **never** a zero; positive-only markers earn
  points and never cost them; **nothing caps or fails** (`test_the_rubric_has_no_critical_fail_gate`). Determinism asserted on JSON and HTML.
* Verified against a planted 27-turn session — readiness 60 "Developing". `tests/test_report_engine.py` (23 tests). New:
  `subsystems/report-engine.md`, `references/report-engine-spec.md`.

## 2026-08-26 (report engine, run against a real recording)
* **Change — four corrections, each found running on a real 5m15s voice session (`cooperative_trap`), invisible to a green offline suite**:
  1. **`discovery_attempted` was inverted for restraint personas** — `cooperative_trap`'s heaviest item (weight **0.40**) is *"Move back to the
     role without asking a single follow-up"*, so question-overlap credited the wrong behaviour. Items now classified ask-shaped vs restraint
     from `how_to_surface`; only ask-shaped counted, weights renormalise, and a persona with none reports the signal unmeasurable.
  2. **Question detection no longer trusts the question mark** (voice punctuation is the transcriber's guess — three real questions missed).
     Recovers auxiliary-fronted clauses and wh+auxiliary without punctuation. **8 of 8 found, zero false positives**.
  3. **OPEN→ASSESS boundary** now opens at the first question of any type (was: first *open* question).
  4. **`promotion_prevention_balance` no longer scored per session** (weight 0.0, value-only) — differential framing needs two candidates; cohort
     measure only.
* **Addition**: `fairness.py` `volunteered_detail_handling` (weight 2.0) — the deterministic counterpart to `cooperative_trap`'s trap; catches
  the well-meant follow-up. Read 1 of 1 on the real session.
* **Change**: `manager_talk_share` uses **speaking time** when turns carry `start_ms`/`end_ms`, else word share, and says which (the gap is
  itself a finding).
* **Addition**: `scripts/transcribe_recording.py` — stereo recording to speaker-labelled turns; each channel transcribed on its own (exact
  labels, the payoff of the channel split). Costs money, not in `check.sh`; reaches the vendor SDK directly (allowed only because `scripts/`
  is unscanned — belongs in `llm/` behind a port when the English module lands).
* **Validation vs independent ground truth**: the engine's path produced **42.0%** manager speaking time / 646 words against the earlier
  pipeline's 43.3% / 643 — agrees to 1.3 points (the number scored); absolute seconds differ (ASR lead-in padding). Real session: readiness
  **62 "Developing"**. 32 tests.

## 2026-08-26 (report in the console: generate, read, print)
* **Addition**: past sessions can be scored/read from the console — a new "Audio & report" column (`recordingUrl` was exported and wired to
  nothing until now) and a report button.
* **Addition**: `session_reports` — one row per session, `session_id` PK; headline + provenance (`readiness_index`, `band`, `scoring_version`,
  `rubric_version`, `english_weight`, `language_gate`) **denormalised out of the JSON**. New port `ReportStore` + composition
  `ReportWorkflowStore`. **The report is stored, not recomputed on read** — a threshold change must not silently move a discussed score;
  regenerating is an explicit `POST`.
* **Addition**: `control_plane/reporting.py` assembles the bundle (`report_engine` imports nothing first-party). **Composed personas carry
  ground truth too** — a `dyn-` persona has no catalog entry (raised on most sessions), but casting writes the same `must_discover` scorecard
  onto the candidate; `persona_block` reads catalog then candidate, returns empty rather than raising. Composed get no
  `session_beats`/`stresses`. Honesty fix in `signals/structure.py`: a composed persona's `how_to_surface` is written from the candidate's
  side, unmatchable by question overlap — the allowlist already excluded them, the printed reason was wrong.
* **Addition**: `POST /sessions/{id}/report` (generate/regenerate, toggles ride as query params into provenance), `GET .../report`, `GET
  .../report.html`. 409 when nothing was said; 404 unknown/ungenerated.
* **Decision — the console embeds the engine's HTML rather than re-drawing it** ("Download as PDF" is the browser printing that document; a
  second React layout would drift). `render.py` gains a print stylesheet. Server-side PDF (WeasyPrint / headless Chrome) considered and
  rejected.
* **Fix**: the table kept offering "Generate" for an existing report (parent doesn't refetch); `ReportView` reports back until the next real
  load. Verified against a running server on a copy of the real DB (incl. `english_weight=0.1` rescaling to 0.27/0.225/0.225/0.18+0.10). 38
  tests.

## 2026-08-26 (language gate: default reversed, detection corrected)
* **Reversal**: `scoring_options.language_gate` now defaults to **`false`** — a non-English session is **scored**, not refused. Production
  proved it: a real Frontline Sales session came back `NOT SCORED — language_unsupported` and the manager got nothing. The gate stays
  available, opt-in.
* **Addition**: `LANGUAGE_SENSITIVE` names the 22 signals computed from English lexicons/syntax; `_downgrade_for_language` marks any criterion
  carrying them **low confidence** with the affected share spelled out. The score stands; the claim about it changes.
* **Fix — a false positive that refused English sessions**: `the` was in the romanised-Hindi wordlist (Hindi *थे*) and is the commonest
  English word, so *"Walk me through the last time the store missed the target."* scored `hi-en` and was gated. Wordlists now disjoint
  (asserted); also removed *par, hum, ya, tha, ho, tum*.
* **Fix**: script detection covered only Devanagari — the triggering session was part **Urdu** (Arabic script). Now spans Arabic/Urdu,
  Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam.
* **Fix**: English share now computed from Latin-script tokens regardless of a script hit.
* **Fix**: `GET .../report` on an unknown session said "no report generated" not "session not found" (`_report_or_404` ran before the session
  lookup).
* **Fix**: `build-artifacts.sh` tars with `--no-xattrs` (macOS `com.apple.provenance` emitted ~130 warning lines into deploy output). 42
  tests.

## 2026-08-26 (the report gets its own screen)
* **Change**: the development report is now a **screen** (`App.jsx` `report` alongside `list`/`create`/`detail`/`session`), with its own
  breadcrumb and full viewport — it is a document read end to end, not a strip above a table. `InterviewDetail` no longer owns report state;
  leaving the screen refetches the session list so a row reflects the server, not a local guess.

## 2026-08-26 (audio analysis agent, and the report built from it)
* **Addition — `analysis_agent/`**, a new sibling (`llm ← analysis_agent ← control_plane`) that analyses a session's **recording**, not its
  stored transcript. Prompted by evidence: live STT rendered *"May I know what's your background?"* as *"May I introduce myself?"* — the audio
  is the source of truth.
* **The instructions are a shipped document** — `analysis_agent/INSTRUCTIONS.md`, versioned `v1.1`, read at runtime. Each observation type
  carries an explicit test (the sentence subject decides requirement vs protected-topic; **surfaced** requires the manager asked *and* the
  candidate revealed; a `how_to_surface` that says not to ask is a **restraint** item).
* **Decision — 60% how the manager handled *this persona*, 40% expectation coverage**, composed in code (the model never sees the weights).
  Coverage is scored against **reachable** items; `EarlyEndAssessment` separates a *judged close* (evidence, fair chance, civil exit) from an
  *abandoned interview* — the test is evidence-before-decision, not duration.
* **Windowing harness** — un-windowed, the model returned **21 of 53 turns ending after the recording did** (furthest 9m06s on a 5m46s file).
  Four-minute windows with code applying offsets; anchors validated against **their own window**; rejected ones surfaced as `dropped_anchors`.
  Windows run concurrently.
* **Addition**: `AudioModel` port + `GeminiAudioModel`. `AUDIO_PROVIDERS` deliberately partial (Gemini-only); `audio_analysis_available()`
  lets the UI hide the button. Fixed a bug where the new class stole the `@dataclass(frozen=True)` decorator from `RealtimeCredential`.
* **Addition**: `session_analyses` — one row per session, written **before** the work starts (so "running" ≠ "never asked"); a failure stores
  its reason. `POST /sessions/{id}/analyze` → **202**, background (~40 s); `GET .../analysis` polls; `.../analysis/full` for the body. Report
  generation 409s while analysis is running.
* **Addition**: the report now has two halves — `signals/assessed.py` marks `source="assessed"`, rendered **heard** vs the counted signals'
  **counted**; the language downgrade doesn't touch them. Moved Fair & Inclusive from **10.0** to **6.24** on the real session
  (household/salary questions asked in Hindi).
* **Addition — the basis panel**, printed on every report: counted vs heard, model + instruction version, languages heard, dropped anchors,
  and the caution that a clean counted-fairness result is not evidence nothing was asked.
* **Addition**: `ReportConfig` — perspective (`manager`/`coach`/`reviewer`) + skills; perspective changes person, never how hard it lands
  (Kluger & DeNisi task-vs-self). Configured skills replace the shipped competency pack.
* Verified end to end against a running server (complete at 38 s with `instructions_version`/`model_used`). 30 new tests. `analysis_agent`
  added to `PACKAGES`, `ALLOWED_IMPORTS`, mypy, `pyproject`, and **`infra/build-artifacts.sh`** — the omission that took the site down once
  already.

## 2026-08-26 (documentation: okf, README, and what a session costs)
* **Addition**: [`docs/PRICING_PER_SESSION.md`](/references/pricing.md) — measured by instrumenting a real 346 s recording: **5,592 prompt
  tokens/window + 31.9/s audio**, **2,137 output + 17.8/s**. Finding worth acting on: **the live voice call costs ~4× analysing it** (~$0.85
  vs $0.19 for 20 min) — the largest lever is the realtime model. Report generation calls no model and is free. The voice-call figure is the
  one estimate (a floor).
* New pages `subsystems/analysis-agent.md`, `references/{analysis-instructions,pricing}.md`. `README.md` — six steps now, opening with **the
  hiring manager is the one assessed, not the candidate**.

## 2026-08-27 (the report a manager can read, and the judge that writes it)
A hiring manager said the six-page, signal-table report was hard to read and supplied a two-page sample. This is that report.
* **Change (same day, after review)**: cut to **only** the four competencies, Q&A, strengths vs gaps, and areas to improve — **the readiness
  dial and summary paragraph left her pages** (both still computed/stored/stamped for spec §9 comparability, and print in the working). Two
  sections came back: **Q&A** (every question — time, verbatim, one tag) and **BEI questions** (behavioural asked vs those that came out as
  hypotheticals) — both views over `acts.classify` data, not a second opinion; `double_barrelled` prints as *two questions in one*.
* **Change**: the default render is **two pages**; the old view is `to_html(report, detail=True)` / `?detail=1` behind a **Show working**
  toggle. `detail` is a *render* argument, not stored, so the report stays a pure function of the JSON. The counted/heard split did **not**
  move behind the toggle — a one-line basis prints in every footer.
* **Addition**: `report_engine/narrate.py` — the summary, per-criterion narrative, and up to three bullets from `coach.py`.
* **Addition — spec phase 6, the judge**: `report_engine/judge.py` makes one structured call at temp 0.1, prose only;
  `report_engine/validate.py` decides what survives with **three vetoes** — a span must appear **verbatim**; a `surfaced: true` must be the
  *candidate* speaking after a manager question; prose states **no number** outside a quotation. A vetoed claim falls back to the composed
  sentence (costs polish, never a section). The spec's "manager question act in the same topic" is written down as **not** a check (topics are
  clustered from the manager's own questions — it would be a test that cannot fail). A surviving `must_discover` verdict becomes a
  `discovery_surfaced` signal (reaching the restraint items `discovery_attempted` excludes) and the report is **rebuilt** via
  `build_report(..., extra_signals=[...])`, not patched. `source` gains a third value, `judged`.
* **Decision**: the judge does **not** relax `ALLOWED_IMPORTS["report_engine"] = set()` (spec §10 assumed it would) — the model arrives as a
  `Protocol`, `reporting.py` does the wiring. **Consequence: the CLI cannot run the judge**, so `python -m report_engine` is always the
  deterministic report (also what the regression suite runs).
* **Change**: strengths and gaps capped at **three each** (down from four; Kluger & DeNisi), now a named constant.
* **Change**: `SCORING_VERSION` is **not** bumped (no threshold/transfer-function/weight moved; a judged report is separated by
  `judge_model`/`judge_version` on provenance, which spec §9's cohort rule already requires to match).
* **Addition**: `CriterionScore.narrative`/`.bullets`, `AssessmentReport.summary`/`.started_at`, `SignalResult.checklist`,
  `Provenance.judge_model`/`.judge_version`. Eight render tests + `tests/test_report_judge.py` (25 tests, drives `judge.overlay` without a
  model), wired into `check.sh`.
* **Change**: [pricing](/references/pricing.md) — report generation is no longer free; the judge is one call at **$0.005–$0.007**;
  **regenerating now costs money**, and `judge=false` is the free path.

## 2026-08-27 (deployed to prod, and the dependency that went with it)
* **Deployed**: the report work + three commits prod was behind, so `analysis_agent/` reached the instance for the first time (artifact over
  SSM, service restart, data volume untouched). The judge ran live on 9 regenerated reports: **no bare numbers, no unanchored quotes** — the
  veto holds on real output.
* **Fixed**: `AudioError: ffmpeg/ffprobe not found on PATH` — the deploy shipped the analysis agent to a box never provisioned for it, and
  **nothing in this bundle named the dependency**. AL2023 carries no ffmpeg, so `bootstrap.sh.tftpl` now installs the pinned static build
  (checksum-compared).
* **Correction**: `infra/README.md` opened "Nothing in this repository has been applied to AWS" — false since 2026-08-23; the state file is a
  live `prod`. It now warns that editing `bootstrap.sh.tftpl` changes `user_data`, and `user_data_replace_on_change = true` means the next
  `terraform apply` **destroys and recreates the instance**.
* **Known, pre-existing, not fixed**: `engined` has been crash-looping since first boot on 2026-08-23 — **61,762 identical failures**. In
  `-dev-sample-contract` mode it reads the sample from a path resolved at *build* time on the developer's laptop, a fixture that ships in no
  artifact. **Voice sessions have never worked on this instance.** Implementation-plan task 46 (no control-plane `ContractSource`), not a
  regression.

## 2026-09-01 (interviews that actually differ — contract v1.4)
* **Fix (the whole point of the product was leaking)**: **no job-spec field ever reached the persona's runtime prompt.**
  `_compile_system_prompt` took persona fields and skill names only — job title, JD, location, department, manager level and the interview's
  `clarity_facts` stopped at the interview row, so two interviews for different roles compiled near-identical prompts and opened the same way.
* **Change (contract v1.4)**: `_compile_system_prompt`/`build_engine_contract` gain `job_title`, `jd`, `company_type`, `experience_level`,
  `job_location_type`, `location` and emit a **THE ROLE YOU ARE INTERVIEWING FOR** section. **`ENGINE_CONTRACT_VERSION` v1.3 → v1.4** (prompt
  text changed ⇒ bump). Renders **only when `job_title` is non-empty**, so hand-built contracts, the handover sample and the Go fixtures
  compile byte-identically to v1.3 apart from the version string.
* **Decision**: the JD is truncated by **`jd_precis(jd, limit=400)` — code-owned, deterministic, no model call** (a model summary would make
  the same interview compile different bytes on every cast, which is what `ENGINE_CONTRACT_VERSION` pins). See
  [determinism](/concepts/determinism.md).
* **Change**: the **casting** prompt gains `location`, `department`, `manager_level`, `clarity_facts` (the model writes
  `opening_line`/`sample_phrases`/`background` and they are *stored* — anything it can't see is permanently missing). Empty scalars render
  `(not specified)`, empty checklist `(none)`, in code.
* **Fix**: `POST /sessions` cast with `expectation=None` and a hardcoded `interview_type="mixed"`, so the "Create & chat" path produced a
  **weaker persona than enrolling the same archetype**; it now reads `get_expectation(...)` and passes the whole job spec.
  `SessionWorkflowStore` gained `ExpectationStore` (mypy caught the composition didn't carry it; the port was widened, not bypassed).
* **Fix (UI)**: `Wizard.jsx` shipped a **fully pre-filled** job spec submitted unchanged (how identical interviews got created).
  `EMPTY`/`START_SKILLS` are now blank, the sample moved to placeholders. Corrected the false step-2 copy *"A different person of that type is
  cast each session"* — the opposite of how casting works and the thing that makes managers comparable.
* **Tests (offline)**: `test_two_job_specs_compile_two_different_system_prompts` (the regression for the whole bug), plus section ordering,
  the empty-`job_title` byte-identity guarantee, `jd_precis` determinism/sentence-boundary/hard-cut, and
  `test_starting_a_session_casts_with_the_stored_expectation_and_job_spec`.
* **Regenerated**: both schemas and both `engine_contract_sample.json` copies; the Go fixture's only change is `v1.3`→`v1.4` (pinned by
  `contract_test.go`). No engine code change — parses by **major**, v1.4 adds no field. Updated: `determinism`, `engine-contract`,
  `storage-ports`, two modules, three subsystems, `GO_ENGINE_CONTRACT.md`.

## 2026-09-01 (Gemini Live becomes the default talker; noise suppression and STT surfaced)
* **Change**: **Gemini Live (`gemini-3.1-flash-live-preview`) is now the default voice provider**, OpenAI Realtime behind
  `VOICE_PROVIDER=openai`. `llm/gemini_live.py` `GeminiLiveBroker` mints an ephemeral token via `auth_tokens.create` and returns it as
  `RealtimeCredential` with `call_url` **empty** (the Live API is a WebSocket the vendor SDK opens). `REALTIME_PROVIDERS` gained a gemini row
  **first**; `build_realtime_broker` falls back to `available[0]`, so **table order is behaviour** and is documented as such.
* **Decision (the seal)**: the *entire* session config — system instruction, voice, `responseModalities`, both transcriptions, VAD,
  resumption, history — goes into `CreateAuthTokenConfig.live_connect_constraints` (verified against `google-genai` 2.21.0). Constrained
  fields are enforced server-side for the token's life, so a browser still passing config on `live.connect` cannot override them;
  `lock_additional_fields` pins `temperature`/`top_p`/`top_k`. `uses=2` (the ~15-min audio cap makes one reconnect normal);
  `new_session_expire_time` 120 s so a leaked token can't start a fresh call later.
* **Decision**: the non-secret half travels to the browser as `client_config` (transcription toggles, VAD timings, `sessionResumption`,
  `historyConfig`) in the Live API's **camelCase wire names**, translated into typed SDK objects on the way into the token (SDKs stay inside
  `llm/`). Two tests assert the prompt and opening line are absent from it.
* **Fix**: **the voice path never delivered `opening_line`** — authored at cast, written as turn 0 in text mode, silently dropped in voice
  (every spoken interview opened with an improvised greeting). `build_voice_system_prompt` gained `opening_line` and appends a `THE FIRST
  THING YOU SAY` block for both providers. An instruction alone isn't enough (neither vendor speaks until something arrives), so each browser
  path nudges once (`openai` `response.create` on `onopen`; `gemini` one synthetic `sendClientContent`). **The nudge is never stored** — the
  transcript carries the persona's actual reply.
* **Change (seam split)**: `build_realtime_session` and `build_gemini_live_session` each emit their vendor's own document; a
  `_SESSION_BUILDERS` table dispatches (a lookup — `test_ocp_new_provider_needs_no_agent_change`). Shared are the *decisions* (same compiled
  prompt, opening line, persona voice, "the human can always interrupt"). New `session_facts()` reads the client-visible half back out, so
  `mint_realtime_credential` never branches on a provider name.
* **Change**: the 30-name voice roster moved to `llm.gemini_live.GEMINI_LIVE_VOICES` and `engine_contract.GEMINI_TTS_VOICES` **re-exports the
  same object** (`candidate_agent → llm` is the allowed direction). Order/membership unchanged, append-only (two copies of an order-sensitive
  tuple is exactly the drift `tts_voice_id` can't survive). The Gemini builder prefers the stored `tts_voice_id`.
* **Change (Phase C)**: `RealtimeCredentialResponse` gained `provider`, `stt_source`, `noise_reduction`, `client_config`; `call_url` defaults
  `""`. The OpenAI document gained `audio.input.noise_reduction: near_field`, an injected transcribe model (`TRANSCRIBE_MODEL`, default
  **`gpt-4o-transcribe`** — up from mini, the interviewer's words are half the evidence), and a transcription vocabulary `prompt` composed
  **in code** from `sorted(contract.knowledge_ceiling)`.
* **Change (UI)**: `@google/genai` **2.20.0** pinned exact (preview protocol). New `ui/src/geminiLive.js` and `ui/src/audio/pcmWorklet.js`.
  `VoiceSessionView.jsx` branches on `cred.provider`; **the recording graph is untouched**. Header shows a mic device picker and
  noise-suppression toggle; both swap the track live via `replaceTrack()`/`setStream()`. `getUserMedia` gained `autoGainControl` +
  `channelCount: 1`.
* **Decision (in code + OKF)**: **no client-side denoising.** Echo cancellation and AGC are non-negotiable and noise suppression is the
  operator's switch, but nothing between the mic and the recorder processes the signal — the raw recording is the evidence `validate.py`
  checks quotes against, and a rewritten recording is not evidence.
* **Fix (build)**: Vite inlined the capture worklet as a `data:` URL that `AudioWorklet.addModule` doesn't fetch reliably → a targeted
  `build.assetsInlineLimit` predicate forces that one file to a real asset.
* **Tests**: `tests/test_voice.py` extended (opening-line delivery + empty-contract fallback, injected transcriber, vocabulary hint,
  `near_field`, five Gemini compilation properties, dispatch, roster identity, `client_config` carrying neither prompt nor opening line). New
  `tests/test_gemini_live_mint.py` (`--live` smoke). `test_architecture.py` passes **unmodified**.
* **Change**: SkillBrew branding — real logo in `Shell.jsx` and as favicon. Asset-only.
* **Fix (docs)**: `infra/README.md` redeploy rewritten — a reboot doesn't redeploy (cloud-init `runcmd` is per-instance), a bare
  `bootstrap.sh` re-run leaves old processes serving; the sequence is build-artifacts → SSM `bootstrap.sh && systemctl restart control-plane
  engined`.
* **Fix (persona coherence)**: **a persona cast as a woman could speak in a man's voice** — `pick_voice` hashed over all thirty voices, so
  `gender_presentation` had no bearing on `tts_voice_id`. Three parts: (1) `GEMINI_FEMALE_VOICES` (14) / `GEMINI_MALE_VOICES` (16) frozensets
  recording the **vendor-documented** voice gender, living beside the roster, which they must partition exactly
  (`test_the_gender_sets_partition_the_roster`) and never reclassify; (2) `voices_for_presentation(voices, gender_presentation)` narrows to
  the matching subset **in roster order** (`non_binary`/`unspecified`/absent unchanged — no vendor-neutral subset exists); (3)
  `build_engine_contract` filters before `pick_voice`, only when `human_traits is not None`. `pick_voice` stays signature-stable (the
  no-traits fallback still resolves against the full roster).
* **Change**: `ENGINE_CONTRACT_VERSION` **v1.4 → v1.5** — the first bump where **the compiled prompt text does not change** (identical inputs
  now compile a different `tts_voice_id`, which neither `fingerprint` nor `seed_fingerprint` covers). No Go change (pins by major).
  **Already-cast personas are untouched** (`tts_voice_id` is written once at cast time). Byte-stability fixtures needed no update.
  `determinism` and `engine-contract` now state the general form of the bump rule.
* **Change (UI)**: **the voice session header no longer names our models** — it rendered `voice`, `model` and `stt_source` off the credential,
  an operator diagnostic a hiring manager was reading. Both lines removed (header is the persona label + *spoken interview*); `cred` and the
  API fields are kept because the browser needs them to connect, they are just never rendered. A sweep found no other user-visible
  vendor/model string.
* **Fix (the v1.5 gap, found in production)**: a persona named **Tanvi** spoke with a man's voice — v1.5's gender match only engaged when
  `human_traits` was present, and the **default** cast path has none (`enroll_candidates` casts `(key, None, None)`). Code can't close this
  alone (a name is not a gender table), so the split moves by exactly one field: `CANDIDATE_DRAFT_JSON_SCHEMA` gains **`presented_gender`**
  (`woman | man | neutral`, enum-constrained, `required`), asked as a description of the model's own output (rule 12); `casting_realism_note`
  requires it to match a stated `gender_presentation` and the name. `engine_contract.normalize_presented_gender` accepts only the three values
  and returns `""` otherwise, **never raises** (losing a whole cast over a voice hint is worse). Precedence is **code over model**:
  `human_traits.gender_presentation` wins where present. `agent.generate` reads the field, so neither cast site changed signature.
* **Change**: `PERSONA_VERSION` **v1.2 → v1.3** (`VirtualCandidate` gained `presented_gender`, pattern `^(woman|man|neutral)?$`, empty for
  every persona stored before v1.3; the declared value folds into `fingerprint`) and `ENGINE_CONTRACT_VERSION` **v1.5 → v1.6** (`tts_voice_id`
  moves again). No Go change.
* **Note on the tests (last round's nearly couldn't fail)**: the new cast tests run over **eight** interview ids whose unfiltered `pick_voice`
  results are mixed (3 male, 5 female); with a single id the `woman` case passed with the fix reverted (that id's unfiltered pick was already
  female). The test now also asserts `moved` (the filter changed at least one pick). Verified by reverting the precedence line.
* **Change (UI)**: the icon rail is single-product — four `disabled` "not part of this service" entries removed (a column of dead icons reads
  as broken); the logo and the one active icon stay.
* **Addition — silent failover to a second Gemini key**: `llm/failover.py` holds four wrappers
  (`FailoverStructuredModel`/`ChatModel`/`AudioModel`/`RealtimeBroker`), each holding one inner per key. **The wrapper *is* the port** (same
  interface, same `ModelError` contract) so nothing outside `llm/` knows it exists. `FALLBACK_API_KEY_VARS = {"gemini":
  ("GEMINI_API_KEY2",)}`; `build_*` wraps only when there's more than one key (single-key path returns the bare adapter).
* **Design notes**: (1) **only key-shaped failures retry** — `looks_like_a_key_failure` reads a 401/403/429 off the exception, then falls back
  to specific markers; a malformed request / 500 / 503 propagates on the first attempt. (2) **markers are deliberately specific** — the short
  "rate" is a substring of `generate_content` (in every Gemini failure's message); a test asserts that near-miss and `429` vs `4291`. (3)
  **stickiness is process-wide**, module-level (`build_model` is called per agent); `reset_preferences()` for tests. (4) each key is tried at
  most once, last failure raised unchanged.
* **Boundaries kept**: `API_KEY_VARS` still decides whether a provider is *configured* — reads only the primary, so `GEMINI_API_KEY2` alone is
  not a deployment (tested). Wrapping happens **after** the table lookup; `test_architecture.py` (which pins the vendor constructor
  signatures) is unmodified.
* **Change (infra, terraform only — nothing applied)**: `ssm.tf` gains `GEMINI_API_KEY2`; `iam.tf` needed no change (path-scoped);
  `bootstrap.sh.tftpl` reads it tolerantly. ⚠️ the bootstrap on the running instance is an **older render**, so prod pickup needs the
  hand-applied step. The **Go engine has no failover** — `GEMINI_API_KEY2` written into `engined.env` is inert there.
* **Addition**: `tests/test_key_failover.py` (29 tests, offline) + its `run` line (`test_every_test_file_is_wired_into_the_gate`).

## 2026-09-10 (naming cleanup: one concept, one name)
* **Change — a repo-wide rename with no behaviour change**, four names that taught a false model: * **`sessions.persona_key` → `archetype`**
  (stores exactly
`candidate.archetype`); `trait_dimensions.persona_key()` → `archetype_key()`. * **`interviews.candidate_notes` → `persona_notes`** (colour
on the archetype's casting prompt, never notes about a job applicant). * **`clarity_facts` / `ClarityFact` / `CLARITY_FACT_KEYS` →
`role_facts` / `RoleFact` / `ROLE_FACT_KEYS`** (the endpoint was already `POST /role-facts`). * **`clarity` the competency deliberately left
alone** — "Hiring with Clarity" is one of the four scored things, a *different thing* from the facts. `signals/clarity.py`, `rubric.py`'s
`id="clarity"`, the `stresses` key, `render.py`'s glyph, and the persisted signal id `clarity_fact_coverage` are all untouched (renaming
that id would be a data migration). The rename separates the **input** (facts) from the **competency**; over-applying it would re-merge
them. * `ANALYSIS_INSTRUCTIONS_VERSION` was **not** bumped — its rule is "bumped when INSTRUCTIONS.md changes what the model is asked to
do", and a noun swap does not (bumping would declare every prior analysis incomparable).
* **Change — `interview_assignments` reshaped** (zero rows/readers/writers, so a redesign not a migration): `interviewer_id` → `user_id` (the
  SkillBrew user id); `interviewer_type` + CHECK **dropped** (a leftover from the pre-pivot framing); `task_status` → `status`; new
  `candidate_id` carrying **no FOREIGN KEY** — like `sessions.candidate_id`, because a re-cast rewrites `virtual_candidates`' primary key in
  place via `ON CONFLICT ... DO UPDATE`. Index renamed to `idx_assignments_user`.
* **Change — `interviews.recording_id` dropped** (a recording belongs to a *session*; verified NULL in all 1788 rows of `control_plane.db`
  first). `started_at`/`completed_at` **stay**.
* **Addition**: `scripts/rename_columns_sqlite.py` — there are no migrations here, and `_SCHEMA` is `CREATE TABLE IF NOT EXISTS`, so a DDL
  rename is **invisible** to an existing database. The script is idempotent (skips already-renamed columns), refuses to drop `recording_id`
  unless NULL everywhere, **aborts** if `interview_assignments` is non-empty, and plans the whole migration before writing (Python `sqlite3`
  doesn't wrap DDL in a transaction). Both guards exercised against a copy of the real DB.
* **Verification**: `check.sh` green end to end; `export_schemas.py --check` clean; `npm run build` green; the migration run against
  `control_plane.db` and the API confirmed serving the renamed fields off migrated rows.

## 2026-09-10 (architecture rules that survive Postgres + S3)
* **Change**: `tests/test_architecture.py` re-cut so the rules keep biting after SQLite → Postgres + S3. The motivating rule
  `test_srp_generation_does_not_persist` asserted `"sqlite3" not in roots` — correct today, **silently inert** the day the adapter becomes
  psycopg (an agent could then import `psycopg`/`boto3` freely).
* **Addition**: `STORAGE_DRIVERS` (`psycopg`, `psycopg_pool`, `boto3`, `botocore`, `sqlite3`) and `STORAGE_ADAPTERS` — the only four modules
  allowed to import one: `control_plane/{database,repository,migrate,object_store}.py`. `test_dip_storage_drivers_only_inside_the_adapters` is
  parametrized over every module in every package. `migrate.py`/`object_store.py` are named before they exist (the allowlist needs no edit
  when the migration lands). Proved it can fail (a temporary import in `api.py` / `candidate_agent`).
* **Removal**: `test_srp_generation_does_not_persist` — both halves now enforced more widely (`sqlite3` by the driver allowlist; the
  `control_plane` import ban by `ALLOWED_IMPORTS` via `test_layering_respects_the_allowed_direction`). A comment records the trade so it isn't
  reintroduced as a gap.
* **Change**: `test_dip_handlers_depend_on_ports_not_the_sqlite_adapter` → `..._not_the_adapters`, broadened — it unparses every *parameter*
  annotation in `api.py` and rejects `InterviewRepository`, `ObjectStore`, `S3ObjectStore`, `FilesystemObjectStore` (so `Annotated`, dotted,
  and quoted forward refs are all caught). Return annotations exempt.
* **Change**: `test_isp_sqlite_adapter_satisfies_every_port` → `test_isp_postgres_adapter_satisfies_every_port`, and it no longer needs a
  database (built with `__new__`; the `:memory:` helper deleted). The suite's "no database, no network" promise is now literally true.
* **Fix**: `NARROW_PORTS`/`COMPOSITION_PORTS` were four/five entries behind `ports.py` — `AnalysisStore`, `ReportStore`,
  `AnalysisWorkflowStore`, `ReportWorkflowStore` were checked by nothing; all four added.
* **Verification**: 342 passed (was 268); ruff/mypy clean. `check.sh` deliberately **not** run — the tree is mid-migration. Updated:
  [Architecture](/concepts/architecture.md), [Conventions](/concepts/conventions.md).

## 2026-09-10 (the Postgres side, built beside SQLite)
* **Addition**: `control_plane/migrations/0001_initial.sql` — the whole schema as Postgres DDL. **Purely additive: the service still runs on
  SQLite** (`init_db`/`_SCHEMA`, `repository.py`, `api.py`, `main.py` untouched). Type mapping: JSON-bearing `TEXT` → `jsonb` (with
  `jsonb_typeof` CHECKs), `*_at` → `timestamptz`, `language_gate` → `boolean`, `byte_size` → `bigint`, non-negative CHECKs. Ids stay `text`
  (derived from a cast seed, not uuids). `CHECK (x IN (...))` over native enums (`ALTER TYPE ... ADD VALUE` can't run in the txn that reads
  the value). `interview_assignments` carried over.
* **The decision that matters — `sessions.candidate_id` gets no FOREIGN KEY** even though SQLite declared one (never enforced). Two shipped
  behaviours depend on the reference being inert: deleting a persona leaves its sessions readable as `"(deleted persona)"` with `POST /turns`
  answering 410 (a cascade would destroy the transcript, the evaluation layer's only evidence); and re-casting **rewrites** the primary key
  via `ON CONFLICT ... DO UPDATE`, which a referencing row would block. `interview_assignments.candidate_id` likewise. **Every other `ON
  DELETE CASCADE` becomes real.**
* **Addition**: `control_plane/migrate.py` — forward-only. `schema_migrations` created before the first read; `NNNN_name.sql` applied in
  ascending order, each in **one transaction that first takes `pg_advisory_xact_lock`** so two runners serialise. sha256 recorded on apply.
  CLI `python -m control_plane.migrate [--dsn] [--check]`, `--check` exits **0** current / **1** pending / **2** drift. **No down-migrations,
  by decision** (recovery is a restore plus a new forward migration; consequence: `CREATE INDEX CONCURRENTLY` can't live in a migration file).
* **Addition**: `database.py` gains `database_url_from_env()`, `spool_dir_from_env()`, `open_pool()` (`psycopg_pool.ConnectionPool`, 1–8,
  `dict_row`, `SET timezone TO 'UTC'`). **`autocommit=True` is deliberate and fully commented**: with it off, a read opens an implicit
  transaction, a later `with conn.transaction():` degrades to a SAVEPOINT that never commits, and the pool rolls the request back — the write
  vanishes with no error.
* **Addition**: `tests/infra.py` — one provisioning helper for `conftest.py` and `check.sh`; uses `TEST_DATABASE_URL`/`TEST_S3_*` when set,
  else starts throwaway `postgres:16-alpine` + `minio` with **Apple `container`** (Docker is not installed; `docker.io/...` is a registry
  hostname, not a runtime). It does not run `container system start` itself (a one-time kernel download) — an unavailable runtime raises
  `InfraUnavailableError` for the caller to turn into NOT RUN. MinIO provided now though its consumer lands next.
* **Addition**: `tests/conftest.py` — session-scoped `database_url` runs `migrate.apply` (so **every run exercises the migrations**) and drops
  at teardown. Isolation is `TRUNCATE ... CASCADE`, **not a database per test** (~1 s each would put the gate minutes behind the ~30 s bar).
  Every fixture is lazy, so offline suites still run with no database; the `init_db(":memory:")` suites are untouched (move with the
  repository switch).
* **Addition**: `tests/test_migrations.py` (18 tests) — apply to a fresh DB, the checksum, `--check`'s three exit codes, no-op re-apply, drift
  (edited/deleted applied file), pending, a mid-file failure recording nothing, and **the advisory lock serialising two concurrent runners**
  (the migration sleeps so the second thread is guaranteed mid-transaction). Plus the two FK decisions and the type mapping.
* **Change**: `check.sh` gains a Postgres block after the offline gates; infra comes up **once** for the whole run (torn down by a `trap`).
  Unavailable infra goes through **`missing()`, not `skip()`** — NOT RUN, failing the gate unless `ALLOW_MISSING_TOOLS=1`.
* Updated: [Database schema](/concepts/contracts/database-schema.md), [Test suite](/concepts/subsystems/test-suite.md),
  [Checks](/concepts/runbooks/checks.md), [Dev setup](/concepts/runbooks/dev-setup.md), [Repo Map](/concepts/repo-map.md).

## 2026-09-10 — the object store (port + two adapters)
* **Addition**: `control_plane/object_store.py` — the byte half of the storage boundary. `ObjectStore` (`put(key, source: Path, *,
  content_type)`, `open(key) -> ByteSource | None`) and `ByteSource` (`size`, `content_type`, `read(start, end)`), both `Protocol`. **`put`
  takes a path and `open` returns a stream — neither says `bytes`** (an hour of stereo Opus should not be held in memory).
  `FilesystemObjectStore` is the no-S3 dev default (production code; content type in a `<name>.content-type` sidecar to match S3's round
  trip). `S3ObjectStore` uses `upload_file` + `head_object` + ranged `get_object`/`iter_chunks`. `object_store_from_env()` picks by
  `S3_BUCKET`.
* **Decision — range semantics identical in both adapters** (one `_resolve_range`): inclusive both ends; an `end` past EOF is **clamped**; a
  `start` at/beyond EOF reads **nothing**; a negative bound **raises** (416 is the handler's decision, not the port's). Keys validated the
  same way, `..` included.
* **Decision — no `delete`** (retention is manual; a `delete` would be dead code someone wires up later without reading the decision).
* **Measured, not assumed**: a `head_object` **404 does not prove the object is missing** — a HEAD has no body, so botocore reports a bare 404
  for a missing *bucket* exactly as for a missing key (verified against MinIO); `open` confirms with `head_bucket` before returning `None`.
  boto3's multipart threshold is **8 MiB** (not S3's 5 MiB), so the suite uploads 9 MiB and asserts the ETag part count.
* **Addition**: `tests/test_object_store.py` (39 tests) — one behavioural set over both adapters + three S3-only facts; the S3 half runs
  against a **real MinIO** and **errors rather than skips** without one (18 passed / 21 errors on a machine with no object store).
* **Change**: `test_architecture.py` gains `test_isp_object_store_adapters_satisfy_the_port` (built with `__new__`; `S3ObjectStore.__init__`
  builds a client). `check.sh` uses `tests.infra up all` (adds MinIO); still `missing()`, not `skip()`.
* **Nothing is wired up yet** — `repository.py` still appends chunks straight to `RECORDINGS_DIR` and reads a whole recording into memory; the
  chunk → spool → finalize state machine S3 needs lands with the next work package.
* Updated: [Storage ports](/concepts/contracts/storage-ports.md), [Session recording](/concepts/contracts/session-recording.md), [Test
  suite](/concepts/subsystems/test-suite.md), [Checks](/concepts/runbooks/checks.md), [Repo Map](/concepts/repo-map.md).

## 2026-09-10 (Apple `container`: the kernel, and the port that only looked open)
* **The runtime needed a kernel, and its own downloader could not fetch one**: `container system kernel set --recommended` failed with
  `StreamClosed(... ProtocolError)` — an HTTP/2 transport fault. Refetching `kata-static-3.28.0-arm64.tar.zst` (596,775,193 bytes) with `curl
  --http1.1 --retry 10 --retry-all-errors -C -` ran at ~216 KB/s and completed; `container system kernel set --tar <file> --binary
  ./opt/kata/.../vmlinux.container` installed it from disk. The earlier "~2 KB/s" reading was the broken HTTP/2 path mistaken for the network.
* **Change (`tests/infra.py`)**: containers are no longer started with `-p`. Apple `container` 1.2.0 binds a host listener that completes a
  TCP handshake then drops the connection once a protocol exchange begins — `nc` calls the port open, `psycopg` gets "server closed the
  connection unexpectedly". The helper now reads `.status.networks[0].ipv4Address` from `container inspect` and talks to the container
  directly; `_free_port`/`_publish_specs`/`_looks_like_a_port_rejection`/`port_form_used` are gone.
* **Consequence**: a check that only opens a socket would have called this stack healthy — `_wait_for_postgres` connecting with psycopg is
  what caught it.
* `scripts/check.sh` is green end to end through Apple `container` with no `TEST_*` overrides: **26 gates PASS** (incl. `migrations
  (postgres)` and `object store (minio)`), `live model scenarios` SKIP by design. Updated: `test-suite`, `checks`.

## 2026-09-10 (the portal meets the control plane halfway)
* **Addition**: three additive changes so the SkillBrew organization portal can call this service from `localhost:3002` and its deployed
  origin, none altering a status code, response body or stored value the `ui/` console already sees. WP0 of
  `docs/INTERVIEWER_PRACTICE_PORTAL_PLAN.md` (decision D2).
  1. **CORS, off by default** — `cors_allowed_origins()` (`CORS_ALLOWED_ORIGINS`, comma-separated); `build_app` installs `CORSMiddleware`
     (`allow_credentials=True`) **only** when the list is non-empty. Unset installs nothing rather than a wildcard (the portal's browsers carry
     an org cookie).
  2. **An error envelope beside `detail`** — `install_error_envelope(app)` returns the same status and `detail` (the pydantic 422 list included)
     plus `status: false` and a `message`. Load-bearing for 409/422 (the portal's axios layer toasts `response.data?.message`). Registered on
     **starlette's** `HTTPException` (the 404 is enveloped too); 204/304 still carry no body.
  3. **A multipart door onto the recording chunks** — `POST /sessions/{id}/recording/chunks` now also accepts `multipart/form-data` with a
     `chunk` file field (the portal's axios can't send a raw `audio/webm` body). `_read_chunk` branches on content type (the raw path untouched);
     on multipart the *part's* content type is stored on `seq=0`. seq ordering / 409s / 422 are one path for both. `python-multipart` is now a
     dependency.
* **Test**: `tests/test_portal_compat.py` (13 tests, offline), wired into `check.sh`. Each assertion was confirmed to fail against a
  deliberately broken implementation first.
* `scripts/check.sh` green on Apple `container`: **27 gates PASS**, `live model scenarios` SKIP by design. Updated: `rest-api`,
  `session-recording`, `control-plane-api`, `control-plane`, `test-suite`, `checks`, `dev-setup`.

## 2026-09-11 (OKF made current, and log.md compressed)
* **Update**: refreshed the two stale spots the recent work left. [Project overview](/concepts/project-overview.md) build state (was dated 2026-08-27): the storage line now records that a **PostgreSQL** schema and an **object-store port with two adapters** (filesystem + S3/MinIO) exist beside SQLite and are exercised by `check.sh` under Apple `container`; a new **Consumers** line records that the **SkillBrew Organization portal** (separate repo) is now a second HTTP consumer of this control plane, behind the CORS/envelope/multipart compatibility layer. [Model providers](/references/model-providers.md): added the operational trap that the `gemini-3.7-flash` default rate-limits (`429`/`503` → `502`) under sustained load, that a `429` fails over but a `503` does not, and that the fix is config-only — pin `LLM_MODEL`/`<ROLE>_MODEL` and give the deployment a real-quota key. Measured live 2026-09-11 while debugging voice: primary key `403` project-denied, fallback key free-tier `429`; moving the default off 3.7-flash to `gemini-3.5-flash` restored typed and spoken sessions until the fallback key's per-minute quota was exhausted.
* **Optimize**: this file was **1397 lines / ~29,300 words / 210 KB** — the single biggest file in the bundle and ~15% of it. Compressed to **~700 lines / ~10,000 words / 79 KB** (word count to 34% of the original). August history, superseded by the concept pages, was cut hard; the ten tiny `2026-08-23` engine-milestone entries were collapsed into one `## 2026-08-23 (engine, phases 0–4 — build milestones)` section that keeps each milestone's decision/fix/gap and points to [Live-session engine](/concepts/subsystems/engine.md). September entries were trimmed lightly. Preserved intact: every dated section header, every carried-forward decision, every not-built / not-tested / not-enforced gap note, every version bump (`ENGINE_CONTRACT_VERSION`, `PERSONA_VERSION`, catalog, scoring/analysis), and every named regression test. No code changed; documentation only.

## 2026-09-12
* **Change**: `owner_handover/` is now ignored and untracked (`git rm -r --cached`, rule in `.gitignore`). The 18 schema/sample JSON files are regenerated by `scripts/export_schemas.py`, so a fresh checkout must run it before `scripts/check.sh` (the `--check` step reports every file stale when the directory is absent). `docs/` stays tracked. See [OKF maintenance](/concepts/runbooks/okf-maintenance.md).
