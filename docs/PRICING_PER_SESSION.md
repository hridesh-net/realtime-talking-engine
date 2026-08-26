# What a session costs

**Measured 2026-08-26.** Every rate is quoted from the vendor's own pricing page
on that date with a link; every token count is measured from a real session on
this system, not estimated. Where a number *is* an estimate, it says so and
shows its working — the difference matters, because the estimated line is also
the largest one.

**Prices change.** Re-measure before quoting these to anyone. The Gemini figures
below are introductory and expire on 2026-12-31.

---

## The short answer

| Session length | Marginal cost | Dominated by |
|---|---|---|
| 5 min | **~$0.32** | the live voice call |
| 20 min | **~$1.06** | the live voice call |
| 30 min | **~$1.56** | the live voice call |

**The interview itself costs roughly four times what analysing it does.** That
is the single most useful fact here: effort spent making the analysis cheaper is
effort spent on the smaller number.

---

## Where it goes, for a 20-minute voice session

| Step | Cost | Basis |
|---|---|---|
| Live voice call (`gpt-realtime-2`) | **~$0.85** | estimated, §3 |
| Audio analysis (`gemini-3.7-flash`) | **$0.19** | **measured**, §2 |
| Persona casting (one structured call) | ~$0.013 | estimated |
| Role-fact drafting (optional, once per role) | ~$0.005 | estimated |
| Report generation | **$0.00** | code only — no model call, §4 |
| **Marginal total** | **~$1.06** | |
| Infrastructure, amortised | +$0.01 – $0.36 | §5, depends entirely on volume |

---

## 1. Rates used

| Model | Input | Output | Source |
|---|---|---|---|
| `gemini-3.7-flash` | $0.75 / 1M | $3.75 / 1M | [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) — introductory, **rises to $1.50 / $7.50 on 2027-01-01** |
| `gemini-2.5-flash` | $0.30 / 1M text, **$1.00 / 1M audio** | $2.50 / 1M | same page |
| `gpt-realtime-2` | $32 / 1M audio, $0.40 cached, $4 text | $64 / 1M audio, $24 text | [OpenAI API pricing](https://developers.openai.com/api/docs/pricing) |
| `gpt-realtime-2.1-mini` | $10 / 1M audio, $0.30 cached | $20 / 1M audio | same page |
| `whisper-1` | $0.006 / minute | — | same page |

Note the modality quirk: **3.7 Flash lists no separate audio rate**, so audio
bills at the text input price. 2.5 Flash charges $1.00/1M for audio — more than
three times its text rate. That inverts which model is cheaper for this
workload, and it is why the analysis role resolves to 3.7 Flash.

---

## 2. Audio analysis — measured

Measured on a real 346-second session, two windows:

| Window | Prompt tokens | Output tokens |
|---|---|---|
| 240 s | 13,240 | 6,417 |
| 126 s | 9,607 | 4,384 |

Those two points fit a straight line cleanly, which gives a cost model rather
than a single data point:

```
prompt tokens = 5,592 per window + 31.9 per second of audio
output tokens = 2,137 per window + 17.8 per second of audio
```

The **per-window fixed cost is the instructions plus the expectation context**,
re-sent with every window. That is the lever that matters (§6).

| Recording | Windows | Audio billed | Prompt | Output | Cost |
|---|---|---|---|---|---|
| 5 min | 2 | 320 s | 21,381 | 9,981 | **$0.053** |
| 10 min | 3 | 640 s | 37,171 | 17,824 | **$0.095** |
| 20 min | 6 | 1,300 s | 74,978 | 36,005 | **$0.191** |
| 30 min | 9 | 1,960 s | 112,786 | 54,186 | **$0.288** |

"Audio billed" exceeds the recording length because windows overlap by 20
seconds so an exchange spanning a boundary is heard whole. That overlap costs
about **8%** of the audio bill and is the price of not cutting a question in
half.

---

## 3. The live voice call — estimated, and the biggest line

**This is an estimate, and it is the number to check first if the total looks
wrong.** OpenAI publishes a token price but not a tokens-per-second rate for
realtime audio, so the conversion is inferred:

> The previous generation billed audio input at $100/1M and was widely reported
> at ~$0.06 per minute, which implies **~600 tokens per minute** (10/second).
> Applying that rate to `gpt-realtime-2`'s published $32/1M and $64/1M gives the
> figures below.

For a 20-minute session with roughly 40% manager / 60% persona speech:

| Component | Working | Cost |
|---|---|---|
| Audio in — the model hears the whole session | 20 min × 600 tok × $32/1M | $0.38 |
| Audio out — the persona's speech | 12 min × 600 tok × $64/1M | $0.46 |
| **Subtotal** | | **~$0.85** |

Two things push this **up** in practice, and neither is modelled above: the
realtime API re-sends conversation context on every turn (which is what the
$0.40/1M cached rate exists for), and silence is still audio. Treat $0.85 as a
floor and budget **$0.80–$1.50**.

**`gpt-realtime-2.1-mini` costs roughly a third** ($10/$20 against $32/$64). It
is a different model with different conversational quality, so that is a product
decision, not a config change — but it is the single largest cost lever in the
system.

---

## 4. Report generation is free

Building a report calls no model. It is pattern matching and arithmetic over the
stored transcript plus the stored analysis — a few milliseconds of CPU. Clicking
**Generate report** repeatedly costs nothing, and regenerating after a threshold
change costs nothing.

Analysis is the paid step, it runs once, and its result is stored.

---

## 5. Infrastructure

From [`infra/README.md`](/infra/README.md): **~$10.85/month** on-demand
(`t4g.small`, two gp3 volumes, S3, Elastic IP), or ~$6.75 with `use_spot`.

Amortised, that is entirely a volume question:

| Sessions / month | Infra per session |
|---|---|
| 30 | $0.36 |
| 100 | $0.11 |
| 1,000 | $0.01 |

Storage is not a separate line at this scale: recordings run about 1 MB per
minute, so the 20 GB data volume holds roughly a thousand 20-minute sessions
before it needs growing.

---

## 6. Levers, in order of size

1. **Switch the realtime model.** `gpt-realtime-2.1-mini` is ~⅓ the cost and is
   two thirds of the total bill. Nothing else comes close.
2. **Shorten interviews.** Every cost here except casting is linear in minutes.
3. **Widen the analysis window.** The 5,592-token fixed cost repeats per window,
   so a 20-minute recording pays it six times. Going from 4- to 8-minute windows
   would roughly halve that overhead — **but** short windows are what keeps the
   model's sense of elapsed time honest, and widening them brings back the
   timestamp drift the harness exists to prevent. Measure `dropped_anchors`
   before and after; do not trade evidence quality for a few cents.
4. **Trim the context sent per window.** The instructions are ~11 KB and the
   expectation block a few more. Both ride on every window. Cutting them helps
   linearly, and costs analysis quality — the persona traits are what make the
   60/40 persona judgement possible at all.
5. **Do not re-analyse.** Analysis is stored. Re-running it is a deliberate
   button, not something a page load triggers.

---

## 7. What is not counted here

* **Model failures and retries.** A failed window is skipped, not retried, so a
  partial analysis costs less than a whole one — the arithmetic above is a
  ceiling per attempt, not a guarantee per session.
* **Transcription** (`scripts/transcribe_recording.py`, $0.006/min per channel)
  is a developer tool. It is not on the production path; the analysis agent
  transcribes as part of its own work.
* **Egress and vendor-bound data transfer.** Small — these are API calls, not
  media relay. Voice media goes browser-to-vendor directly and never transits
  this infrastructure.
* **Anything a human does with the report.**

---

## How to re-measure

The token counts came from instrumenting one real recording through the real
windowing path and reading `usage_metadata` off each response. Do that again
rather than trusting this file after any change to `INSTRUCTIONS.md`, the
window size, or the model — all three move the numbers, and the first is
changed by editing prose, which does not look like a cost change.
