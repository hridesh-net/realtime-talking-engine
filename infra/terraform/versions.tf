terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state is deliberately not configured. This stack is a single
  # cost-optimized instance for one environment; a team-shared S3+DynamoDB
  # backend is more operational surface than the deployment currently
  # justifies. Local state is fine as long as exactly one person applies it.
  #
  # To move to remote state later (recommended once more than one person
  # touches this), create the bucket/table out of band (do not bootstrap a
  # backend from the same config it stores state for) and uncomment:
  #
  # backend "s3" {
  #   bucket         = "interview-watcher-tfstate"
  #   key            = "interview-watcher/terraform.tfstate"
  #   region         = "ap-south-1"
  #   dynamodb_table = "interview-watcher-tflock"
  #   encrypt        = true
  # }
}
