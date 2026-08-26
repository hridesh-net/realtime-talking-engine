# infra — interview-watcher AWS deployment

A single EC2 instance running three processes behind Caddy: the Python
control plane (FastAPI), the Go engine (`engined`), and Caddy itself
terminating TLS and serving the built UI. Every cost decision below is
deliberate — see "Cost decisions" for what was left out and why.

**Nothing in this repository has been applied to AWS.** This Terraform was
written and validated (`terraform fmt`, `terraform init -backend=false`,
`terraform validate`) without any AWS credentials, AWS CLI calls, `plan`,
or `apply`. You need to run `terraform apply` yourself.

## Architecture

```
Internet
   │  :80 (ACME HTTP-01 only), :443
   ▼
Elastic IP ── EC2 instance (t4g.small, public subnet, no NAT)
                 ├─ Caddy (:443, TLS via Let's Encrypt)
                 │    ├─ /healthz, /api/*      -> 127.0.0.1:8081 (control plane)
                 │    ├─ /engine/* (strip prefix, WS-aware) -> 127.0.0.1:8080 (engine)
                 │    └─ everything else        -> static ui/dist, SPA fallback
                 ├─ control-plane.service (venv python -m control_plane.main)
                 ├─ engined.service (-dev-sample-contract, see below)
                 └─ data volume (gp3, separate, prevent_destroy) at
                      /var/lib/interview-watcher/{db,recordings,spool}
```

Voice media (WebRTC) never transits this infrastructure — the browser
talks directly to OpenAI. There is no TURN server, no media ports, and no
bandwidth planning here.

## Known interim state: `-dev-sample-contract`

`engined` has no control-plane `ContractSource` yet (implementation-plan
task 46) and **refuses to boot** without `-dev-sample-contract`. With that
flag, every session gets the one checked-in sample persona, not a real one
derived from the job spec. This is accepted, not hidden: it's a Terraform
variable, `engine_dev_sample_contract` (default `true`), with the same
explanation next to its declaration in `variables.tf` and baked into
`engined.service` via `templates/engined.service.tftpl`. Flip it to `false`
only once a real `ContractSource` exists — `engined` will then refuse to
start until one is wired up, which is the correct failure mode.

## Prerequisites

- Terraform >= 1.5.0, AWS provider `~> 5.0` (pinned in `versions.tf`).
- An AWS account/credentials available to the Terraform AWS provider via
  the standard chain (env vars, `~/.aws/credentials`, SSO, etc.) — this
  config never takes a `profile` argument or hardcoded keys.
- A domain you control, for `var.domain_name`. Caddy cannot obtain a TLS
  cert without it — see "DNS and TLS" below.
- Go and Node.js locally (or in CI) to run `infra/build-artifacts.sh`.

## Deploying

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: domain_name, letsencrypt_email, model IDs, etc.

terraform init
terraform apply
```

After the instance exists but before it has anything to run:

```bash
# from repo root, needs real AWS creds with s3:PutObject on the bucket
infra/build-artifacts.sh "$(terraform -chdir=infra/terraform output -raw s3_bucket_name)"
```

Then either wait for the instance's first boot to pull it (if you ran
`build-artifacts.sh` before `terraform apply` finished cloud-init, cloud-init
retries the `aws s3 cp` — it doesn't retry automatically if it already
failed and moved on, so on a chicken-and-egg first apply, reboot the
instance after the artifact exists), or reboot the instance:

```bash
aws ssm start-session --target "$(terraform -chdir=infra/terraform output -raw instance_id)"
```

There is no in-place redeploy mechanism (no orchestrator, single
instance): shipping a new build means running `build-artifacts.sh` again
and rebooting the instance (or re-running `bootstrap.sh` by hand over SSM)
to pick up the new tarball.

## Secrets

`GEMINI_API_KEY`, `OPENAI_API_KEY`, and `CONTROL_PLANE_SHARED_SECRET` are
created as SSM `SecureString` parameters under `/interview-watcher/<env>/`
with a placeholder value (`REPLACE_ME` by default) and
`lifecycle { ignore_changes = [value] }`. **Terraform never manages the
real secret values** — they never land in state or plan output. Set them
after `apply`:

```bash
aws ssm put-parameter \
  --name "/interview-watcher/prod/GEMINI_API_KEY" \
  --type SecureString --overwrite --value "<real key>"
```

(repeat for `OPENAI_API_KEY` and `CONTROL_PLANE_SHARED_SECRET`). The
instance reads these at boot via its IAM role and writes them into
`/etc/interview-watcher/{control-plane,engined}.env`, mode `0600`, owned by
the non-root `interview-watcher` service user. Setting a parameter after
the instance already booted means rebooting (or re-running
`bootstrap.sh`) to pick it up — nothing polls SSM at runtime.

## DNS and TLS

TLS is not optional: the UI calls `navigator.mediaDevices.getUserMedia`
for voice sessions, and browsers refuse microphone access outside a secure
context (HTTPS). A plain-HTTP deployment silently breaks voice.

- Set `var.domain_name` to the hostname Caddy should request a cert for.
- If you set `var.route53_zone_id` (an existing hosted zone), Terraform
  creates an A record pointing at the Elastic IP.
- If you leave it empty, no record is created — point `domain_name` at the
  `elastic_ip` output manually at your DNS provider.

Either way, **Caddy cannot obtain a Let's Encrypt certificate until the
domain actually resolves to the instance's IP.** Until then, HTTPS (and
therefore voice) is broken by design, not by a bug — this is inherent to
ACME HTTP-01/TLS-ALPN-01 validation, not something this stack can route
around.

## Cost decisions (read before changing defaults)

Deliberately **not** used, because at one-instance scale they cost more
than they're worth here:

| Left out | Would cost | Why it's skippable here |
|---|---|---|
| ALB / NLB | ~$18/mo | Caddy on the instance does TLS; one instance doesn't need a load balancer |
| NAT gateway | ~$32/mo | One public subnet, instance has a public IP directly |
| RDS | varies, none free-tier-perpetual | SQLite on the data EBS volume is enough for one instance's state |
| CloudFront / S3 static hosting | CDN request+transfer cost | Caddy serves `ui/dist` directly from the same instance that has the API — no separate origin to front |
| Secrets Manager | ~$0.40/secret/mo | SSM Parameter Store `SecureString` (Standard tier) is free and does the same job for 3 secrets |
| SSH / bastion | instance-hours + a public attack surface | SSM Session Manager is free and needs no open port 22 |
| KMS customer-managed key | ~$1/mo + per-request | AWS-managed keys (`alias/aws/ssm`, `alias/aws/ebs`) cover SSE and EBS encryption at no extra cost for a single-reader setup |

Used instead: `t4g.small` (Graviton, ~20% cheaper than x86 equivalents),
`gp3` everywhere (cheaper per-GB than `gp2`, with a free 3000 IOPS /
125 MiB/s baseline), a minimal single-AZ VPC (VPC/subnet/IGW/route table
are free — only NAT costs money), one Elastic IP (free while attached to a
running instance), and IMDSv2 enforced at no cost.

### Estimated monthly cost — default configuration (`ap-south-1`, on-demand)

| Item | Rate (ap-south-1, on-demand) | Default config | Monthly |
|---|---|---|---|
| EC2 `t4g.small` | $0.0112/hr | 1 instance, 730 hr | ~$8.18 |
| EBS gp3 — root | $0.0912/GB-mo | 8 GB | ~$0.73 |
| EBS gp3 — data volume | $0.0912/GB-mo | 20 GB | ~$1.82 |
| S3 Standard storage | ~$0.025/GB-mo | few hundred MB (artifacts + bundles) | ~$0.10 |
| S3 requests | usage-based | low volume, single-instance reader/writer | negligible |
| Elastic IP | free while attached to a running instance | 1, attached | $0.00 |
| SSM Parameter Store (Standard, SecureString) | free | 3 parameters | $0.00 |
| KMS (AWS-managed keys) | free | `alias/aws/ssm`, `alias/aws/ebs` | $0.00 |
| **Total (on-demand)** | | | **~$10.85/mo** |
| **Total (`use_spot = true`)** | EC2 line roughly halved | | **~$6.75/mo** |

gp3's free baseline (3,000 IOPS, 125 MiB/s throughput) covers this
workload with room to spare, so no IOPS/throughput overage is expected.
Prices per [aws-pricing.com](https://aws-pricing.com/ap-south-1.html) and
[cloudprice.net](https://cloudprice.net/aws/ec2/instances/t4g.small) at
time of writing.

Actual AWS list prices change over time and this is a rough planning
estimate, not a quote — check the [AWS Pricing Calculator](https://calculator.aws)
for current numbers before committing to a budget. Not included: data
transfer to vendor LLM/TTS/ASR APIs (small — text/audio API calls, not
media relay, since voice never transits this infra) and any Route 53
hosted-zone cost (this stack creates a record in an existing zone, not the
zone itself).

### `use_spot`

`var.use_spot` (default `false`) switches the instance to a Spot request,
roughly **halving** the compute line above. The tradeoff: a Spot
interruption (AWS reclaiming the capacity, ~2 minutes' notice) means
downtime — in-flight interview sessions drop — until a new Spot request is
fulfilled. **Interview data is not at risk either way**: the SQLite DB and
recordings live on the separate `aws_ebs_volume.data` (protected by
`prevent_destroy`), not on the instance, and reattach to whatever instance
comes back up.

## What could not be implemented as specified

- **`bootstrap.sh` is templated separately** (`templates/bootstrap.sh.tftpl`)
  rather than being inlined into `cloud-init.yaml.tftpl`'s `runcmd`. The
  task listed only `cloud-init.yaml.tftpl`, `Caddyfile.tftpl`,
  `control-plane.service.tftpl`, and `engined.service.tftpl` as templates,
  but the setup logic (volume detection/format/mount, Caddy install,
  artifact pull, venv, SSM reads, env-file writes, systemd enable) is long
  enough that inlining it as an unreviewable single-line `runcmd` blob
  would itself be the kind of thing the project's "no dead code, nothing
  boots silently in a broken state" bar argues against. It's rendered by
  Terraform and embedded into the cloud-init document base64-encoded, so
  functionally it's still one generated `user_data` payload — this is a
  file-layout deviation, not a behavior gap.
- **`caddy.service` is generated inline inside `cloud-init.yaml.tftpl`**
  (not templated — it has no variable content) rather than via a
  `caddy.service.tftpl`, for the same reason: it wasn't in the listed file
  set, and AL2023 doesn't package Caddy, so *some* systemd unit for it has
  to come from somewhere. Caddy itself is installed from the project's
  official pinned static-binary GitHub release (`v2.8.4` for the target
  arch) inside `bootstrap.sh`, not a dnf/copr repo — Caddy's COPR
  packaging targets Fedora/RHEL/EL derivatives and its AL2023 compatibility
  isn't documented, so a pinned upstream binary is the choice that doesn't
  rest on an unverified assumption.
- **Remote Terraform state (S3 + DynamoDB) is commented out, not wired
  up**, per the task's own instruction (`versions.tf`) — this repo's infra
  has exactly one deployer today, so local state is the honest choice
  until that changes.
- Everything else in the spec (VPC shape, security group rules, IAM
  policy scoping, S3 lifecycle rules, SSM secret handling, the routing
  contract, `-dev-sample-contract` as a visible switch, the data-volume
  `prevent_destroy`, `use_spot`, IMDSv2, the AMI SSM lookup) is implemented
  as specified.

## Verifying without touching AWS

```bash
cd infra/terraform
terraform fmt -recursive
terraform init -backend=false
terraform validate
```

No `plan` or `apply` was run against this configuration, and no AWS CLI
command was executed with real credentials while writing it.
