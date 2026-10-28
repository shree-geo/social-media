import os

# Safe defaults so unit tests run without a .env. Integration tests override via env.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app_runtime:test@localhost:5432/socialcommerce")
os.environ.setdefault("DATABASE_PLATFORM_URL", "postgresql+asyncpg://app_platform:test@localhost:5432/socialcommerce")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-0123")
os.environ.setdefault("ENCRYPTION_KEYS", "v1:" + "A" * 43 + "=")
