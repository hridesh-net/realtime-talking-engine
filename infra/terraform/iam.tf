# AWS-managed key backing SSM SecureString parameters (alias/aws/ssm). Used
# only to scope the inline policy's kms:Decrypt — no customer-managed key is
# created (that would add ~$1/mo for a single-instance deployment).
data "aws_kms_alias" "ssm" {
  name = "alias/aws/ssm"
}

data "aws_caller_identity" "current" {}

resource "aws_iam_role" "instance" {
  name = "${var.project}-${var.environment}-instance"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Grants SSM Session Manager connectivity (our SSH replacement) plus the
# baseline agent permissions needed for it to check in.
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "instance" {
  name = "${var.project}-${var.environment}-instance"
  role = aws_iam_role.instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSecretParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project}/${var.environment}/*"
      },
      {
        Sid      = "DecryptSecureStringParameters"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = data.aws_kms_alias.ssm.target_key_arn
      },
      {
        Sid      = "ReadDeployArtifacts"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.main.arn}/artifacts/*"
      },
      {
        Sid      = "ListArtifactsPrefix"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.main.arn
        Condition = {
          StringLike = {
            "s3:prefix" = ["artifacts/*"]
          }
        }
      },
      {
        Sid    = "SessionBundleStore"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
        ]
        Resource = "${aws_s3_bucket.main.arn}/bundles/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.project}-${var.environment}-instance"
  role = aws_iam_role.instance.name
}
