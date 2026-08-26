# Report Engine — Deterministic Scoring Specification

**Status:** design for review. No code written.
**Scope:** a standalone report-generation engine that turns one completed
session into a manager development report.
**Assessed subject:** the hiring manager. Never the candidate.

---

## 0. What "deterministic" has to mean here

Re-running the engine on a stored session must produce **byte-identical
numbers**. That forces a hard split, which is the organising rule of this
document:

| Owned by code | Owned by the model |
|---|---|
| Every count, ratio, rate and threshold comparison | Reasoning prose for a criterion |
| Every sub-score, criterion score, and the Readiness Index | Quote *selection* from the transcript |
| Segment boundaries, question-act extraction and typing | "Done well" / "focus area" wording |
| Confidence downgrades and "not measurable" verdicts | Whether a `must_discover` signal was surfaced (evidence-bound, see §6) |
| The recommended next persona | — |

The model never emits a number. Not one. Where reading comprehension is
genuinely required (§6), the model returns a **boolean plus a verbatim evidence
span**, and code rejects the boolean if the span is not found verbatim in the
transcript. That keeps the arithmetic reproducible even where the judgment is not.

### Threshold honesty

Every threshold in this document is tagged:

* **`SOURCED`** — the number comes from published research or a named industry
  dataset, cited inline.
* **`CALIBRATION`** — the *metric* is research-backed but the *cut point* is
  not published. It ships as versioned configuration with an engineering-judgment
  starting value, and is expected to move once cohort data exists (§9).

Most cut points are `CALIBRATION`. Pretending otherwise would be the single
easiest way to make this report indefensible to a manager who disagrees with it.

---

## 1. The comparability mechanism — why this works at all

The BRD requires scores comparable across ~3,000 managers. Comparability cannot
come from the job card, which varies per role. It comes from **the persona**.

`candidate_agent/archetypes.py` already gives every archetype:

```python
must_discover: list[ScorecardSignal]   # weights sum to 1.0
session_beats: list[str]               # the scripted moments, in order
interviewer_failure_modes: list[str]
stresses: dict[str, int]               # criterion -> 1..4
```

Two managers who face `inflated_resume` are handed the **same four things to
discover, at the same weights, with the same scripted deflections at the same
points**. That is a fixed denominator — a controlled instrument rather than an
open-ended conversation. It is the closest thing in this design to a validated
test, and every other signal is secondary to it.

Consequence for the report: the headline is *"you surfaced 65% of what this
candidate was hiding"*, not *"you asked 7 open questions"*.

---

## 2. Input contract — `SessionBundle`

The engine is standalone: one JSON in, one report out. It reads no database and
holds no session state.

```jsonc
{
  "bundle_version": "v1",
  "session":  { "session_id", "manager_id", "modality": "text|voice",
                "started_at", "ended_at", "planned_minutes", "end_reason" },
  "job_card": { "job_title", "summary", "role_family",
                "clarity_facts": [{"key", "statement"}] },
  "persona":  { "archetype_key", "label", "must_discover": [...],
                "session_beats": [...], "stresses": {...},
                "disruption_turn": 12 },
  "turns":    [{"index", "speaker": "manager|candidate", "text",
                "elapsed_ms", "start_ms": null, "end_ms": null}],
  "events":   [ ... ],        // voice only; barge-in, VAD, stall
  "rubric":   { ...Rubric... },
  "jurisdiction": "IN",       // drives the protected-topic pack, §5.C
  "recording": { "path": "…/{session_id}.webm",
                 "channel_layout": "manager_left_candidate_right",
                 "status": "complete|recording" },   // null in text sessions
  "scoring_options": {
    "english_weight": null,   // null = advisory only; a float = weighted, §4.1
    "language_gate": true     // §3.4
  }
}
```

**The rubric travels in the bundle.** `tests/test_architecture.py:41` forbids
sibling agent packages importing each other, so a standalone `report_engine/`
cannot import `evaluation_agent.rubric`. Copying it would mean a *second*
duplicated declaration policed by a drift test — the repo already pays that price
once (`test_rubric_vocabulary_agrees_across_the_two_agents`). Passing it as
input costs nothing and keeps the rubric org-owned configuration, exactly as
`rubric.py` intends.

### Modality honesty

`start_ms` / `end_ms` are `null` in text mode. Every signal declares
`text | voice | both`. A voice-only signal in a text session returns
`value: null, reason: "not measurable in a text session"` — never a zero. This
is already the standing rule in the pivot plan §4 and it is load-bearing: a
fake zero silently penalises a manager for the modality they were given.

---

## 3. Deterministic pre-processing

### 3.1 Segmentation

The session is cut into four segments by rule, because talk-time and question
mix mean different things in each (see §5.D — interviewer talk legitimately
spikes at the open and close):

| Segment | Boundary rule |
|---|---|
| `OPEN` | turn 0 → the first manager question act classified as competency-probing |
| `ASSESS` | → the first manager turn matching the invite-questions cue |
| `CANDIDATE_Q` | → the first manager turn in the closing cue set |
| `CLOSE` | → end |

Missing boundaries collapse gracefully: no invite cue means `CANDIDATE_Q` is
empty and `S15` (§5.B) records "never invited".

### 3.2 The unit of analysis: the question act

Turns are too coarse — one manager turn routinely contains a preamble, a
question, and a second question. The engine extracts **question acts**:
sentences in manager turns that either end in `?` or open with an elicitation
cue (`tell me`, `walk me through`, `describe`, `explain`, `give me an example`).

Each act carries: `type`, `is_probe`, `probe_depth`, `topic_id`,
`protected_topic`, `segment`, `turn_index`, `char_span`.

### 3.3 Question typing — rules, not a model

Applied in strict precedence order (a leading behavioural question is still
leading):

1. `leading` — tag questions (`, right?`, `, correct?`, `, don't you?`), embedded
   premise (`So you're not…`, `I assume you…`, `Surely you…`, `You probably…`)
2. `double_barrelled` — two `?` in one sentence, or two wh-clauses coordinated by `and`/`or`
3. `behavioural` — past-behaviour cue (`tell me about a time`, `describe a situation where`,
   `give me an example of when`, `walk me through a time`) with past-tense main verb
4. `situational` — `what would you do`, `how would you handle`, `imagine`, `suppose`, `if you were`
5. `closed` — opens with an auxiliary/modal (`do/did/does/are/is/were/have/has/can/could/will/would/should`)
6. `open_other` — opens with a wh-word or elicitation cue

`is_probe` is true when the act's lemmatised content-word overlap with the
immediately preceding candidate turn exceeds θ (**`CALIBRATION`**, start 0.10),
**or** it matches an explicit probe cue (`you said`, `you mentioned`, `what exactly`,
`which one`, `what was the number`, `what was your part`). `probe_depth` counts
consecutive probes within a `topic_id`.

**Known limitation, stated up front:** every rule above is English-only and
assumes reasonably clean punctuation from ASR. See §3.4.

### 3.4 The language gate — `scoring_options.language_gate`

BRD **D-6** flags that frontline Airtel interviews are frequently Hindi or
Hindi-English code-mixed, which breaks question typing, the protected-topic
lexicon, STAR extraction and filler detection *simultaneously*.

The engine **always** detects and reports the language mix of manager turns —
`detected_language`, `english_token_share`, `confidence`. Visibility is not
optional. The flag controls only what happens next:

| `language_gate` | Behaviour when `english_token_share` < 0.85 (**`CALIBRATION`**) |
|---|---|
| `true` (default) | Return `unscoreable: language_unsupported`. No numbers produced. |
| `false` | Score anyway, stamp `validity_warning: language` on the report and on every affected signal. |

Turning the gate off does not make the numbers valid; it makes them *available*.
The report must say so on its face, because a confidently wrong score is the
worst failure mode this engine has.

---

## 4. Scoring mathematics

```
sub_score(signal)  = transfer(raw_value)            -> 0..10
criterion_score    = Σ(sub × w) / Σ(w)  over MEASURABLE signals only
readiness_index    = round(10 × Σ(criterion_score × criterion.weight))   -> 0..100
band               = rubric.band_for(readiness_index)
```

Transfer functions are declared per signal and are the only place a raw number
becomes a score: `linear_up(lo,hi)`, `linear_down(lo,hi)`, `band([...])`,
`boolean(true_score,false_score)`, `hit_rate` (identity ×10), `penalty_count(step)`.

**Unmeasurable signals are dropped and the remaining weights renormalised** —
never scored as zero. If a criterion's measurable weight falls below 50% of its
total, `confidence = low` and the report says which signals were missing and why.

**No gates, no caps.** `test_the_rubric_has_no_critical_fail_gate` already
guards this and the design does not challenge it: a protected-topic hit lowers
the Fair & Inclusive score and raises a prominent flag, but it does not cap or
fail anything.

### 4.1 `english_weight` — the operator's toggle

`scoring_options.english_weight` decides whether English proficiency reaches the
Readiness Index:

* **`null` (default)** — §5.E is computed and printed as an advisory panel.
  The four rubric criteria keep their weights exactly as `rubric.py` declares them.
* **a float `w` in (0, 1)** — a fifth criterion `communication_english` enters at
  weight `w`, and the four existing weights are scaled by `(1 − w)`. Proportional
  scaling preserves their relative ordering, so the org's rubric decision is not
  silently re-ranked by a toggle. Proposed starting value **w = 0.10**
  (**`CALIBRATION`** — org-owned, exactly like the rubric itself):

  | Criterion | `null` | `w = 0.10` |
  |---|---|---|
  | Structured Interviewing | 0.30 | 0.270 |
  | Hiring with Clarity | 0.25 | 0.225 |
  | Fair & Inclusive | 0.25 | 0.225 |
  | Communication & Presence | 0.20 | 0.180 |
  | Communication & Presentation (English) | — | 0.100 |

**A weighted-English report is not comparable to an unweighted one.** That is
the whole product premise (§1, §9) and a per-report toggle can break it silently.
Two consequences, both non-negotiable in the implementation:

1. `english_weight` is stamped on every report alongside `rubric_version` and
   `scoring_version`.
2. The cohort dashboard **segments on it** and refuses to average across
   settings. A cohort mixing both is shown as two cohorts.

Recommendation: set it once per training programme, not per session. It is
offered per report because you asked for it; it is safest used as a
programme-level decision.

**If the recording is missing** (text session, browser without `MediaRecorder`,
failed upload) and `english_weight` is set, the criterion is `unmeasurable` and
its weight is redistributed by the normal §4 rule. A manager is never penalised
for audio their browser failed to upload.

---

## 5. The signal set

### 5.A — Structured Interviewing (rubric weight 0.30)

Evidence base: structured interviews validate at **r = .42 vs ~.19 unstructured**
(Sackett, Zhang, Berry & Lievens 2022, *JAP* — the modern re-correction; structured
interviewing is now the single best predictor of job performance, ahead of GMA at .31).
Earlier estimates: .51 vs .38 (Schmidt & Hunter 1998), .44 vs .33 (McDaniel et al. 1994).
Huffcutt & Arthur (1994) show validity climbing **.20 → .35 → .56 → .57** across four
structure levels — note the Level III→IV gain is only **+.01**, so banning follow-ups
buys nothing. Probing is not the enemy of structure.

| id | Signal | Mode | Formula | Transfer | Basis |
|---|---|---|---|---|---|
| S1 | `discovery_score` | both | Σ `must_discover[i].weight` × surfaced(i) | hit_rate | §1, §6 — **primary structure signal** |
| S2 | `behavioural_share` | both | behavioural / all question acts | linear_up(0, 0.40) | Direction `SOURCED` (past-behaviour r=.56 vs situational .45, Taylor & Small 2002); cut point `CALIBRATION` |
| S3 | `probe_rate` | both | probes / root questions | linear_up(0, 1.0) | Direction `SOURCED` (cognitive-interview meta-analysis, Memon, Meissner & Fraser 2010: large gain in correct detail, no rise in confabulation); cut `CALIBRATION` |
| S4 | `beat_response_rate` | both | scripted `session_beats` that drew a probe within 2 manager turns | hit_rate | Ground-truth denominator, §1 |
| S5 | `star_result_rate` | both | behavioural answers reaching **R** / behavioural questions asked | linear_up(0, 0.6) | `CALIBRATION`. STAR-completeness is a **practitioner construct (DDI)**, not a validated mediator — no study found. Report it, do not over-weight it |
| S6 | `closed_share` | both | closed / all question acts | linear_down(0.35, 0.70) | Direction `SOURCED` (open questions yield longer, more accurate answers — Oxburgh, Myklebust & Grant 2010); cut `CALIBRATION` |
| S7 | `leading_count` | both | count of `leading` acts | penalty_count | `SOURCED` direction (Snyder & Swann 1978 — confirmatory questioning *manufactures* confirming behaviour) |
| S8 | `competency_coverage` | both | role-family competencies touched by ≥1 act | linear_up(0.4, 1.0) | `SOURCED` (Campion, Palmer & Campion 1997, component #1: job-analysis-based content) |
| S9 | `question_count` | both | distinct root questions | band | `SOURCED` direction (Campion component #5: more questions = better behaviour sample); cut `CALIBRATION` |

**Deliberately excluded from the per-session score:** *question consistency
across candidates* and *plan-order adherence*. These are Campion component #2
and the main driver of the .35 → .56 validity jump — the strongest structure
levers in the literature — but they are **mathematically undefined for a single
session**, and the manager-assessment model has no planned question list to
adhere to (the `expectation_agent` that once produced one is retired in pivot
Phase 2). They belong on the cohort dashboard (§9), comparing one manager across
sessions. Putting them in the per-session score would mean inventing a plan the
manager was never given.

### 5.B — Hiring with Clarity (rubric weight 0.25)

Evidence base: realistic job previews reduce voluntary turnover (**r ≈ −.06**,
small but reliable — Phillips 1998, *AMJ*), and the mechanism is **perceived
organisational honesty** rather than met expectations, with **face-to-face oral
previews outperforming written or video** (Earnest, Allen & Landis 2011, *Personnel
Psychology*, 52 studies / ~17k people). Candidate-facing information and
explanation is also a procedural-justice driver predicting offer acceptance
(Hausknecht, Day & Thomas 2004, 86 samples, N = 48,750).

| id | Signal | Mode | Formula | Transfer | Basis |
|---|---|---|---|---|---|
| S10 | `clarity_fact_coverage` | both | facts conveyed / facts with a non-empty `statement` | hit_rate | The spec's "4 of 5". Already modelled in `evaluation_agent/schema.py` |
| S11 | `candidate_question_answer_rate` | both | candidate questions substantively answered / asked | hit_rate | `SOURCED` (Hausknecht et al. 2004 — information provision) |
| S12 | `agenda_set` | both | agenda/duration stated in `OPEN` | boolean | `SOURCED` construct (Campion; BrightHire ships "agenda set" as a scored signal) |
| S13 | `next_steps_stated` / `timeline_stated` | both | closing cue detection in `CLOSE` | boolean | `SOURCED` (Hausknecht procedural-justice facet) |
| S14 | `downside_disclosed` | both | any utterance previewing a hard part of the role | boolean | `SOURCED` (Earnest et al. 2011 honesty mechanism) — **positive marker only** |
| S15 | `invite_questions_fraction` | both | elapsed fraction at first invitation | linear_down(0.6, 1.0) | `CALIBRATION` |

Note a genuine tension: Campion component #7 recommends *deferring* candidate
questions until after assessment, while candidate-experience research rewards
inviting them. The engine scores **whether they were invited and answered**, not
when — except that never inviting them is penalised.

### 5.C — Fair & Inclusive (rubric weight 0.25)

| id | Signal | Mode | Formula | Transfer | Basis |
|---|---|---|---|---|---|
| S16 | `protected_topic_hits` | both | matched acts by category | penalty_count | `LEGAL` — see pack below |
| S17 | `bias_bait_handled` | both | scripted volunteered-personal-detail beats routed correctly | hit_rate | Ground truth from `session_beats` |
| S18 | `confirmatory_ratio` | both | leading acts with valence / all acts | linear_down | `SOURCED` (Snyder & Swann 1978) |
| S19 | `promotion_prevention_balance` | both | promotion-framed vs prevention-framed acts | band | `SOURCED` metric (Kanze, Huang, Conley & Higgins 2018, *AMJ*: investors asked women prevention-framed questions ~2:1; each extra prevention question ≈ **$3.8M less raised**). **Per-session it is descriptive only** — differential framing needs two candidates to be a bias claim |
| S20 | `accommodation_offered` | both | adjustment/accommodation offer detected | boolean | **positive marker, never a penalty** |
| S21 | `name_confirmed` | both | name-pronunciation check detected | boolean | **positive marker only.** `INDUSTRY` evidence only (NameCoach/Race Equality Matters surveys); no outcome study found |
| S22 | `intrusive_interruption_rate` | **voice** | intrusive interruptions per candidate speaking-minute | linear_down | `SOURCED` (Zimmerman & West operational definitions; Anderson & Leaper 1998 meta-analysis, 43 studies: intrusive-interruption **d = .33**) |

**Interruption definition** (Zimmerman & West; modern voice-AI barge-in
practice): an **overlap** starting in the final syllable of a turn is benign
turn-taking. **Backchannels** (`mm-hmm`, `right`, `okay`, `sure`) are *not*
interruptions. An **intrusive interruption** is manager speech starting >500 ms
(**`CALIBRATION`**) before candidate turn-end, lasting >1 s, where the candidate's
turn terminates or the topic shifts. Reported as a *rate*, never a raw count.

**Protected-topic pack — versioned configuration, not code.** Categories: age /
graduation year, marital status, children & family planning, pregnancy, national
origin & "where are you really from", religion & observance, caste / community /
native place, disability & health, genetic & family medical history, gender-role
assumption ("will your family allow", "can you adjust"), criminal history,
salary history.

Jurisdiction matters and moves:
* **UK Equality Act 2010 s.60** bans health/disability questions *pre-offer*
  outright — the single most cleanly detectable rule anywhere.
* **US** — under federal law the *question* is usually not per-se illegal; it is
  strong evidence of discriminatory intent. The engine's category is therefore
  **"unlawful or high-risk inquiry"**, never "illegal question".
* **Salary history** — banned in 22 US states + ~23 localities (HR Dive tracker,
  as of 2026-04-28). **Ban-the-box** — 37 states + ~150 localities.
  Both are date-sensitive and ship as dated config with a review date.
* Launch jurisdiction here is **India / Airtel**, so the Indian pack (caste,
  community, native place, marital status, family-permission framing) is the one
  that matters first. The BRD's own detector list already names these.

**Adverse impact is not a per-session metric.** The EEOC four-fifths rule
(29 CFR §1607.4(D)) compares *selection rates across groups of applicants*. It is
mathematically undefined for one interview. It belongs on the cohort dashboard
(§9) and nowhere else.

**Regulatory note for the product, not the score:** NYC Local Law 144 (bias
audit, enforced since 2023-07-05), Illinois AIVI Act (2020-01-01, video-interview
notice/consent/deletion), and the EU AI Act's high-risk employment classification
all govern AI used in *employment decisions*. This engine scores the interviewer
for training, which is arguably outside that — but "arguably" is not a compliance
position, and D-8 (does a manager's report reach their reporting line?) decides
it. If reports go to a manager's boss, this becomes an evaluation system and the
regulatory surface changes.

### 5.D — Communication & Presence (rubric weight 0.20)

| id | Signal | Mode | Formula | Transfer | Basis |
|---|---|---|---|---|---|
| S23 | `manager_talk_share` | both | `ASSESS` segment only. Voice: speech-seconds. Text: word share (degraded, labelled) | band | See below |
| S24 | `longest_monologue` | both | longest single manager turn | linear_down | `INDUSTRY` (Gong ships it) |
| S25 | `compound_question_rate` | both | double-barrelled / all acts | linear_down | Rubric text: "clear single questions, no compounds" |
| S26 | `greeting` / `self_intro` | both | cue detection in `OPEN` | boolean | Rubric text; BRD C4 |
| S27 | `composure_at_disruption` | both | manager response to the scripted disruption turn | evidence-bound (§6) | Persona ground truth |
| S28 | `wpm`, `filler_density`, `pause_profile` | **voice** | — | **ADVISORY, NOT SCORED** | Wizard spec line 448: "Advisory: pace & fillers — Shown, never scored" |

**Talk-share bands.** There is **no peer-reviewed optimal interviewer:candidate
ratio for selection interviews** — I searched and it does not exist. The only
quantified sources are industry: Gong's 25k+ sales calls put the ideal rep
talk-share at **~43%** with win-rates falling off past ~65%; BrightHire's
hiring-specific guidance is **~20% interviewer / 80% candidate**. Proposed bands
(**`CALIBRATION`**, `ASSESS` segment only): full marks 20–40%, linear decay to
45%, flagged above 65%. `OPEN` and `CLOSE` are excluded because that is where
role-clarity behaviour lives and manager talk *should* spike — penalising it
there would score S12–S14 twice, once as a positive and once as a negative.

### 5.E — Communication & Presentation (English)

**Two outputs, not one.** The question "can this manager be understood" and the
question "what is their CEFR level" are different measurements with different
evidence bases, and only the first is what a trainer usually needs:

| Output | What it answers | Scale |
|---|---|---|
| `intelligibility` | Was the manager understandable? | 0–100 |
| `cefr_band` | Placement against the CEFR speaking scales | A1–C2 + adjacent range |

Both are computed. Whether either reaches the Readiness Index is
`scoring_options.english_weight` (§4.1). When weighted, the criterion score is
driven by **`intelligibility`**, with `cefr_band` reported beside it — a band is
a placement, not a performance, and banding someone's first language against an
L2 framework is not a fair basis for a development score.

#### Source: the stereo recording, not new engine work

`okf/concepts/contracts/session-recording.md` — the browser already records
**stereo, `channel_layout = "manager_left_candidate_right"`**, built with a
`ChannelMergerNode` in `ui/src/VoiceSessionView.jsx`: manager's mic on channel 0,
persona's WebRTC track on channel 1. That is sufficient for everything below:

* **Speaker separation is free** — split the channels. No diarisation, no
  turn-alignment, no server clock.
* **Pause structure** — VAD the left channel at frame resolution.
* **Word-level timings and clause anchoring** — forced-align the known manager
  transcript against its own channel. Because text and audio come from the same
  speaker's isolated channel, this needs no shared timeline with the transcript's
  `elapsed_ms`, so the recording/transcript clock drift is irrelevant.

The engine's future stereo WAV (48 kHz PCM, zero-filled gaps, drift-corrected)
would be *better* input, and this module reads it unchanged when it arrives —
`producer` on `RecordingMeta` is already the seam. It is not a prerequisite.

**Cost of this decision, stated plainly:** the report engine gains an audio
dependency (Opus/WebM decode, VAD, forced alignment) that the rest of the repo
does not have. That is real scope and it is the reason this module is last in
the build order (§12).

#### When it is absent

Not degraded — absent, with the reason printed:

* text session (no recording exists, by design — `POST .../chunks` is a 409)
* browser without `MediaRecorder` support for `audio/webm;codecs=opus`
* failed or partial upload — the contract explicitly keeps partials playable
* under the reliability floor: **< 3 minutes of manager speech** (rate measures
  stabilise around 3 min) or **< 100 tokens** (MTLD's floor)

#### `intelligibility` — the primary measure

`SOURCED` construct. This is what the commercial systems actually mean by
pronunciation scoring: Duolingo's DET technical manual defines its Pronunciation
subconstruct as the acoustic model's transcription confidence; ETS SpeechRater
v1 used ASR acoustic and language-model confidence among its ~40 features;
Versant scores "stress and segmental forms of words in phrasal context".

Computed as mean per-word ASR confidence over manager speech, plus
alignment-failure rate (words the aligner could not place), normalised.
Reported with the low-confidence spans quoted, so a trainer sees *which* words
were unclear rather than a bare number.

#### `cefr_band` — the advisory placement

Silent-pause threshold is **250 ms** — `SOURCED`. De Jong & Bosker (2013)
empirically tested cut-offs from 100 ms to 1 s and found **250–300 ms maximises
the correlation between pause frequency and L2 proficiency**, with correlations
falling away above 300 ms. That settles the usual 0.25 s vs 0.4 s question.

Measured **within manager turns of ≥5 s only**, inter-turn gaps excluded. All
published benchmarks are **monologic test speech**; dialogic turn-taking deflates
length-of-run and inflates pause counts at turn boundaries. Applying monologic
norms to raw dialogue would under-band every manager systematically.

| Feature | Unit | Note |
|---|---|---|
| `speech_rate` | syllables/min incl. pauses | separates A2/B1/B2, **not** B2/C1 |
| `articulation_rate` | syllables/min excl. pauses | |
| `mean_length_of_run` | syllables between pauses ≥250 ms | |
| `phonation_time_ratio` | % of time speaking | |
| `mean_silent_pause` | seconds | |
| `mid_clause_pause_rate` | per minute | the lower/upper divider |
| `juncture_pause_proportion` | clause-boundary pauses / all pauses | **strongest single predictor, r = .84** |
| `mtld` | length-robust lexical diversity | needs ≥100 tokens |
| `error_free_clause_ratio` | per AS-unit | best C-level discriminator |
| `cefr_band_lexis` | proportion of lemmas at C1+ (EVP / CEFR-J) | DET ships exactly this feature |

**Published per-level anchors — `SOURCED`.** Tavakoli, Nakatsuhara & Hunter
(British Council ARAGs, Aptis; n=32, 250 ms threshold; means):

| Measure | A2 | B1 | B2 | C1 |
|---|---|---|---|---|
| Speech rate (syll/min) | 73.2 | 135.2 | 172.1 | 172.2 |
| Articulation rate (syll/min) | 158.1 | 188.0 | 224.3 | 234.9 |
| Mean length of run (syll) | 3.21 | 5.84 | 8.54 | 7.75 |
| Phonation-time ratio (%) | 46.5 | 71.3 | 76.9 | 72.9 |
| Mean silent pause (s) | 1.42 | 0.63 | 0.56 | 0.54 |
| Mid-clause pauses/min | 7.5 | 6.3 | 4.0 | 4.3 |

Yan, Kim & Kim (British Council ARAGs, Aptis; n=125, adds A1 and C):

| Measure | A1 | A2 | B1 | B2 | C | r |
|---|---|---|---|---|---|---|
| Speech rate (syll/s) | 1.70 | 2.28 | 2.79 | 3.54 | 3.54 | .70 |
| Juncture-pause proportion | 0.07 | 0.22 | 0.39 | 0.66 | 0.75 | **.84** |
| MLR (syll) | 7.0 | 7.1 | 10.7 | 17.4 | 18.6 | .60 |
| MTLD | 17 | 24 | 32 | 44 | 46 | .79 |
| Error-free clauses / c-unit | — | 0.30 | 0.54 | 0.64 | 0.76 | .77 |
| Subordinate clauses / c-unit | — | 0.12 | 0.24 | 0.30 | 0.30 | .51 |

The two studies cross-validate on speech rate, MLR and the B2≈C1 ceiling. MLR
differs in absolute value between them (different unit conventions), so the
engine bands against **one table** — Yan et al., because it covers A1 and C and
carries the lexical and accuracy measures — and uses Tavakoli et al. only as a
cross-check. The two are never mixed.

**Band assignment.** There is **no published regression equation**
`CEFR = f(features)`. Zechner et al. (2007) publish SpeechRater's
linear-regression *form* but not its weights; Versant, Duolingo and Linguaskill
weights are proprietary. The engine cannot reimplement a validated equation and
must not pretend to. Construction is nearest-per-level-mean per feature, combined
by **median**, with two rules the data directly supports:

1. **Fluency alone can never award C1 or above.** Both datasets find B2 and C1
   fluency-indistinguishable — Tavakoli et al. conclude C1 differs in lexis and
   grammar, not fluency. C1+ requires the lexis/accuracy features
   (MTLD ≳ 44, error-free-clause ratio ≳ 0.7).
2. **Never penalise filled pauses.** Filled-pause frequency *rises* with
   proficiency (C1 8.6/min vs A2 3.1/min, Tavakoli et al.) and normalised per
   syllable does not discriminate level at all (r = −.08, n.s., Yan et al.).
   This contradicts every commercial "um counter" and is why S28 stays advisory.

Output is a **band plus an adjacent range** (`B2, adjacent B1–C1`) with the
per-feature table shown — never a bare letter. Cambridge's own auto-marker
reports 56.8% exact / 96.6% adjacent agreement with human CEFR graders; adjacent
accuracy is the honest unit for this measurement and the report says so.

**The L1 caveat, printed on the panel.** CEFR is a **second-language** framework.
A fluent L1 English speaker ceilings every measure, and De Jong et al. (2015,
*SSLA*) show a speaker's **L1 pausing style contaminates L2 fluency measures** —
an unhurried speaker is marked down for a habit, not a competence. This is the
main reason `intelligibility`, not `cefr_band`, carries the weight when §4.1 is on.

#### Invalid measures, named so nobody adds them later

* **Raw type-token ratio** — falls monotonically with sample length; every
  serious study rejects it. Use MTLD (length-robust from ~100 tokens).
* **Flesch-Kincaid / Flesch Reading Ease** — normed on written prose for
  *readers*, and both terms depend on sentence length, which in a transcript is
  an artefact of ASR punctuation rather than speaker behaviour. Use AS-unit
  measures instead; the AS-unit (Foster, Tonkyn & Wigglesworth 2000) exists
  precisely because sentences and T-units fail on spontaneous speech.

---

## 6. The judge layer

One model call per session. Input: transcript + the complete computed signal
table + rubric. Output, against a strict JSON schema:

* per criterion — reasoning prose and 1–3 supporting quotes
* per `must_discover` signal — `surfaced: bool` + `evidence_span` (verbatim)
* `composure_at_disruption` — verdict + `evidence_span`
* `done_well` (2–4 moments), `focus_areas`

**Code validates and can veto every one of these:**

1. Each `evidence_span` must appear **verbatim** in the transcript. If not, the
   claim is dropped and the signal degrades to `unmeasurable`, not to `false`.
2. A `surfaced: true` must be preceded by a manager question act in the same
   topic. Credit requires the manager to have *asked*; a candidate volunteering
   something is not discovery.
3. Every number in the report is recomputed by code from the validated booleans.
   The judge's prose is never parsed for values.

Temperature 0.1. The judge is deterministic-adjacent, not deterministic — so
§9's regression suite pins the *code* path on stored fixtures with a stub judge,
and the judge path is tested separately for schema and evidence validity.

---

## 7. Strengths vs Gaps, and Development Areas

Kluger & DeNisi (1996, *Psychological Bulletin*, 607 effect sizes / 23,663
observations) is the governing constraint: feedback raises performance by
**d = .41** on average, but **over one third of feedback interventions made
performance worse**. What separates the two is attentional focus — feedback
aimed at the **task and specific behaviour** helps; feedback aimed at the
**person** harms. This dictates the format, not just the tone:

* Every strength and gap is a **behaviour tied to a quoted, timestamped moment**,
  never a trait. "You accepted the first jargon deflection at 08:12" — not
  "you are too easily impressed".
* Every gap carries a **rehearsable alternative**: the exact sentence to have
  said instead. `must_discover[i].how_to_surface` already contains this wording
  for the persona's own signals.

**Volume: at most 3 development areas, exactly 1 marked primary.** No study gives
an optimal number — I looked, and the "N=3" is convention. The justification is
Kluger & DeNisi's own mechanism (diffuse, high-volume feedback shifts attention
from task to self) plus cognitive-load-based coaching practice that focused
feedback outperforms comprehensive lists. Stated as convention, not finding.

**Selection is deterministic:** strengths = highest sub-scores with valid
evidence; gaps = lowest. The model writes the sentences, code picks which
signals get sentences written about them.

**Next practice persona is fully deterministic** — no model involved. Take the
weakest criterion, then pick the catalog archetype with the highest
`stresses[criterion]`, excluding the one just faced. `interviewer_failure_modes`
supplies the "why this one" line.

---

## 8. Report sections → signal mapping

| Report section (wizard spec) | Source |
|---|---|
| Readiness Index + band | §4 |
| Welcome & greeting | S12, S26 |
| Role explanation | S10, S11, S13, S14 |
| Category scorecard | four criterion scores + counts |
| **Strengths vs gaps** | §7 |
| Key moments | `session_beats` × S4/S17/S27 |
| **Question analysis (QNA)** | every question act: timestamp, verbatim, type, probe depth, competency, information yield; plus candidate questions and S11 |
| Bias check | S16 with exact line + neutral alternative |
| Transcript & audio | passthrough |
| Next practice | §7, deterministic |
| Advisory: pace & fillers | S28, shown not scored |
| Manager English proficiency | §5.E, off by default |

---

## 9. Calibration, and how this becomes genuinely measurable

Cold start runs `absolute` mode against the `CALIBRATION` constants above. They
are engineering judgment and the report should not pretend otherwise.

Once ~50 sessions exist **per archetype**, the engine switches to
`norm_referenced` mode: each raw signal is scored as its percentile within the
cohort facing the same persona. This is what actually delivers the BRD's
comparability across 3,000 managers, because the persona fixes the difficulty.
The absolute thresholds then become a sanity floor rather than the scoring rule.

Cohort-only metrics — impossible per session, valuable in aggregate:
question consistency across candidates (Campion #2), plan adherence,
per-manager promotion/prevention framing differentials by candidate group
(Kanze et al.), and four-fifths adverse-impact rate comparisons.

**Cohort segmentation is mandatory, not optional.** A cohort average may only
be taken across reports that share `scoring_version`, `rubric_version`,
`english_weight`, `language_gate` and jurisdiction-pack version. Mixed settings
are shown as separate cohorts, never averaged. Without this, the operator
toggles in §3.4 and §4.1 quietly destroy the comparability that §1 exists to
create.

**Regression requirement:** stored session fixtures + a stub judge must produce
byte-identical reports across runs and across engine versions within a
`scoring_version`. Any change to a threshold bumps `scoring_version` and is
recorded — otherwise last month's 62 and this month's 62 are not the same 62.

---

## 10. Packaging

`report_engine/` — a new sibling package, `ALLOWED_IMPORTS["report_engine"] = {"llm"}`,
added to `PACKAGES` in `tests/test_architecture.py`.

```
report_engine/
  schema.py       # SessionBundle in, AssessmentReport out
  segment.py      # §3.1
  acts.py         # §3.2, §3.3 — question extraction and typing
  signals/        # one module per criterion; each signal declares modality + transfer
  audio/          # phase 7 only: decode, VAD, forced alignment (§5.E)
  score.py        # §4 — the only place numbers are combined
  judge.py        # §6 — takes an injected StructuredModel
  validate.py     # evidence-span verification, the judge veto
  render.py       # JSON + HTML
  cli.py          # python -m report_engine bundle.json --rubric r.json -o report.html
  packs/          # protected-topic packs by jurisdiction, dated
```

Standalone means: reads a JSON file, writes a report, no database, no control
plane, no network except the one judge call — and `--no-judge` produces the
complete deterministic half of the report with no network at all. That mode is
also the regression harness.

The audio dependency (§5.E) is confined to `audio/` and imported lazily, so
phases 1–6 install and run without it. A repo that cannot decode Opus still
produces every other section rather than failing to import.

---

## 11. Decisions recorded

Settled 2026-08-26. These are inputs to the build, not open items.

1. **English weighting is an operator toggle** — `scoring_options.english_weight`
   (§4.1). Default `null` = advisory panel only. Comparability consequence and
   cohort segmentation rule are in §4.1 and §9.
2. **The language gate is an operator toggle** — `scoring_options.language_gate`
   (§3.4). Default `true`. Language mix is always detected and always reported;
   the flag decides whether a non-English session is refused or scored with a
   stamped validity warning.
3. **Word-level timings come from the recording, not the engine** (§5.E). The
   browser's stereo `manager_left_candidate_right` capture is sufficient: channel
   split for speaker separation, VAD for pause structure, forced alignment
   against the manager's own channel for clause anchoring. No engine work is
   blocking. The engine's future stereo WAV is a better input for the same code
   path when it lands.
4. **The module measures communication, not only English** (§5.E) — two outputs,
   `intelligibility` (primary, carries the weight when §4.1 is on) and
   `cefr_band` (advisory placement, printed with its L1 caveat).
5. **Reports are reviewed by mentors and trainers** (BRD D-8, resolved). This is
   an assessment reviewed by third parties, not a private practice space.
   Consequences, all already served by the design but now mandatory rather than
   nice-to-have:
   * **Every claim stays quote-anchored and timestamped.** A report someone else
     acts on must be checkable by the person it describes. The judge veto (§6)
     is the mechanism.
   * **Full provenance stamped on every report**: `scoring_version`,
     `rubric_version`, `engine_version`, `english_weight`, `language_gate`,
     jurisdiction pack version and date. Last month's 62 and this month's 62 are
     only the same 62 if these match.
   * **A stated validity caveat, once, on the report**: managers who know a
     trainer will read this will interview more defensively than they otherwise
     would. That is a real limit on what the numbers mean and it should be
     printed rather than known only by us.
   * **Consent copy needs updating** — the recording contract's consent event is
     "proceeding past the connecting screen", and that screen currently says the
     call is recorded and stored. It does not say the resulting assessment is
     shared with mentors and trainers. That is a product/legal change outside
     this engine, flagged here because this decision creates it. India's DPDP Act
     2023 applies to the voice recordings and the derived assessment.

### Still genuinely open

* **`english_weight` starting value** — 0.10 proposed (§4.1). Org-owned, like
  the rubric. Needs Atibhee's L&D call, not an engineering one.
* **Jurisdiction pack for India** — the BRD names the categories (caste,
  community, native place, marital status, family-permission framing). Someone
  with Indian employment-law standing should review the pack before it ships;
  I can draft it, I cannot sign it off.

---

## 12. Build order

Each phase produces something runnable. Nothing after phase 1 can silently
change a number produced by phase 1 without a `scoring_version` bump.

| # | Phase | Delivers | Depends on |
|---|---|---|---|
| 1 | `schema.py`, `segment.py`, `acts.py` | bundle in, segmented transcript with typed question acts out; the QNA table is already producible | — |
| 2 | `signals/structure.py`, `clarity.py` | S1–S15 minus the judge-bound parts; `--no-judge` report with two criteria | 1 |
| 3 | `signals/fairness.py` + `packs/in.json` | S16–S21, the bias check section | 1 |
| 4 | `signals/communication.py` | S23–S27 (text-computable half) | 1 |
| 5 | `score.py`, `render.py`, `cli.py` | complete deterministic report, zero network, JSON + HTML | 2–4 |
| 6 | `judge.py`, `validate.py` | reasoning prose, `must_discover` surfacing, strengths/gaps/development areas | 5 |
| 7 | `signals/english.py` | §5.E — audio dependency lands here and nowhere else | 5, a voice session with a recording |

Phase 5 is the first genuinely useful artifact and the regression harness for
everything after it. Phase 7 is last because it is the only phase that adds a
dependency the repo does not already carry.

**Process obligations that apply from phase 1** (repo hard rules): add
`report_engine` to `PACKAGES` and `ALLOWED_IMPORTS` in `tests/test_architecture.py`;
`.venv/bin/python scripts/export_schemas.py` after any public Pydantic model;
an okf concept page plus one `okf/log.md` line per change, per
`okf/concepts/runbooks/okf-maintenance.md`.
