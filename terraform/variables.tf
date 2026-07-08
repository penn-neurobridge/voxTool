variable "aws_region" {
  description = "Primary AWS region for backend and storage"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev or prod). Use Terraform workspaces: terraform workspace select dev"
  type        = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be dev or prod."
  }
}

variable "project_name" {
  description = "Short project prefix for resource names"
  type        = string
  default     = "voxtool"
}

variable "flask_secret_key" {
  description = "Flask secret key for sessions/tokens"
  type        = string
  sensitive   = true
}

variable "python_solution_stack" {
  description = "Elastic Beanstalk Python platform stack"
  type        = string
  default     = "64bit Amazon Linux 2023 v4.13.3 running Python 3.12"
}

variable "eb_instance_type" {
  description = "EC2 instance type for the Flask API"
  type        = string
  default     = "t3.small"
}

variable "eb_min_instances" {
  type    = number
  default = 1
}

variable "eb_max_instances" {
  type    = number
  default = 1
}

variable "eb_availability_zones" {
  description = "AZs for Elastic Beanstalk subnets (exclude AZs that do not support eb_instance_type, e.g. us-east-1e for t3)"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f"]
}

variable "domain_name" {
  description = "Optional root domain for custom URLs (e.g. voxtool.example.com). Leave empty to use CloudFront/EB default URLs."
  type        = string
  default     = ""
}

variable "cors_allowed_origins" {
  description = "Comma-separated CORS origins for the Flask API"
  type        = string
  default     = ""
}

variable "create_github_actions_user" {
  description = "Whether Terraform should create the GitHub Actions CI/CD IAM user. Set false if your AWS user lacks IAM write permissions (ask an admin to create it instead)."
  type        = bool
  default     = true
}
