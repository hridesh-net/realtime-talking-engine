# interview-watcher — project instructions

Interview **control plane**: creates interviews from a job spec, generates
deterministic interviewer expectations, and casts virtual candidate personas
that human interviewers practise against. The real-time runtime is a separate
Go/Rust build; this service owns the "what" of an interview.

## Code reference: read `okf/` first

`okf/` is a curated [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
v0.2 knowledge bundle describing this repo. **Use it as the primary code
reference instead of re-reading the tree.** Start at `okf/index.md`, then
`okf/concepts/repo-map.md` to route from a path to the right page.

Read `okf/concepts/determinism.md` before touching either agent — the split
between what code owns and what the model may author is the organizing rule of
this codebase.

**A code change is not finished until the affected concept is updated and
`okf/log.md` has a line.** Process: `okf/concepts/runbooks/okf-maintenance.md`.

## Hard rules (enforced by `tests/test_architecture.py`)

- Vendor SDKs only inside `llm/`. Agents take an injected model and never read API keys.
- Handlers depend on the narrowest port in `control_plane/ports.py`, never on `InterviewRepository`.
- Agents never import `sqlite3` or `control_plane`, and never persist.
- Dependencies point one way: `llm` ← agents ← `control_plane`. No relative imports.
- Model IDs are config, never hardcoded — see `.env.example`.

## Commands

```bash
scripts/check.sh                 # lint, format, types, architecture, schemas — offline
scripts/check.sh --live          # also the model scenario tests (costs money)
.venv/bin/python -m control_plane.main       # API on :8081
cd ui && npm run dev                          # UI on :3000 (start the API first)
```

Any change to a public Pydantic model requires
`.venv/bin/python scripts/export_schemas.py` or CI fails.
