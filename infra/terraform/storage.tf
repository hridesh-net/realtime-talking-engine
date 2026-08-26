# One bucket, two purposes: deploy artifacts under artifacts/ (built UI +
# engined binary + Python source, pushed by infra/build-artifacts.sh) and
# the engine's session-bundle store under bundles/. The engine's S3_BUCKET/
# S3_REGION config is required at boot (internal/store/s3 is still a stub,
# but the config gate isn't) — pointing it at this bucket's bundles/ prefix
# avoids standing up a second bucket for a feature that doesn't write
# anything yet.
#
# No CloudFront / no S3 static website hosting: Caddy on the instance
# serves ui/dist directly, so a CDN in front of a single-instance origin
# would just be extra cost with no cache-hit benefit at this scale.
resource "aws_s3_bucket" "main" {
  bucket = "${var.project}-${var.environment}-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# SSE-S3, not a KMS CMK — a customer-managed key adds ~$1/mo for
# key storage plus per-request charges that buy nothing extra here, since
# the only reader/writer is this instance's own role.
resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    # Applies bucket-wide (empty filter) so a stalled multipart upload to
    # either prefix doesn't sit around accruing storage cost.
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-deploy-artifacts"
    status = "Enabled"

    filter {
      prefix = "artifacts/"
    }

    expiration {
      days = var.artifact_retention_days
    }
  }

  # No expiration rule for bundles/ — session bundles are interview data,
  # not a build byproduct, and get pruned by application policy (if ever),
  # not a blanket bucket lifecycle rule.
}

# ---------------------------------------------------------------------------
# Data volume: SQLite DB + recordings live here, separate from the root
# volume, so replacing the instance (AMI update, instance-type change, spot
# interruption recovery) never touches interview data. prevent_destroy means
# `terraform destroy` — or a change that would force replacement — refuses
# to take this volume out; it must be detached/deleted deliberately.
# ---------------------------------------------------------------------------
resource "aws_ebs_volume" "data" {
  availability_zone = aws_subnet.public.availability_zone
  size              = var.data_volume_gb
  type              = "gp3"
  encrypted         = true # AWS-managed key (alias/aws/ebs) — no CMK, see iam.tf note.

  tags = {
    Name = "${var.project}-${var.environment}-data"
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Device name is a request, not a guarantee: on Nitro-based instances
# (t4g is Nitro) EBS volumes surface as NVMe devices, so this may appear as
# /dev/xvdf, /dev/nvme1n1, or occasionally another nvme index rather than
# literally /dev/sdf. cloud-init resolves the real device by probing the
# known candidates and pins the mount by filesystem UUID, not device path,
# so the exact kernel name doesn't matter after first boot.
resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.main.id

  # Detach on instance replacement instead of failing the apply; the
  # volume's own prevent_destroy is what actually protects the data.
  force_detach                   = false
  stop_instance_before_detaching = true
}
