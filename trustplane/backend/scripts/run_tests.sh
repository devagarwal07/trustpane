#!/usr/bin/env bash
# run_tests.sh - Test runner script

set -e

echo "================================"
echo "TrustPlane Test Suite"
echo "================================"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Parse arguments
TEST_TYPE=${1:-all}
COVERAGE=${2:-true}

# Set test environment
export ENVIRONMENT=test
export TEST_DATABASE_URL=${TEST_DATABASE_URL:-postgresql://test:test@localhost/trustplane_test}
export JWT_SECRET=test_secret_key_for_testing_only

echo "Test Type: $TEST_TYPE"
echo "Coverage: $COVERAGE"
echo ""

# Function to run tests
run_tests() {
    local marker=$1
    local description=$2
    
    echo -e "${YELLOW}Running $description...${NC}"
    
    if [ "$COVERAGE" = "true" ]; then
        pytest -m "$marker" --cov=app --cov-report=term-missing
    else
        pytest -m "$marker" -v
    fi
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $description passed${NC}"
    else
        echo -e "${RED}✗ $description failed${NC}"
        exit 1
    fi
    echo ""
}

# Run tests based on type
case $TEST_TYPE in
    unit)
        run_tests "unit" "Unit Tests"
        ;;
    
    integration)
        run_tests "integration" "Integration Tests"
        ;;
    
    performance)
        export RUN_PERFORMANCE_TESTS=true
        run_tests "performance" "Performance Tests"
        ;;
    
    e2e)
        run_tests "e2e" "End-to-End Tests"
        ;;
    
    all)
        echo -e "${YELLOW}Running all tests...${NC}"
        
        # Run unit tests
        run_tests "unit" "Unit Tests"
        
        # Run integration tests
        run_tests "integration" "Integration Tests"
        
        # Run e2e tests
        run_tests "e2e" "End-to-End Tests"
        
        echo -e "${GREEN}✓ All test suites passed!${NC}"
        ;;
    
    coverage)
        echo -e "${YELLOW}Generating coverage report...${NC}"
        pytest --cov=app --cov-report=html --cov-report=term
        echo -e "${GREEN}Coverage report generated in htmlcov/index.html${NC}"
        ;;
    
    *)
        echo -e "${RED}Unknown test type: $TEST_TYPE${NC}"
        echo "Usage: ./run_tests.sh [unit|integration|performance|e2e|all|coverage]"
        exit 1
        ;;
esac

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}Test suite completed successfully!${NC}"
echo -e "${GREEN}================================${NC}"
