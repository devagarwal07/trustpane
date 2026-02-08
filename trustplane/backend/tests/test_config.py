"""
Test Configuration

Pytest configuration for different test environments and markers.
"""
import pytest
import os
from typing import Generator
import asyncio


# Test markers
def pytest_configure(config):
    """Register custom pytest markers"""
    config.addinivalue_line(
        "markers", "integration: Integration tests (may require database)"
    )
    config.addinivalue_line(
        "markers", "performance: Performance and load tests"
    )
    config.addinivalue_line(
        "markers", "unit: Unit tests (fast, no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "slow: Slow-running tests"
    )
    config.addinivalue_line(
        "markers", "e2e: End-to-end tests"
    )


# Test environment configuration
@pytest.fixture(scope="session")
def test_env():
    """Test environment configuration"""
    return {
        "ENVIRONMENT": "test",
        "DATABASE_URL": os.getenv("TEST_DATABASE_URL", "postgresql://test:test@localhost/trustplane_test"),
        "SUPABASE_URL": os.getenv("TEST_SUPABASE_URL", "http://localhost:54321"),
        "SUPABASE_KEY": os.getenv("TEST_SUPABASE_KEY", "test_key"),
        "JWT_SECRET": "test_secret_key_for_testing_only",
        "JWT_ALGORITHM": "HS256",
        "LOG_LEVEL": "DEBUG",
    }


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Database fixtures
@pytest.fixture(scope="function")
async def db_session():
    """Database session for tests"""
    # In production, this would create a test database session
    # For now, return a mock
    class MockSession:
        async def execute(self, query):
            return []
        
        async def commit(self):
            pass
        
        async def rollback(self):
            pass
        
        async def close(self):
            pass
    
    session = MockSession()
    yield session
    await session.close()


@pytest.fixture(autouse=True)
async def cleanup_test_database():
    """Clean up test database after each test"""
    yield
    # Cleanup logic
    # In production, would truncate test tables or rollback transactions


# Mock external services
@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for agent tests"""
    class MockCompletion:
        def __init__(self):
            self.choices = [
                type('obj', (object,), {
                    'message': type('obj', (object,), {
                        'content': '{"decision": "escalate", "confidence": 0.85}'
                    })()
                })()
            ]
    
    class MockOpenAI:
        def __init__(self):
            self.chat = self
            self.completions = self
        
        def create(self, *args, **kwargs):
            return MockCompletion()
    
    return MockOpenAI()


@pytest.fixture
def mock_supabase():
    """Mock Supabase client for tests"""
    from tests.fixtures import mock_supabase_client
    return mock_supabase_client()


# Test data cleanup
@pytest.fixture(scope="function")
def test_data_tracker():
    """Track test data for cleanup"""
    created_resources = {
        "workflows": [],
        "slas": [],
        "events": [],
        "notifications": []
    }
    
    yield created_resources
    
    # Cleanup created resources
    # In production, would delete test data


# Logging configuration for tests
@pytest.fixture(autouse=True)
def configure_test_logging():
    """Configure logging for tests"""
    import logging
    
    # Set test log level
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    yield
    
    # Reset logging after test


# Time mocking utilities
@pytest.fixture
def freeze_time():
    """Fixture to freeze time for testing"""
    from datetime import datetime
    from unittest.mock import patch
    
    frozen_time = datetime(2024, 1, 15, 10, 30, 0)
    
    with patch('datetime.datetime') as mock_datetime:
        mock_datetime.utcnow.return_value = frozen_time
        mock_datetime.now.return_value = frozen_time
        yield frozen_time


# Performance test configuration
@pytest.fixture
def performance_threshold():
    """Performance thresholds for tests"""
    return {
        "event_append_ms": 10,          # Max time to append single event
        "workflow_creation_ms": 50,      # Max time to create workflow
        "dashboard_overview_ms": 500,    # Max time for dashboard overview
        "query_100_events_ms": 50,       # Max time to query 100 events
    }


# Test isolation
@pytest.fixture(autouse=True)
def isolate_test():
    """Ensure test isolation"""
    # Setup
    yield
    # Teardown - clear any shared state
    from app.services.workflow_service import _workflow_services
    from app.services.sla_service import _sla_services
    from app.services.notification_service import _notification_services
    
    _workflow_services.clear()
    _sla_services.clear()
    _notification_services.clear()


# Async test utilities
@pytest.fixture
def async_timeout():
    """Timeout for async operations in tests"""
    return 5  # 5 seconds


# Skip markers based on environment
def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers and environment"""
    skip_performance = pytest.mark.skip(reason="Performance tests disabled")
    skip_integration = pytest.mark.skip(reason="Integration tests disabled")
    
    # Check environment variables
    run_performance = os.getenv("RUN_PERFORMANCE_TESTS", "false").lower() == "true"
    run_integration = os.getenv("RUN_INTEGRATION_TESTS", "true").lower() == "true"
    
    for item in items:
        # Skip performance tests unless explicitly enabled
        if "performance" in item.keywords and not run_performance:
            item.add_marker(skip_performance)
        
        # Skip integration tests if disabled
        if "integration" in item.keywords and not run_integration:
            item.add_marker(skip_integration)
