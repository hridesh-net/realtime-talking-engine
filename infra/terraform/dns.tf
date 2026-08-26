# Optional: only created when var.route53_zone_id is supplied. Left empty,
# no record is created and outputs.tf surfaces the Elastic IP with a note
# to point DNS at it manually. Either way, Caddy cannot obtain a Let's
# Encrypt certificate for var.domain_name until that name actually resolves
# to this instance — see infra/README.md.
resource "aws_route53_record" "main" {
  count = var.route53_zone_id != "" ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.main.public_ip]
}
