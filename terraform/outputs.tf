output "environment" {
  value = var.environment
}

output "frontend_bucket" {
  value = aws_s3_bucket.frontend.bucket
}

output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "cloudfront_url" {
  value = "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}

output "elastic_beanstalk_url" {
  value = aws_elastic_beanstalk_environment.api.endpoint_url
}

output "api_url" {
  description = "HTTPS API URL for REACT_APP_API_URL (use this instead of the raw EB load balancer URL)"
  value       = "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "elastic_beanstalk_app_name" {
  value = aws_elastic_beanstalk_application.api.name
}

output "elastic_beanstalk_env_name" {
  value = aws_elastic_beanstalk_environment.api.name
}

output "github_actions_access_key" {
  value     = local.create_ci_user ? aws_iam_access_key.github_actions[0].id : null
  sensitive = true
}

output "github_actions_secret_key" {
  value     = local.create_ci_user ? aws_iam_access_key.github_actions[0].secret : null
  sensitive = true
}

output "cors_allowed_origins" {
  value = local.cors_origins
}

output "github_secrets_checklist" {
  description = "Copy these into GitHub repo Settings → Secrets and variables → Actions"
  value = local.create_ci_user ? join("\n", [
    "AWS_ACCESS_KEY_ID     = terraform output -raw github_actions_access_key",
    "AWS_SECRET_ACCESS_KEY = terraform output -raw github_actions_secret_key",
    "CLOUDFRONT_ID_DEV     = ${aws_cloudfront_distribution.frontend.id}",
    # Must be the API CloudFront URL, not the load balancer: the frontend is served
    # over HTTPS, and a browser blocks a plain-HTTP call from an HTTPS page.
    "REACT_APP_API_URL_DEV = https://${aws_cloudfront_distribution.api.domain_name}",
  ]) : "CI user disabled (create_github_actions_user=false or prod workspace). Ask an admin to create the CI IAM user, or run dev workspace with IAM write perms."
}
