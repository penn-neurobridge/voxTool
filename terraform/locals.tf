locals {
  name_prefix = "${var.project_name}-${var.environment}"

  frontend_bucket = "${local.name_prefix}-frontend"
  data_bucket     = "${local.name_prefix}-data"

  eb_app_name = "${local.name_prefix}-app"
  eb_env_name = "${local.name_prefix}-env"

  cors_origins = var.cors_allowed_origins != "" ? var.cors_allowed_origins : (
    var.domain_name != "" ? (
      var.environment == "prod"
      ? "https://${var.domain_name},https://www.${var.domain_name},http://localhost:3000"
      : "https://dev.${var.domain_name},http://localhost:3000"
    ) : "http://localhost:3000"
  )

  frontend_subdomain = var.domain_name != "" ? (var.environment == "prod" ? var.domain_name : "dev.${var.domain_name}") : ""
  api_subdomain      = var.domain_name != "" ? (var.environment == "prod" ? "api.${var.domain_name}" : "api.dev.${var.domain_name}") : ""

  # CI user is only created in the dev workspace (shared across dev+prod) and only if enabled.
  create_ci_user = var.create_github_actions_user && var.environment == "dev"
}
