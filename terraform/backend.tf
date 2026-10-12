data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_subnets" "eb" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "availability-zone"
    values = var.eb_availability_zones
  }
}

resource "aws_iam_role" "eb_ec2" {
  name = "${local.name_prefix}-eb-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "eb_web_tier" {
  role       = aws_iam_role.eb_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AWSElasticBeanstalkWebTier"
}

resource "aws_iam_role_policy_attachment" "eb_worker_tier" {
  role       = aws_iam_role.eb_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AWSElasticBeanstalkWorkerTier"
}

resource "aws_iam_role_policy" "eb_s3_data" {
  name = "${local.name_prefix}-eb-s3-data"
  role = aws_iam_role.eb_ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ]
      Resource = [
        aws_s3_bucket.data.arn,
        "${aws_s3_bucket.data.arn}/*"
      ]
    }]
  })
}

resource "aws_iam_instance_profile" "eb_ec2" {
  name = "${local.name_prefix}-eb-ec2"
  role = aws_iam_role.eb_ec2.name
}

resource "aws_security_group" "eb_instances" {
  name        = "${local.name_prefix}-eb-instances"
  description = "Elastic Beanstalk instances for voxTool API"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP from anywhere (via load balancer)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name_prefix}-eb-instances"
    Environment = var.environment
  }
}

resource "aws_elastic_beanstalk_application" "api" {
  name        = local.eb_app_name
  description = "voxTool Flask API (${var.environment})"
}

resource "aws_elastic_beanstalk_environment" "api" {
  name                = local.eb_env_name
  application         = aws_elastic_beanstalk_application.api.name
  solution_stack_name = var.python_solution_stack
  tier                = "WebServer"

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "IamInstanceProfile"
    value     = aws_iam_instance_profile.eb_ec2.name
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "InstanceType"
    value     = var.eb_instance_type
  }

  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "SecurityGroups"
    value     = aws_security_group.eb_instances.id
  }

  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MinSize"
    value     = tostring(var.eb_min_instances)
  }

  setting {
    namespace = "aws:autoscaling:asg"
    name      = "MaxSize"
    value     = tostring(var.eb_max_instances)
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "VPCId"
    value     = data.aws_vpc.default.id
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "Subnets"
    value     = join(",", data.aws_subnets.eb.ids)
  }

  setting {
    namespace = "aws:ec2:vpc"
    name      = "AssociatePublicIpAddress"
    value     = "true"
  }

  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "EnvironmentType"
    value     = "LoadBalanced"
  }

  setting {
    namespace = "aws:elasticbeanstalk:environment:process:default"
    name      = "HealthCheckPath"
    value     = "/api/health"
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "FLASK_ENV"
    value     = var.environment == "prod" ? "production" : "development"
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "FLASK_SECRET_KEY"
    value     = var.flask_secret_key
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "CORS_ALLOWED_ORIGINS"
    value     = local.cors_origins
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "DATA_S3_BUCKET"
    value     = aws_s3_bucket.data.bucket
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "AWS_REGION"
    value     = var.aws_region
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "PORT"
    value     = "8000"
  }

  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "ENABLE_VOLUME_WARM"
    value     = "true"
  }

  tags = {
    Name        = local.eb_env_name
    Environment = var.environment
  }
}
