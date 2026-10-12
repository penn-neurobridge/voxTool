data "aws_caller_identity" "current" {}

# GitHub Actions CI/CD user. Created only in the dev workspace (shared across
# dev + prod) and only when create_github_actions_user = true. Set that variable
# to false if your AWS user lacks IAM write permissions and have an admin create
# this user instead.
resource "aws_iam_user" "github_actions" {
  count = local.create_ci_user ? 1 : 0
  name  = "${var.project_name}-github-actions"
}

resource "aws_iam_access_key" "github_actions" {
  count = local.create_ci_user ? 1 : 0
  user  = aws_iam_user.github_actions[0].name
}

resource "aws_iam_user_policy" "github_actions" {
  count = local.create_ci_user ? 1 : 0
  name  = "${var.project_name}-github-actions"
  user  = aws_iam_user.github_actions[0].name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowFrontendS3Sync"
        Effect = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:GetObject"
        ]
        Resource = [
          "arn:aws:s3:::${var.project_name}-dev-frontend",
          "arn:aws:s3:::${var.project_name}-dev-frontend/*",
          "arn:aws:s3:::${var.project_name}-prod-frontend",
          "arn:aws:s3:::${var.project_name}-prod-frontend/*"
        ]
      },
      {
        Sid    = "AllowCloudFrontInvalidation"
        Effect = "Allow"
        Action = [
          "cloudfront:CreateInvalidation",
          "cloudfront:GetInvalidation"
        ]
        Resource = "arn:aws:cloudfront::${data.aws_caller_identity.current.account_id}:distribution/*"
      },
      {
        Sid    = "AllowElasticBeanstalkDeploy"
        Effect = "Allow"
        Action = [
          "elasticbeanstalk:*",
          "s3:CreateBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:DeleteObject",
          "cloudformation:*",
          "ec2:Describe*",
          "autoscaling:Describe*"
        ]
        Resource = "*"
      }
    ]
  })
}
