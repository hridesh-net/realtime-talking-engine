variable "project" {
  description = "Short name used to prefix/tag every resource."
  type        = string
  default     = "interview-watcher"
}

variable "environment" {
  description = "Deployment environment name (e.g. prod, staging)."
  type        = string
  default     = "prod"
}

variable "aws_region" {
  description = "AWS region. Mumbai by default since the engagement is India-based."
  type        = string
  default     = "ap-south-1"
}

# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------

variable "instance_type" {
  description = "EC2 instance type. Graviton (arm64) t4g is ~20% cheaper than the x86 t3 equivalent for this workload."
  type        = string
  default     = "t4g.small"
}

variable "use_spot" {
  description = <<-EOT
    Run the instance as a Spot request instead of On-Demand. Roughly halves
    compute cost, but an interruption means downtime until the Spot request
    is refilled — interview sessions in flight are dropped. Interview data
    itself is safe either way: it lives on the separate EBS data volume
    (see storage.tf), which is not destroyed by a Spot interruption and
    reattaches to whatever instance comes back.
  EOT
  type        = bool
  default     = false
}

variable "root_volume_gb" {
  description = "Root (OS) EBS volume size in GB."
  type        = number
  default     = 8
}

variable "data_volume_gb" {
  description = "Size in GB of the separate encrypted data volume holding the SQLite DB and recordings."
  type        = number
  default     = 20
}

variable "engine_dev_sample_contract" {
  description = <<-EOT
    Passes -dev-sample-contract to engined. The Go engine has no
    control-plane ContractSource yet (implementation-plan task 46) and
    refuses to boot without this flag; with it, every session is served the
    one checked-in sample persona rather than a real one derived from the
    job spec. This is a known, accepted interim state, not a bug — the flag
    is surfaced here as an explicit, visible switch instead of a buried
    hack. Flip to false only once the control-plane ContractSource ships,
    at which point engined will refuse to start until this is false and a
    real contract source is wired up.
  EOT
  type        = bool
  default     = true
}

variable "control_plane_port" {
  description = "Port control_plane/main.py binds uvicorn to (CONTROL_PLANE_PORT)."
  type        = number
  default     = 8081
}

variable "engine_port" {
  description = "Port engined listens on (-addr)."
  type        = number
  default     = 8080
}

variable "ssh_key_name" {
  description = <<-EOT
    Optional EC2 key pair name for emergency console access. Left empty by
    default: operational access is via SSM Session Manager (free, no open
    port 22, see security.tf), not SSH. Set this only if you have a real
    break-glass need for a key pair.
  EOT
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Networking / DNS
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidr" {
  description = "CIDR for the single public subnet the instance lives in."
  type        = string
  default     = "10.0.0.0/24"
}

variable "domain_name" {
  description = "FQDN Caddy will request a Let's Encrypt certificate for (e.g. interview.example.com). Required for TLS to work; see README."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Hosted zone id to create the A record in. Leave empty to manage DNS manually (the Elastic IP is still output)."
  type        = string
  default     = ""
}

variable "letsencrypt_email" {
  description = "Contact email Caddy sends to Let's Encrypt for certificate notices."
  type        = string
  default     = ""
}

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

variable "artifact_retention_days" {
  description = "Days after which objects under the artifacts/ prefix expire."
  type        = number
  default     = 30
}

# ---------------------------------------------------------------------------
# Secrets (SSM Parameter Store placeholders — see ssm.tf and README)
# ---------------------------------------------------------------------------

variable "gemini_api_key_placeholder" {
  description = "Placeholder value written at create time only; Terraform never manages the real secret (lifecycle ignore_changes). Set the real key out-of-band via console or CLI."
  type        = string
  default     = "REPLACE_ME"
  sensitive   = true
}

variable "openai_api_key_placeholder" {
  description = "Placeholder value written at create time only; Terraform never manages the real secret (lifecycle ignore_changes). Set the real key out-of-band via console or CLI."
  type        = string
  default     = "REPLACE_ME"
  sensitive   = true
}

variable "control_plane_shared_secret_placeholder" {
  description = "Placeholder value written at create time only; Terraform never manages the real secret (lifecycle ignore_changes). Set the real value out-of-band via console or CLI."
  type        = string
  default     = "REPLACE_ME"
  sensitive   = true
}

# ---------------------------------------------------------------------------
# Model IDs — required by the engine (engine/internal/config), config not secret
# ---------------------------------------------------------------------------

variable "speaker_model_id" {
  description = "SPEAKER_MODEL_ID for engined. Required by the engine; no code default (operational decision)."
  type        = string
}

variable "thinker_model_id" {
  description = "THINKER_MODEL_ID for engined. Required by the engine; no code default (operational decision)."
  type        = string
}

variable "judge_model_id" {
  description = "JUDGE_MODEL_ID for engined. Required by the engine; no code default (operational decision)."
  type        = string
}

variable "tts_model_id" {
  description = "TTS_MODEL_ID for engined. Required by the engine; no code default (operational decision)."
  type        = string
}

variable "asr_model_id" {
  description = "ASR_MODEL_ID for engined. Required by the engine; no code default (operational decision)."
  type        = string
}

variable "speaker_vendor" {
  description = "Which vendor backs the Speaker adapter: gemini or openai."
  type        = string
  default     = "gemini"
}
