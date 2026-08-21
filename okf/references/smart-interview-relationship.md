---
type: Reference
title: smart-Interview (sibling repo)
description: The real-time voice interviewer this control plane was split out of, and where the boundary sits.
resource: https://github.com/hridesh-net/smart-Interview
tags: [reference, boundary, sibling-repo, architecture]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /README.md
  - resource: /docs/GO_ENGINE_CONTRACT.md
---
# smart-Interview (sibling repo)

Local path: `~/Projects/Skillbrew/smart-Interview`. This repo was split out of it
at commit `378a7b4` ("Split interview control plane out of smart-Interview").

**Nothing here imports from it, and nothing there imports from this.** The
separation is intentional and worth preserving.

## Who owns what

| | interview-watcher (here) | smart-Interview |
|---|---|---|
| Owns | the **what** of an interview | the **how** of a live conversation |
| Runtime | FastAPI + SQLite, request/response | real-time voice, sub-second latency |
| Produces | expectations, personas, engine contracts, scorecards | a spoken interview and its recordings |
| Who is the AI? | the AI plays the **candidate** | the AI plays the **interviewer** |
| Who is the human? | the human is the **interviewer** being trained | the human is the **candidate** |

That last row is the thing to keep straight — the two repos point the microphone
in opposite directions. Here, personas exist so a human interviewer can practise
and be graded. There, the system interviews a real candidate.

## Vocabulary that looks shared but is not

| Term | Here | There |
|---|---|---|
| "expectation" / "flow" | `InterviewExpectation` — phases, criteria, guidance for a human | `InterviewFlow` — JD-derived topics + rubric for the AI interviewer |
| "persona" | the candidate the AI plays | the voice the AI interviewer speaks in |
| "rubric" | six fixed weighted criteria | per-role generated 0/3/5 anchors |
| "engine" | the Go runtime that will play personas | the Speaker/Thinker/Orchestrator planes |

Do not port code between them on the strength of a matching noun.

## The interface

There is none today — no HTTP call, no shared database, no shared package. The
only planned integration is the Go **interview-candidate engine** reading
`GET /candidates/{cid}/engine-contract` from this service
(`docs/GO_ENGINE_CONTRACT.md`). That engine is a third build, in neither repo.

If a real link is added later, this page is where to record it.
