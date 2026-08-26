output "elastic_ip" {
  description = "Public Elastic IP of the instance. If route53_zone_id was left empty, point domain_name at this address manually before Caddy can obtain a TLS certificate."
  value       = aws_eip.main.public_ip
}

output "instance_id" {
  description = "EC2 instance id. Use with SSM Session Manager for shell access: aws ssm start-session --target <instance_id>."
  value       = aws_instance.main.id
}

output "s3_bucket_name" {
  description = "Bucket holding deploy artifacts (artifacts/) and engine session bundles (bundles/). Pass this to infra/build-artifacts.sh."
  value       = aws_s3_bucket.main.bucket
}

output "data_volume_id" {
  description = "EBS volume id holding the SQLite DB and recordings. Protected by prevent_destroy; detach/delete deliberately if it's ever decommissioned."
  value       = aws_ebs_volume.data.id
}

output "ssm_parameter_names" {
  description = "SSM SecureString parameter names created with placeholder values — set the real values out-of-band (see infra/README.md)."
  value = [
    aws_ssm_parameter.gemini_api_key.name,
    aws_ssm_parameter.openai_api_key.name,
    aws_ssm_parameter.control_plane_shared_secret.name,
  ]
}

output "site_url" {
  description = "The URL the deployed app should be reachable at once DNS resolves and Caddy has a certificate."
  value       = var.domain_name != "" ? "https://${var.domain_name}" : "domain_name not set — no site URL yet, see elastic_ip output"
}
