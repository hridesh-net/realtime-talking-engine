---
type: Runbook
title: Keeping this bundle current
description: How to update the OKF bundle when code changes — the rule, the routing table, and the conformance check.
resource: /okf
tags: [runbook, okf, maintenance, process]
generated:
  by: claude-opus-5/okf-curator
  at: "2026-08-21T19:17:54Z"
status: stable
sources:
  - resource: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
---
# Keeping this bundle current

**The rule: a code change is not finished until the affected concept is updated
and `log.md` has a line.** This bundle is the standing code reference for agents
working in this repo; a stale page is worse than no page, because it will be
trusted.

## Which page do I touch?

Route from the changed path via the [Repo Map](/concepts/repo-map.md), then:

| Kind of change | Update |
|---|---|
| Function signature or new exported symbol | that file's card in [Modules](/concepts/modules/index.md) |
| Pydantic model, protocol, or JSON schema | the matching page in [Contracts](/concepts/contracts/index.md) — **and** regenerate `owner_handover/` |
| New or removed module | the owning [Subsystem](/concepts/subsystems/index.md) page **and** the [Repo Map](/concepts/repo-map.md) |
| New archetype | [archetypes.py card](/concepts/modules/candidate-agent-archetypes.md) table, [Candidate agent](/concepts/subsystems/candidate-agent.md) table |
| New provider | [llm/factory.py](/concepts/modules/llm-factory.md), [LLM port](/concepts/subsystems/llm-port.md) |
| Anything moving between code-owned and model-owned | [Determinism split](/concepts/determinism.md) — **always**, this is the page that must never be wrong |
| Rubric tables, criteria, weights | [rubric.py card](/concepts/modules/expectation-agent-rubric.md), [InterviewExpectation](/concepts/contracts/interview-expectation.md) |
| Compiled persona prompt | [engine_contract.py card](/concepts/modules/candidate-agent-engine-contract.md), [EngineContract](/concepts/contracts/engine-contract.md) — and bump `ENGINE_CONTRACT_VERSION` |
| New env var | [Dev setup](/concepts/runbooks/dev-setup.md) |
| New endpoint | [REST API](/concepts/contracts/rest-api.md), [api.py card](/concepts/modules/control-plane-api.md) |
| New test file or coverage area | [Test suite](/concepts/subsystems/test-suite.md) — **and** the check table in [Checks](/concepts/runbooks/checks.md) if `check.sh` runs it |
| Shipping something from a "not built" list | [Project Overview](/concepts/project-overview.md) build state |

Then append to `/log.md` under today's date:

```markdown
## 2026-08-22
* **Update**: <what changed in the code> — updated [<page title>](</concepts/path/to/page.md>).
```

Bump `generated.at` on pages you rewrite; add a `verified` entry when you have
checked the page against the source.

## Writing style

* Frontmatter needs `type` at minimum. Prefer also `title`, `description`, `resource`, `tags`, `generated`, `status`.
* Links are bundle-relative, starting with `/`.
* **Document the why and the trap, not the syntax.** Signatures are cheap to re-derive; the reason verbosity wins the turn-policy bounds is not.
* Say plainly when something is not implemented or not tested. The gap lists are load-bearing — they stop an agent assuming a guardrail exists.
* `status: deprecated` for superseded code (e.g. `control_plane/persona.py`), `status: draft` for anything documented from signatures rather than a full read.

## Conformance check

```bash
for f in $(find okf -name '*.md' ! -name 'index.md' ! -name 'log.md'); do
  head -1 "$f" | grep -q '^---$' || echo "missing frontmatter: $f"
  sed -n '2,25p' "$f" | grep -q '^type:' || echo "missing type: $f"
done
```

`index.md` files carry **no** frontmatter except `okf_version` in the bundle root.
Full spec summary: [OKF v0.2](/references/okf-spec.md).

## `.gitignore` — resolved 2026-08-22

The rules that ignored `owner_handover/` and `docs/` — directly above a comment
saying those deliverables were *"tracked on purpose"* — were removed, and the
comment now explains why they must stay tracked. `okf/` is deliberately **not**
ignored: this bundle travels with the repo.
