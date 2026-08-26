# No `profile` and no hardcoded credentials, ever. The provider resolves
# credentials from the standard chain (environment variables, shared config,
# instance/task role) so this config never has to know or care which
# principal is applying it.
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
