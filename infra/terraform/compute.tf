# Resolved via the SSM public parameter, never a hardcoded AMI id, so the
# instance always launches on the current AL2023 arm64 build without a
# manual bump here.
data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

locals {
  service_user     = "interview-watcher"
  app_dir          = "/opt/${var.project}/app"
  data_mount_path  = "/var/lib/${var.project}"
  env_dir          = "/etc/${var.project}"
  bootstrap_path   = "/opt/${var.project}/bootstrap.sh"
  artifact_key     = "artifacts/${var.project}-latest.tar.gz"
  ssm_param_prefix = "/${var.project}/${var.environment}"
  ui_dist_dir      = "${local.app_dir}/ui_dist"

  caddyfile = templatefile("${path.module}/templates/Caddyfile.tftpl", {
    domain_name        = var.domain_name
    letsencrypt_email  = var.letsencrypt_email
    control_plane_port = var.control_plane_port
    engine_port        = var.engine_port
    ui_dist_dir        = local.ui_dist_dir
  })

  control_plane_service = templatefile("${path.module}/templates/control-plane.service.tftpl", {
    service_user    = local.service_user
    app_dir         = local.app_dir
    data_mount_path = local.data_mount_path
    env_file        = "${local.env_dir}/control-plane.env"
  })

  engined_service = templatefile("${path.module}/templates/engined.service.tftpl", {
    service_user        = local.service_user
    app_dir             = local.app_dir
    data_mount_path     = local.data_mount_path
    env_file            = "${local.env_dir}/engined.env"
    engine_port         = var.engine_port
    dev_sample_contract = var.engine_dev_sample_contract
  })

  bootstrap_script = templatefile("${path.module}/templates/bootstrap.sh.tftpl", {
    app_dir            = local.app_dir
    data_mount_path    = local.data_mount_path
    env_dir            = local.env_dir
    service_user       = local.service_user
    aws_region         = var.aws_region
    s3_bucket          = aws_s3_bucket.main.bucket
    artifact_key       = local.artifact_key
    ssm_param_prefix   = local.ssm_param_prefix
    control_plane_port = var.control_plane_port
    speaker_model_id   = var.speaker_model_id
    thinker_model_id   = var.thinker_model_id
    judge_model_id     = var.judge_model_id
    tts_model_id       = var.tts_model_id
    asr_model_id       = var.asr_model_id
    speaker_vendor     = var.speaker_vendor
  })

  cloud_init = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    service_user              = local.service_user
    bootstrap_path            = local.bootstrap_path
    caddyfile_b64             = base64encode(local.caddyfile)
    control_plane_service_b64 = base64encode(local.control_plane_service)
    engined_service_b64       = base64encode(local.engined_service)
    bootstrap_script_b64      = base64encode(local.bootstrap_script)
  })
}

resource "aws_instance" "main" {
  ami                    = data.aws_ssm_parameter.al2023_arm64.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.instance.id]
  iam_instance_profile   = aws_iam_instance_profile.instance.name
  key_name               = var.ssh_key_name != "" ? var.ssh_key_name : null

  # Gives the instance a public IP at launch, independent of and before the
  # Elastic IP association below — cloud-init needs outbound internet
  # (S3, SSM, Let's Encrypt) from the moment it starts, and EIP association
  # is a separate API call that lands slightly after instance creation.
  associate_public_ip_address = true

  # No NAT gateway (~$32/mo saved): this is the only way this instance
  # reaches the internet, which is why it must live in the public subnet.
  user_data                   = local.cloud_init
  user_data_replace_on_change = true

  metadata_options {
    http_tokens   = "required" # IMDSv2 only.
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true # AWS-managed key (alias/aws/ebs) — no CMK.
    delete_on_termination = true # Root volume holds no state; the data volume (storage.tf) does.
  }

  # Spot roughly halves compute cost but can be interrupted with ~2 minutes'
  # notice; interview data itself is unaffected because it lives on the
  # separate EBS data volume (storage.tf), not the instance. See
  # var.use_spot and infra/README.md.
  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = "terminate"
        spot_instance_type             = "one-time"
      }
    }
  }

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

# Free while attached to a running instance — the cost this stack avoids is
# an ALB, not the address itself.
resource "aws_eip" "main" {
  domain   = "vpc"
  instance = aws_instance.main.id

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}
