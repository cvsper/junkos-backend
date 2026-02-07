"""
Testing configuration for JunkOS backend
"""
import os
from config.settings import Config


class TestingConfig(Config):
    """Testing configuration with isolated database and safe defaults"""
    
    TESTING = True
    DEBUG = False
    
    # Use in-memory SQLite for fast tests
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'TEST_DATABASE_URL',
        'sqlite:///:memory:'
    )
    
    # Disable CSRF for testing
    WTF_CSRF_ENABLED = False
    
    # Use simple password hashing for speed
    BCRYPT_LOG_ROUNDS = 4
    
    # Disable email sending
    MAIL_SUPPRESS_SEND = True
    MAIL_DEFAULT_SENDER = 'test@junkos.test'
    
    # Use test Stripe keys
    STRIPE_SECRET_KEY = 'sk_test_mock'
    STRIPE_PUBLISHABLE_KEY = 'pk_test_mock'
    
    # Fast JWT tokens for testing
    JWT_ACCESS_TOKEN_EXPIRES = 300  # 5 minutes
    
    # Disable rate limiting in tests
    RATELIMIT_ENABLED = False
    
    # Use local file storage instead of S3
    UPLOAD_FOLDER = '/tmp/junkos_test_uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    
    # Logging
    LOG_LEVEL = 'WARNING'
    
    # CORS - allow all in tests
    CORS_ORIGINS = ['http://localhost:5173', 'http://localhost:3000']
    
    # Celery - use eager mode (synchronous)
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True
