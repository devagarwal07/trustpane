# Testing Suite Documentation

## Overview

TrustPlane includes a comprehensive testing suite covering unit tests, integration tests, performance tests, and end-to-end scenarios. The test suite ensures system reliability, correctness, and performance.

## Test Structure

```
tests/
├── conftest.py              # Pytest fixtures and configuration
├── test_config.py           # Test environment configuration
├── fixtures.py              # Reusable test data factories
├── test_*.py               # Unit tests (by component)
├── test_integration.py     # Integration tests
├── test_performance.py     # Performance benchmarks
└── __init__.py
```

## Test Categories

### Unit Tests (Fast)

Isolated tests for individual components without external dependencies.

**Markers**: `@pytest.mark.unit`

**Examples**:
- `test_event_store.py` - Event store operations
- `test_workflow.py` - Workflow state machine
- `test_sla_engine.py` - SLA calculations
- `test_policy_engine.py` - Policy evaluation
- `test_notifications.py` - Notification models
- `test_dashboard.py` - Dashboard models

**Run**: 
```bash
pytest -m unit
```

### Integration Tests (Moderate)

Tests interactions between multiple components, may use test database.

**Markers**: `@pytest.mark.integration`

**Examples**:
- Workflow creation → SLA instance creation
- Agent decision → Notification generation
- Event append → Projection update
- Dashboard aggregation across services

**Run**:
```bash
pytest -m integration
```

### Performance Tests (Slow)

Load and performance benchmarks to ensure system scalability.

**Markers**: `@pytest.mark.performance`

**Tests**:
- Event store write throughput (>100 events/sec)
- Concurrent stream writes (>200 events/sec)
- Workflow creation rate (>20 workflows/sec)
- Dashboard query performance (<500ms)
- Memory usage under load

**Run**:
```bash
RUN_PERFORMANCE_TESTS=true pytest -m performance
```

### End-to-End Tests (E2E)

Complete user scenarios from API request to response.

**Markers**: `@pytest.mark.e2e`

**Scenarios**:
- Create workflow → Start → SLA breach → Notification
- Agent analysis → Decision → Workflow update
- Dashboard overview → Drill-down → Time series

**Run**:
```bash
pytest -m e2e
```

## Running Tests

### Quick Start

```bash
# All tests with coverage
pytest

# Specific test file
pytest tests/test_workflow.py

# Specific test
pytest tests/test_workflow.py::TestWorkflowService::test_create_workflow

# With verbose output
pytest -v

# Stop on first failure
pytest -x
```

### Using Test Scripts

**Linux/Mac**:
```bash
# All tests
./scripts/run_tests.sh all

# Unit tests only
./scripts/run_tests.sh unit

# Integration tests
./scripts/run_tests.sh integration

# Performance tests
./scripts/run_tests.sh performance

# Generate coverage report
./scripts/run_tests.sh coverage
```

**Windows**:
```powershell
# All tests
.\scripts\run_tests.ps1 -TestType all

# Unit tests only
.\scripts\run_tests.ps1 -TestType unit

# With coverage
.\scripts\run_tests.ps1 -TestType all -Coverage $true
```

## Test Fixtures

### Common Fixtures

```python
# Organization and User
@pytest.fixture
def org_id():
    return uuid4()

@pytest.fixture
def user_id():
    return uuid4()

# Services
@pytest.fixture
def mock_workflow_service(org_id):
    return WorkflowService(org_id)

# Test Data
@pytest.fixture
def workflow_payload(org_id, user_id):
    return TestDataFactory.create_workflow_payload(org_id, assignee_id=user_id)

# Auth Headers
@pytest.fixture
def auth_headers(user_id, org_id):
    # Returns JWT token headers
    return {"Authorization": f"Bearer {token}"}
```

### Using Fixtures

```python
@pytest.mark.asyncio
async def test_create_workflow(org_id, user_id, workflow_payload):
    service = WorkflowService(org_id)
    workflow = await service.create_workflow(**workflow_payload, user_id=user_id)
    assert workflow.workflow_id is not None
```

## Test Data Factory

The `TestDataFactory` provides convenient methods for creating test data:

```python
from tests.fixtures import TestDataFactory

# Create test IDs
org_id = TestDataFactory.create_org_id()
user_id = TestDataFactory.create_user_id()

# Create workflow payload
workflow_data = TestDataFactory.create_workflow_payload(
    org_id=org_id,
    workflow_type=WorkflowType.SUPPORT_TICKET,
    priority="high"
)

# Create SLA definition
sla_def = TestDataFactory.create_sla_definition(
    org_id=org_id,
    soft_limit=60,
    hard_limit=120
)

# Create event
event = TestDataFactory.create_event(
    org_id=org_id,
    stream_id=workflow_id,
    event_type="workflow.created",
    payload={"title": "Test"}
)
```

## Coverage

### Generate Coverage Report

```bash
# Terminal output
pytest --cov=app --cov-report=term-missing

# HTML report
pytest --cov=app --cov-report=html
# Open htmlcov/index.html in browser

# XML report (for CI/CD)
pytest --cov=app --cov-report=xml
```

### Coverage Targets

- **Overall**: >80% code coverage
- **Critical paths**: >90% coverage
  - Event store
  - Workflow state machine
  - SLA engine
  - Authentication

### Viewing Coverage

```bash
# Generate and open HTML report
pytest --cov=app --cov-report=html
open htmlcov/index.html  # Mac
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      
      - name: Run tests
        run: |
          pytest --cov=app --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml
```

## Writing Tests

### Test Structure

```python
"""
Test module docstring
"""
import pytest

@pytest.mark.unit  # Mark test category
@pytest.mark.asyncio  # For async tests
async def test_something(fixture1, fixture2):
    """Test description"""
    # Arrange
    setup_data = prepare_test_data()
    
    # Act
    result = await function_under_test(setup_data)
    
    # Assert
    assert result.status == "expected"
    assert result.value > 0
```

### Best Practices

1. **Test Names**: Use descriptive names starting with `test_`
   ```python
   def test_workflow_creation_generates_event()
   def test_sla_breach_triggers_notification()
   ```

2. **Arrange-Act-Assert**: Structure tests clearly
   ```python
   # Arrange
   org_id = uuid4()
   service = WorkflowService(org_id)
   
   # Act
   result = await service.create_workflow(...)
   
   # Assert
   assert result.workflow_id is not None
   ```

3. **One Assertion Per Test**: Test one thing at a time
   ```python
   def test_workflow_has_pending_state():
       workflow = create_workflow()
       assert workflow.current_state == WorkflowState.PENDING
   
   def test_workflow_has_creation_timestamp():
       workflow = create_workflow()
       assert workflow.created_at is not None
   ```

4. **Use Fixtures**: Share setup code
   ```python
   @pytest.fixture
   def sample_workflow(org_id):
       return create_test_workflow(org_id)
   
   def test_workflow_start(sample_workflow):
       sample_workflow.start()
       assert sample_workflow.is_active
   ```

5. **Mock External Dependencies**:
   ```python
   @pytest.fixture
   def mock_openai(monkeypatch):
       def mock_completion(*args, **kwargs):
           return {"choice": "escalate"}
       monkeypatch.setattr("openai.Completion.create", mock_completion)
   ```

## Performance Benchmarks

### Current Targets

| Operation | Target | Current |
|-----------|--------|---------|
| Event append | <10ms | ~5ms |
| Workflow creation | <50ms | ~30ms |
| State transition | <20ms | ~15ms |
| Dashboard overview | <500ms | ~200ms |
| Query 100 events | <50ms | ~25ms |

### Running Benchmarks

```bash
# Run all performance tests
RUN_PERFORMANCE_TESTS=true pytest -m performance -v

# With profiling
pytest -m performance --profile
```

## Troubleshooting

### Common Issues

**1. Tests Hanging**:
```bash
# Check for missing async/await
# Add timeout to pytest.ini:
timeout = 10
```

**2. Database Connection Errors**:
```bash
# Set test database URL
export TEST_DATABASE_URL=postgresql://test:test@localhost/trustplane_test

# Or use SQLite for faster tests
export TEST_DATABASE_URL=sqlite:///./test.db
```

**3. Fixture Not Found**:
```python
# Import fixtures in conftest.py
from tests.fixtures import *
```

**4. Async Test Errors**:
```python
# Use @pytest.mark.asyncio
@pytest.mark.asyncio
async def test_async_function():
    result = await async_operation()
    assert result is not None
```

## Test Environment

### Environment Variables

```bash
# Test configuration
export ENVIRONMENT=test
export TEST_DATABASE_URL=postgresql://test:test@localhost/trustplane_test
export JWT_SECRET=test_secret_key
export LOG_LEVEL=DEBUG

# Disable external services
export SKIP_EXTERNAL_TESTS=true

# Enable performance tests
export RUN_PERFORMANCE_TESTS=true
```

### Test Database Setup

```bash
# Create test database
createdb trustplane_test

# Run migrations
alembic upgrade head

# Seed test data (optional)
python scripts/seed_test_data.py
```

## Continuous Testing

### Watch Mode

```bash
# Install pytest-watch
pip install pytest-watch

# Run in watch mode
ptw -- -v
```

### Pre-commit Hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
pytest -m unit --tb=short
```

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)
- [Testing Best Practices](https://docs.python-guide.org/writing/tests/)
