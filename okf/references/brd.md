---
type: Reference
title: BRD — AI Interview Platform, Interviewer Training Module
description: The requirements document this repo implements the control-plane half of.
resource: /docs/BRD_AI_Interview_Platform_v2.md
tags: [reference, brd, requirements]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /docs/BRD_AI_Interview_Platform_v2.md
---
# BRD — AI Interview Platform (Interviewer Training Module)

772 lines, `docs/BRD_AI_Interview_Platform_v2.md`. The source document for this
service. Worth knowing where its sections land in code, because several are
implemented **elsewhere** — the BRD covers a Go runtime this repo does not
contain.

## Section map

| BRD section | Where it lives |
|---|---|
| §1.4 Build decision matrix | Why interview creation is Python — `control_plane/README.md` restates it |
| §3.1 Functional requirements | The endpoints; FR-002 is the seeded persona |
| §3.2 NFR-003 | [`tests/test_architecture.py`](/concepts/architecture.md) — SOLID as executable checks |
| §4.1–4.2 Domain model, interview aggregate | [`control_plane/schemas.py`](/concepts/contracts/interview-record.md), the SQLite schema |
| §4.3 Persona value object | `control_plane/persona.py` — the **legacy** persona, superseded by `candidate_agent` |
| §5.1 Layered architecture | [Architecture](/concepts/architecture.md) |
| §5.3 Dual-model integration | [`llm/`](/concepts/subsystems/llm-port.md) |
| §5.4 Turn engine strategy | The Go runtime — not here |
| §6 API specification | Partly here; the training-batch and session endpoints differ from what was built |
| §8 Go implementation guidelines | The Go runtime — not here. `.golangci.yml` records the lint standard |
| §8.5 Persona prompt template | Superseded by [`engine_contract.py`](/concepts/modules/candidate-agent-engine-contract.md), which compiles a far richer prompt |
| §9 Fixed evaluation criteria | [`expectation_agent/rubric.py`](/concepts/modules/expectation-agent-rubric.md) — the six criteria and weights, verbatim |
| §10 Implementation phases | Phases 1–2 are done; training mode and reporting are partial |
| §11 Risk & mitigation, §12 Glossary | Background |

## Where the code has moved on

* **Personas.** §4.3's five scored attributes became the eleven-archetype catalog with knowledge ceilings, scorecards, and a compiled engine contract. `control_plane/persona.py` is the original and is still wired in but never read.
* **The API.** §6's training-batch and session endpoints were not built as specified; enrollment is per-interview instead.
* **Evaluation criteria.** §9 survives unchanged — the one part of the BRD copied into code literally.

Treat the BRD as intent, not as a description of the current system. Where they
disagree, this bundle describes the code.
