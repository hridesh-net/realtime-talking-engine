# Minimal VPC: one public subnet, one IGW, one route table. The VPC, subnet,
# IGW and route table themselves are free — only a NAT gateway costs money,
# and this stack deliberately has none (see security.tf / README for the
# cost rationale). The instance gets a public IP directly instead.

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.project}-${var.environment}"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidr
  map_public_ip_on_launch = true

  # Single-AZ by design: this is one instance, not a fleet. Multi-AZ HA
  # would need a second subnet, a load balancer, and shared state — the
  # exact cost this stack exists to avoid.
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name = "${var.project}-${var.environment}-public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.project}-${var.environment}-public"
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

data "aws_availability_zones" "available" {
  state = "available"
}
