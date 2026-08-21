---
okf_version: "0.2"
---
# interview-watcher Knowledge Bundle

An [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
v0.2 bundle describing the **interview-watcher** repository: the interview
control plane. It creates interviews from a job spec, generates a deterministic
interviewer expectation for each, and casts virtual candidates that human
interviewers practise against.

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
* [Runbooks](/concepts/runbooks/index.md) - setup, checks, using the API, maintaining this bundle.
* [References](/references/index.md) - the BRD, providers, the sibling repo, the OKF spec.

## Freshness

Describes the working tree at commit `802c84260fa2bbdede2945580bafebba102a7304`
("Add virtual candidate enrollment and enforce SOLID/Python standards"), clean at
the time of writing. Curated 2026-08-21 by reading every documented source file.

⚠️ Two housekeeping problems found while writing this bundle, both in
`.gitignore`: the owner deliverables in `owner_handover/` and `docs/` are
**ignored despite a comment saying they are tracked on purpose**, so eight of
them are not in git; and `okf/` is not yet excluded from that same file's
patterns. See [Keeping this bundle current](/concepts/runbooks/okf-maintenance.md).
