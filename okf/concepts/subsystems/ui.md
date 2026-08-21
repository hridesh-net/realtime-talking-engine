---
type: Subsystem
title: Test UI
description: The React + Vite operator console for exercising the API by hand.
resource: /ui
tags: [ui, react, vite, frontend]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
verified:
  - by: claude-opus-5/okf-curator
    at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: /ui/src/api.js
  - resource: /ui/src/App.jsx
  - resource: /ui/vite.config.js
  - resource: /ui/package.json
---
# Test UI

`ui/` — React 18 + Vite 5, no framework beyond that, no state library, no
TypeScript. A test harness for the API, not a product surface.

```bash
cd ui && npm install && npm run dev     # http://localhost:3000
```

Vite proxies `/api` → `http://127.0.0.1:8081`, so **start the API first**.

## Files

| File | Contents |
|---|---|
| `src/api.js` (40 ln) | Thin `fetch` wrapper over `/api/v1` — one function per endpoint, unwraps FastAPI's `detail` into `Error.message` |
| `src/App.jsx` (449 ln) | The whole console: interview form, list, expectation view, archetype picker, candidate cards. Plus `Trait` and `CandidateCard` components |
| `src/index.css` (363 ln) | Hand-written styles, no framework |
| `src/main.jsx`, `index.html` | Mount point |

`api.js` covers: `listInterviews`, `createInterview`, `generateExpectation`,
`getExpectation`, `listArchetypes`, `listCandidates`, `enrollCandidates`,
`deleteCandidate`. It does **not** cover the engine-contract or scorecard
endpoints — those are for the Go engine and the grading pipeline, not the
operator.

## Notes

* `ui/` is excluded from ruff and mypy; there is no JS lint or test setup.
* `node_modules/` and `ui/dist/` are gitignored; `package-lock.json` is committed.
* Both AI-calling actions (generate expectation, enroll candidates) are slow — enrollment is one serial model call per archetype. The UI needs to show progress for them; check `App.jsx` before assuming it does.
