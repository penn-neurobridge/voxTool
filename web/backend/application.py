"""Elastic Beanstalk WSGI entry point (expects `application` at module root)."""
from app import create_app

application = create_app()
