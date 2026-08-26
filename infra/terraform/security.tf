# No ALB/NLB in front of this instance (~$18/mo saved) — Caddy on the
# instance terminates TLS directly, so the security group is the only
# network boundary and must open exactly what Caddy needs.

resource "aws_security_group" "instance" {
  name        = "${var.project}-${var.environment}-instance"
  description = "Interview-watcher host: HTTP/HTTPS in, everything out. No SSH."
  vpc_id      = aws_vpc.main.id

  tags = {
    Name = "${var.project}-${var.environment}-instance"
  }
}

# NOTE: AWS validates rule descriptions against a restricted charset
# (a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*). Em dashes and apostrophes are
# rejected with InvalidParameterValue, so these stay plain ASCII even
# though the rest of this repo uses em dashes freely in comments.
resource "aws_vpc_security_group_ingress_rule" "http" {
  security_group_id = aws_security_group.instance.id
  description       = "HTTP - required for the ACME HTTP-01 challenge; Caddy redirects the rest to HTTPS."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.instance.id
  description       = "HTTPS - the only real entrypoint (UI, /api, /engine WebSocket)."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.instance.id
  description       = "Unrestricted egress: vendor LLM/TTS/ASR APIs, S3, SSM, package repos."
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}

# Deliberately no ingress rule for port 22. Operational access is via SSM
# Session Manager (aws ssm start-session), which is free and needs no open
# port, no bastion host, and no distributed SSH key — see iam.tf for the
# AmazonSSMManagedInstanceCore policy that makes this work.
