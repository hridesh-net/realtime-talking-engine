# SSM Parameter Store (Standard tier, SecureString) instead of Secrets
# Manager: functionally equivalent for "one instance reads a few secrets at
# boot", free vs ~$0.40/secret/mo, and uses the AWS-managed alias/aws/ssm
# key so there's no CMK to pay for either (see iam.tf).
#
# Each parameter is created with a placeholder and Terraform is told to
# ignore future changes to `value`. That means: Terraform never reads,
# stores, or diffs the real secret, so it never lands in state or plan
# output. Set the real value out-of-band after apply, e.g.:
#
#   aws ssm put-parameter \
#     --name "/interview-watcher/prod/GEMINI_API_KEY" \
#     --value "<real key>" --type SecureString --overwrite
#
# (or via the console). See infra/README.md.

resource "aws_ssm_parameter" "gemini_api_key" {
  name  = "/${var.project}/${var.environment}/GEMINI_API_KEY"
  type  = "SecureString"
  value = var.gemini_api_key_placeholder

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "openai_api_key" {
  name  = "/${var.project}/${var.environment}/OPENAI_API_KEY"
  type  = "SecureString"
  value = var.openai_api_key_placeholder

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "control_plane_shared_secret" {
  name  = "/${var.project}/${var.environment}/CONTROL_PLANE_SHARED_SECRET"
  type  = "SecureString"
  value = var.control_plane_shared_secret_placeholder

  lifecycle {
    ignore_changes = [value]
  }
}
