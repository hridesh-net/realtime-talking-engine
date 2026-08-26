---
type: Reference
title: What a session costs
description: Measured token counts and quoted vendor rates for one interview session, end to end.
resource: /docs/PRICING_PER_SESSION.md
tags: [reference, cost, pricing, operations]
generated:
  by: claude-opus-5
  at: "2026-08-26T00:00:00Z"
status: stable
sources:
  - resource: /docs/PRICING_PER_SESSION.md
---
# What a session costs

`docs/PRICING_PER_SESSION.md`, measured 2026-08-26.

## The one fact worth remembering

**The live voice call costs roughly four times what analysing it does.** A
20-minute session is about **$1.06** marginal, of which ~$0.85 is the realtime
conversation and $0.19 is the audio analysis. Report generation is free — it
calls no model.

Effort spent making the analysis cheaper is effort spent on the smaller number.
The single largest lever is the realtime model: `gpt-realtime-2.1-mini` is
roughly a third the cost of `gpt-realtime-2`, and that is a product decision
about conversational quality rather than a config change.

## Measured, not estimated

The analysis figures come from instrumenting a real 346-second recording through
the real windowing path:

```
prompt tokens = 5,592 per window + 31.9 per second of audio
output tokens = 2,137 per window + 17.8 per second of audio
```

The per-window fixed cost is the instructions plus the expectation context,
re-sent with every window — which is why window size is a cost lever as well as
an accuracy one, and why widening it trades money against the timestamp
discipline the harness exists to enforce.

**The voice-call figure is an estimate** and the document says so, showing its
working: OpenAI publishes a token price but not a tokens-per-second rate, so the
conversion is inferred from the previous generation's reported per-minute cost.

## Re-measure after any of these

`INSTRUCTIONS.md` changing, the window size changing, or the model changing. The
first is the trap — it is edited as prose and does not look like a cost change.

## Related

[Audio analysis agent](/concepts/subsystems/analysis-agent.md) ·
[infra/README.md](/infra/README.md) — the fixed monthly cost this amortises against
