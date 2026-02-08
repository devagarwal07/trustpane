"""
Pytest configuration and fixtures
"""
import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app

# Import all fixtures from fixtures.py
from tests.fixtures import *


@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)


@pytest.fixture
def mock_org_id():
    """Mock organization ID"""
    return str(uuid4())


@pytest.fixture
def mock_user_id():
    """Mock user ID"""
    return str(uuid4())


@pytest.fixture
def mock_tenant_context(mock_org_id, mock_user_id):
    """Mock tenant context"""
    return {
        "org_id": mock_org_id,
        "user_id": mock_user_id,
        "email": "test@example.com",
        "role": "admin"
    }
