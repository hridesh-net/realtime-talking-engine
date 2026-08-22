---
type: Subsystem
title: Live-session engine
description: Go engine that runs the live voice session — one brain, two parts, with the persona's mouth and its subconscious.
resource: /engine
tags: [engine, go, realtime, voice, session, dual-model]
generated:
  by: claude-opus-5
  at: "2026-08-21T21:40:00Z"
verified:
  - by: claude-opus-5
    at: "2026-08-21T21:40:00Z"
  - by: kimi-code/okf-curator
    at: "2026-08-22T21:10:00Z"
status: draft
sources:
  - resource: /docs/ENGINE_IMPLEMENTATION_PLAN.md
  - resource: /docs/GO_ENGINE_CONTRACT.md
  - resource: /docs/ENGINE_ONE_BRAIN_TWO_PARTS.html
  - resource: /engine/internal/ports
  - resource: /engine/internal/contract
  - resource: /engine/internal/arch
---
# Live-session engine

`engine/` — a Go module that runs the **live voice session**. It is the runtime
counterpart to everything else in this repo: the Python side decides *what* an
interview is, the engine performs it. Design and task breakdown live in
[the implementation plan](/docs/ENGINE_IMPLEMENTATION_PLAN.md); the payload it
consumes is specified in [the engine contract](/docs/GO_ENGINE_CONTRACT.md).

**Status: under construction.** Phase 0 (skeleton, ports, contract types,
config, fakes, layering test, session manager) is the only part that exists as
working code. The rest of the planned tree — `audio`, `gate`, `judge`, `ledger`,
`obs`, `record`, `stall`, `store/s3`, `transcriptlog`, `transport/{webrtc,wsfallback}`,
`vendor/{openairt,openaitx,gemini,geminitts,localasr,thinkerllm}`,
`controlplane` — is present as `doc.go`-only placeholder packages, each a
one-line declaration of what will live there, so the layering test already walks
the final shape.

## The inversion that shapes everything

In this product the **AI plays the candidate and a human interviewer practises
against it**. That is the reverse of a normal voice-AI interview product, and it
inverts the timing budget: an interviewer's question runs 5–15 seconds where a
candidate's answer runs 30–90. The reasoning model therefore has roughly a fifth
of the thinking window the usual "think while the user talks" design assumes.

The persona's own contract supplies the compensation — `target_pause_before_answer_ms`,
`hesitation_frequency`, `filler_frequency` — because a candidate pausing before
answering is in character, not a stall. See
[determinism](/concepts/determinism.md) for why that material is compiled in
Python rather than invented at runtime.

## One brain, two parts

| Part | Role |
|---|---|
| **Speaker** | The mouth and the fast front brain. A realtime speech-to-speech model that always owns the voice; it is never replaced as the speaker. |
| **Thinker** | The subconscious. A reasoning model that holds who this person actually is, runs speculatively and continuously, and is consulted when the Speaker is unsure what it may say. |

[`docs/ENGINE_ONE_BRAIN_TWO_PARTS.html`](/docs/ENGINE_ONE_BRAIN_TWO_PARTS.html) draws
the mechanism: the anatomy, a millisecond timeline of both the confident and the
deferring turn, and what the shared ledger prevents. Open it in a browser.

These are two parts of **one** brain, not two agents — which is why they share a
per-session claims ledger. Without it the persona is *randomly* wrong across
turns, where a real weak candidate is *consistently* wrong. That distinction
matters because "did the candidate contradict themselves" is a signal the
interviewer is being trained to detect.

The Thinker is a **persona oracle, not a knowledge oracle**: asked what to say,
it answers "what would this person say", never "what is correct". For a weak
persona the right output is a vague or confidently wrong answer.

## Layering

Enforced by `go test ./internal/arch`, mirroring
[the Python architecture rules](/concepts/architecture.md):

```
vendors / transports / stores  →  ports  ←  session core
                       only cmd/engined wires concrete adapters
```

* `internal/ports` imports no other internal package.
* `internal/session`, `ledger`, `gate`, `stall` import only `ports`, `contract`, `obs`.
* Nothing outside `cmd/engined` imports a vendor, transport or store adapter.
* `os.Getenv` / `os.LookupEnv` appear only in `internal/config` — the Go mirror of
  "agents never read API keys".
* No vendor model-id string literals outside `internal/config` — model IDs are config.
* `internal/session` never calls `time.Now`; the `Clock` port is injected, or
  turn-timing tests are permanently flaky.

## Contract versioning

`internal/contract` pins the **major** version and rejects anything else, per
[the engine contract spec](/docs/GO_ENGINE_CONTRACT.md). It also retains the
**minor**, because minor bumps are additive and therefore accepted — meaning a
newer contract can reach an older engine and have its new fields silently
dropped by the decoder. Features gated on a later minor call `RequireMinor` so a
version skew fails loudly. v1.1 is already taken — by the M1 language line, an
additive prompt change the engine needed no edit for (its own `contract_test.go`
covers the case). The behavioural fields the persona library v2 still wants
(precompiled beliefs, stall phrases, pre-gate lexicon, unlock spec) would now be
a **v1.2**: running those on an older code path would fall back to
runtime-invented persona beliefs — exactly the non-determinism they exist to
remove.

## Checks

`scripts/check.sh` runs gofmt, vet, build, `go test -race`, the layering test and
golangci-lint against `.golangci.yml`, all from inside the module. Vendor tests
are tagged `//go:build live` and run only under `--live`, matching the Python
convention that model calls cost money. See [checks](/concepts/runbooks/checks.md).
