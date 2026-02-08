# run_tests.ps1 - PowerShell Test Runner for Windows

param(
    [string]$TestType = "all",
    [bool]$Coverage = $true
)

Write-Host "================================" -ForegroundColor Cyan
Write-Host "TrustPlane Test Suite" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Set test environment
$env:ENVIRONMENT = "test"
$env:TEST_DATABASE_URL = if ($env:TEST_DATABASE_URL) { $env:TEST_DATABASE_URL } else { "postgresql://test:test@localhost/trustplane_test" }
$env:JWT_SECRET = "test_secret_key_for_testing_only"

Write-Host "Test Type: $TestType" -ForegroundColor Yellow
Write-Host "Coverage: $Coverage" -ForegroundColor Yellow
Write-Host ""

# Function to run tests
function Run-Tests {
    param(
        [string]$Marker,
        [string]$Description
    )
    
    Write-Host "Running $Description..." -ForegroundColor Yellow
    
    if ($Coverage) {
        pytest -m $Marker --cov=app --cov-report=term-missing
    } else {
        pytest -m $Marker -v
    }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ $Description passed" -ForegroundColor Green
    } else {
        Write-Host "✗ $Description failed" -ForegroundColor Red
        exit 1
    }
    Write-Host ""
}

# Run tests based on type
switch ($TestType) {
    "unit" {
        Run-Tests -Marker "unit" -Description "Unit Tests"
    }
    
    "integration" {
        Run-Tests -Marker "integration" -Description "Integration Tests"
    }
    
    "performance" {
        $env:RUN_PERFORMANCE_TESTS = "true"
        Run-Tests -Marker "performance" -Description "Performance Tests"
    }
    
    "e2e" {
        Run-Tests -Marker "e2e" -Description "End-to-End Tests"
    }
    
    "all" {
        Write-Host "Running all tests..." -ForegroundColor Yellow
        
        # Run unit tests
        Run-Tests -Marker "unit" -Description "Unit Tests"
        
        # Run integration tests
        Run-Tests -Marker "integration" -Description "Integration Tests"
        
        # Run e2e tests
        Run-Tests -Marker "e2e" -Description "End-to-End Tests"
        
        Write-Host "✓ All test suites passed!" -ForegroundColor Green
    }
    
    "coverage" {
        Write-Host "Generating coverage report..." -ForegroundColor Yellow
        pytest --cov=app --cov-report=html --cov-report=term
        Write-Host "Coverage report generated in htmlcov/index.html" -ForegroundColor Green
    }
    
    default {
        Write-Host "Unknown test type: $TestType" -ForegroundColor Red
        Write-Host "Usage: .\run_tests.ps1 -TestType [unit|integration|performance|e2e|all|coverage]"
        exit 1
    }
}

Write-Host ""
Write-Host "================================" -ForegroundColor Green
Write-Host "Test suite completed successfully!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
