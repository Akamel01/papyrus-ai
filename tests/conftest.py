"""Shared test fixtures for SME Research Assistant."""
import os
import pytest
from unittest.mock import MagicMock, AsyncMock

# Set test environment
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=True)
    redis.exists = AsyncMock(return_value=False)
    return redis


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant client."""
    qdrant = MagicMock()
    qdrant.search = AsyncMock(return_value=[])
    qdrant.upsert = AsyncMock(return_value=None)
    qdrant.delete = AsyncMock(return_value=None)
    return qdrant


@pytest.fixture
def sample_user():
    """Sample user data for testing."""
    return {
        "id": "test-user-id",
        "email": "test@example.com",
        "password_hash": "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4UfIQK1.hJHJ6R6y",
    }


@pytest.fixture
def sample_paper():
    """Sample research paper data for testing."""
    return {
        "id": "paper-123",
        "title": "Test Paper on Machine Learning",
        "abstract": "This is a test abstract about machine learning techniques.",
        "authors": ["Author One", "Author Two"],
        "year": 2024,
        "doi": "10.1234/test.paper.123",
    }


@pytest.fixture
def auth_headers(sample_user):
    """Generate auth headers for testing."""
    return {
        "Authorization": "Bearer test-jwt-token",
        "Content-Type": "application/json",
    }
