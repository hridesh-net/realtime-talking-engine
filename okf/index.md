---
okf_version: "0.2"
---
# interview-watcher Knowledge Bundle

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
v0.2 bundle describing the **interview-watcher** repository: the interview
control plane. It creates interviews from a job spec, generates a deterministic
interviewer expectation for each, casts virtual candidates that hiring managers
practise against, and runs the live interview against them — typed or spoken.

**This bundle is the primary code reference for agents working in this repo.**
Read it instead of re-reading the source. When code changes, update the affected
concept and append to [log.md](/log.md) — see
[Keeping this bundle current](/concepts/runbooks/okf-maintenance.md).

## Start here

* [Project Overview](/concepts/project-overview.md) - what this service is, what it is not, current state.
* [Determinism split](/concepts/determinism.md) - **the central idea**: what code owns vs. what the model may author.
* [Architecture](/concepts/architecture.md) - the four layers, the one-way dependency rule, and how it is enforced.
* [Repo Map](/concepts/repo-map.md) - path → concept routing table.
* [Conventions](/concepts/conventions.md) - the explicit lint/type rule set and the executable architecture rules.
* [Glossary](/concepts/glossary.md) - archetype, verdict, expectation, scorecard, fingerprint, ceiling.

## Sections

* [Subsystems](/concepts/subsystems/index.md) - one page per package.
* [Contracts](/concepts/contracts/index.md) - API, persona, expectation, engine handoff, storage.
* [Modules](/concepts/modules/index.md) - one reference card per significant source file.
* [Runbooks](/concepts/runbooks/index.md) - setup, checks, using the API, **running an interview**, maintaining this bundle.
* [References](/references/index.md) - the BRD, providers, the sibling repo, the OKF spec.

## Freshness

Curated 2026-08-21 against commit `802c8426` by reading every documented source
file, and kept current since — see [log.md](/log.md) for what has changed.

Most recent substantive change: the **audio analysis agent** and the report
built from it. `analysis_agent/` listens to a session's recording against the
expectation it was held against and stores observations; `report_engine/`
composes a report with two clearly-separated halves, **counted** and **heard**.
See [Audio analysis agent](/concepts/subsystems/analysis-agent.md),
[Report engine](/concepts/subsystems/report-engine.md) and
[What a session costs](/references/pricing.md).

Previous substantive change: the **Phase 0 MVP milestone M1** — the interview
configuration the training-wizard specification asks for, including a `language`
setting that genuinely reaches the persona's prompt and the speech-to-text hint,
operator notes that cannot override an archetype, and the fixed role-fact
checklist in the new [evaluation agent](/concepts/subsystems/evaluation-agent.md).
`ENGINE_CONTRACT_VERSION` is now **v1.1**.

⚠️ Read `docs/BRD_Interviewer_Upskilling_v3.html` before changing anything about
what is scored or who is scored: the assessed subject is being flipped from the
candidate to the hiring manager, and much of the code and this bundle still
describes the older framing.
