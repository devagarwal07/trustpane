"""
Tests for SLA Engine - Core calculation logic

These tests verify the pure calculation logic of the SLA engine
without any I/O or database dependencies.
"""
import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from app.engines.sla_engine import (
    SLAEngine,
    SLATimer,
    BreachCheckResult,
    BreachPrediction,
)
from app.engines.sla_types import (
    SLADefinition,
    SLAInstance,
    SLAStatus,
    SLAPriority,
    BusinessHoursConfig,
    DEFAULT_SLA_TEMPLATES,
)


class TestSLATimer:
    """Tests for SLATimer calculations"""
    
    def test_basic_elapsed_time(self):
        """Timer should calculate simple elapsed time"""
        started = datetime.utcnow() - timedelta(minutes=30)
        timer = SLATimer(started_at=started)
        
        elapsed = timer.get_effective_elapsed()
        
        # Should be approximately 30 minutes in seconds
        assert 29 * 60 <= elapsed <= 31 * 60
    
    def test_paused_timer_does_not_increase(self):
        """Paused timer should not count additional time"""
        started = datetime.utcnow() - timedelta(minutes=60)
        paused = datetime.utcnow() - timedelta(minutes=30)  # Paused 30 mins ago
        
        timer = SLATimer(
            started_at=started,
            paused_at=paused,
            total_paused_seconds=0
        )
        
        # Take measurement
        elapsed1 = timer.get_effective_elapsed()
        
        # Wait a bit (simulated)
        elapsed2 = timer.get_effective_elapsed(
            now=datetime.utcnow() + timedelta(minutes=5)
        )
        
        # Should be the same since timer is paused
        # Both should show ~30 minutes (time before pause)
        assert 29 * 60 <= elapsed1 <= 31 * 60
        assert elapsed1 == elapsed2  # No change while paused
    
    def test_total_paused_time_subtracted(self):
        """Total paused time should be subtracted from elapsed"""
        started = datetime.utcnow() - timedelta(minutes=60)
        total_paused = 20 * 60  # 20 minutes paused
        
        timer = SLATimer(
            started_at=started,
            total_paused_seconds=total_paused
        )
        
        elapsed = timer.get_effective_elapsed()
        
        # 60 minutes wall clock - 20 minutes paused = 40 minutes effective
        assert 39 * 60 <= elapsed <= 41 * 60
    
    def test_is_paused_property(self):
        """is_paused should return correct state"""
        now = datetime.utcnow()
        
        running_timer = SLATimer(started_at=now)
        assert running_timer.is_paused is False
        
        paused_timer = SLATimer(started_at=now, paused_at=now)
        assert paused_timer.is_paused is True


class TestBreachDetection:
    """Tests for breach detection logic"""
    
    @pytest.fixture
    def engine(self):
        return SLAEngine()
    
    @pytest.fixture
    def standard_limits(self):
        return {
            "soft_limit_minutes": 30,
            "hard_limit_minutes": 60
        }
    
    def test_no_breach_within_limits(self, engine, standard_limits):
        """Timer within limits should show no breach"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=15)
        )
        
        result = engine.check_breach(
            timer,
            standard_limits["soft_limit_minutes"],
            standard_limits["hard_limit_minutes"]
        )
        
        assert result.is_soft_breached is False
        assert result.is_hard_breached is False
        assert result.status == SLAStatus.ACTIVE
        assert result.time_to_soft_minutes is not None
        assert result.time_to_soft_minutes > 10  # ~15 minutes left to soft
    
    def test_soft_breach_detected(self, engine, standard_limits):
        """Timer past soft limit should show soft breach"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=45)
        )
        
        result = engine.check_breach(
            timer,
            standard_limits["soft_limit_minutes"],
            standard_limits["hard_limit_minutes"]
        )
        
        assert result.is_soft_breached is True
        assert result.is_hard_breached is False
        assert result.status == SLAStatus.SOFT_BREACH
        assert result.soft_exceeded_by_minutes > 10  # ~15 minutes over
        assert result.time_to_hard_minutes is not None  # Still time to hard
    
    def test_hard_breach_detected(self, engine, standard_limits):
        """Timer past hard limit should show hard breach"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=90)
        )
        
        result = engine.check_breach(
            timer,
            standard_limits["soft_limit_minutes"],
            standard_limits["hard_limit_minutes"]
        )
        
        assert result.is_soft_breached is True  # Hard implies soft
        assert result.is_hard_breached is True
        assert result.status == SLAStatus.HARD_BREACH
        assert result.hard_exceeded_by_minutes > 25  # ~30 minutes over
    
    def test_exact_boundary_soft_breach(self, engine, standard_limits):
        """Timer at exactly soft limit should be breached"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=30)
        )
        
        result = engine.check_breach(
            timer,
            standard_limits["soft_limit_minutes"],
            standard_limits["hard_limit_minutes"]
        )
        
        # At exactly 30 minutes, should be breached (>= comparison)
        assert result.is_soft_breached is True
    
    def test_breach_result_to_dict(self, engine, standard_limits):
        """BreachCheckResult should serialize correctly"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=15)
        )
        
        result = engine.check_breach(
            timer,
            standard_limits["soft_limit_minutes"],
            standard_limits["hard_limit_minutes"]
        )
        
        data = result.to_dict()
        
        assert "status" in data
        assert "is_soft_breached" in data
        assert "is_hard_breached" in data
        assert "elapsed_minutes" in data
        assert isinstance(data["elapsed_minutes"], float)


class TestBreachPrediction:
    """Tests for breach prediction logic"""
    
    @pytest.fixture
    def engine(self):
        return SLAEngine()
    
    def test_low_risk_early_in_sla(self, engine):
        """Early in SLA should have low risk"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=10)
        )
        
        prediction = engine.predict_breach(
            timer,
            soft_limit_minutes=60,
            hard_limit_minutes=120
        )
        
        assert prediction.risk_level in ("minimal", "low")
        assert prediction.probability < 0.3
        assert prediction.will_breach is False
        assert prediction.time_remaining_seconds > 100 * 60  # Over 100 min left
    
    def test_high_risk_near_deadline(self, engine):
        """Near hard deadline should have high risk"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=55)
        )
        
        prediction = engine.predict_breach(
            timer,
            soft_limit_minutes=30,
            hard_limit_minutes=60
        )
        
        assert prediction.risk_level in ("high", "critical")
        assert prediction.probability > 0.6
        assert len(prediction.recommendations) > 0
    
    def test_critical_already_breached(self, engine):
        """Already breached SLA should be critical"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=120)
        )
        
        prediction = engine.predict_breach(
            timer,
            soft_limit_minutes=30,
            hard_limit_minutes=60
        )
        
        assert prediction.risk_level == "critical"
        assert prediction.probability == 1.0
        assert prediction.will_breach is True
        assert prediction.time_remaining_seconds == 0
    
    def test_prediction_to_dict(self, engine):
        """Prediction should serialize correctly"""
        timer = SLATimer(
            started_at=datetime.utcnow() - timedelta(minutes=10)
        )
        
        prediction = engine.predict_breach(
            timer,
            soft_limit_minutes=60,
            hard_limit_minutes=120
        )
        
        data = prediction.to_dict()
        
        assert "will_breach" in data
        assert "probability" in data
        assert "risk_level" in data
        assert "recommendations" in data
        assert "time_remaining_minutes" in data  # Note: converted from seconds


class TestDeadlineCalculation:
    """Tests for deadline calculation"""
    
    @pytest.fixture
    def engine(self):
        return SLAEngine()
    
    def test_simple_deadline_calculation(self, engine):
        """Basic deadline calculation without business hours"""
        started_at = datetime(2024, 1, 15, 10, 0, 0)
        
        soft_deadline, hard_deadline = engine.calculate_deadlines(
            started_at=started_at,
            soft_limit_minutes=30,
            hard_limit_minutes=60,
            business_hours_config=None
        )
        
        assert soft_deadline == datetime(2024, 1, 15, 10, 30, 0)
        assert hard_deadline == datetime(2024, 1, 15, 11, 0, 0)
    
    def test_deadline_spans_midnight(self, engine):
        """Deadline calculation that spans midnight"""
        started_at = datetime(2024, 1, 15, 23, 30, 0)
        
        soft_deadline, hard_deadline = engine.calculate_deadlines(
            started_at=started_at,
            soft_limit_minutes=60,
            hard_limit_minutes=120,
            business_hours_config=None
        )
        
        assert soft_deadline == datetime(2024, 1, 16, 0, 30, 0)
        assert hard_deadline == datetime(2024, 1, 16, 1, 30, 0)


class TestPenaltyCalculation:
    """Tests for penalty calculation logic"""
    
    @pytest.fixture
    def engine(self):
        return SLAEngine()
    
    @pytest.fixture
    def penalty_config(self):
        return {
            "base_amount": 100,
            "per_minute": 5,
            "max_amount": 1000,
            "soft_breach_multiplier": 1.0,
            "hard_breach_multiplier": 2.0,
            "currency": "USD"
        }
    
    def test_soft_breach_penalty(self, engine, penalty_config):
        """Soft breach penalty calculation"""
        result = engine.calculate_penalty(
            breach_type="soft_breach",
            exceeded_by_minutes=10,
            penalty_config=penalty_config
        )
        
        # Base (100) + Time (10 * 5 = 50) * Multiplier (1.0) = 150
        assert result["amount"] == 150.0
        assert result["currency"] == "USD"
        assert result["breach_type"] == "soft_breach"
    
    def test_hard_breach_penalty(self, engine, penalty_config):
        """Hard breach penalty with multiplier"""
        result = engine.calculate_penalty(
            breach_type="hard_breach",
            exceeded_by_minutes=10,
            penalty_config=penalty_config
        )
        
        # (Base (100) + Time (10 * 5 = 50)) * Multiplier (2.0) = 300
        assert result["amount"] == 300.0
        assert result["breakdown"]["multiplier"] == 2.0
    
    def test_penalty_cap(self, engine, penalty_config):
        """Penalty should be capped at max_amount"""
        result = engine.calculate_penalty(
            breach_type="hard_breach",
            exceeded_by_minutes=1000,  # Would be way over cap
            penalty_config=penalty_config
        )
        
        # Should be capped at 1000
        assert result["amount"] == 1000.0
        assert result["breakdown"]["capped"] is True


class TestSLATypes:
    """Tests for SLA type definitions"""
    
    def test_sla_instance_elapsed_calculation(self):
        """SLAInstance should calculate elapsed time correctly"""
        now = datetime.utcnow()
        started = now - timedelta(minutes=45)
        
        instance = SLAInstance(
            id=uuid4(),
            org_id=uuid4(),
            definition_id=uuid4(),
            workflow_id=uuid4(),
            status=SLAStatus.ACTIVE,
            started_at=started,
            total_paused_seconds=5 * 60,  # 5 minutes paused
            created_at=now
        )
        
        # 45 minutes wall clock - 5 minutes paused = 40 minutes effective
        elapsed = instance.elapsed_minutes()
        assert 39 <= elapsed <= 41
    
    def test_sla_instance_remaining_calculation(self):
        """SLAInstance should calculate remaining time correctly"""
        now = datetime.utcnow()
        started = now - timedelta(minutes=20)
        soft_deadline = now + timedelta(minutes=10)  # 10 min remaining
        hard_deadline = now + timedelta(minutes=40)  # 40 min remaining
        
        instance = SLAInstance(
            id=uuid4(),
            org_id=uuid4(),
            definition_id=uuid4(),
            workflow_id=uuid4(),
            status=SLAStatus.ACTIVE,
            started_at=started,
            soft_deadline=soft_deadline,
            hard_deadline=hard_deadline,
            created_at=now
        )
        
        soft_remaining = instance.remaining_to_soft_minutes()
        hard_remaining = instance.remaining_to_hard_minutes()
        
        assert 9 <= soft_remaining <= 11
        assert 39 <= hard_remaining <= 41
    
    def test_sla_instance_is_terminal(self):
        """is_terminal should identify terminal states correctly"""
        base_params = {
            "id": uuid4(),
            "org_id": uuid4(),
            "definition_id": uuid4(),
            "workflow_id": uuid4(),
            "created_at": datetime.utcnow()
        }
        
        # Non-terminal states
        for status in [SLAStatus.PENDING, SLAStatus.ACTIVE]:
            instance = SLAInstance(**base_params, status=status)
            assert instance.is_terminal() is False
        
        # Terminal states
        for status in [SLAStatus.MET, SLAStatus.SOFT_BREACH, SLAStatus.HARD_BREACH, SLAStatus.CANCELLED]:
            instance = SLAInstance(**base_params, status=status)
            assert instance.is_terminal() is True
    
    def test_default_templates_exist(self):
        """Default SLA templates should be defined"""
        assert "p1_critical" in DEFAULT_SLA_TEMPLATES
        assert "p2_high" in DEFAULT_SLA_TEMPLATES
        assert "p3_medium" in DEFAULT_SLA_TEMPLATES
        assert "p4_low" in DEFAULT_SLA_TEMPLATES
    
    def test_p1_critical_template_values(self):
        """P1 critical template should have correct values"""
        p1 = DEFAULT_SLA_TEMPLATES["p1_critical"]
        
        assert p1["soft_limit_minutes"] == 15
        assert p1["hard_limit_minutes"] == 30
        assert p1["priority"] == "p1"
        assert p1["business_hours_only"] is False  # 24/7 for critical
    
    def test_sla_definition_to_dict(self):
        """SLADefinition should serialize correctly"""
        definition = SLADefinition(
            id=uuid4(),
            org_id=uuid4(),
            name="Test SLA",
            soft_limit_minutes=30,
            hard_limit_minutes=60,
            priority=SLAPriority.P2,
            created_at=datetime.utcnow(),
            created_by=uuid4()
        )
        
        data = definition.to_dict()
        
        assert data["name"] == "Test SLA"
        assert data["soft_limit_minutes"] == 30
        assert data["hard_limit_minutes"] == 60
        assert data["priority"] == "p2"


class TestBusinessHoursConfig:
    """Tests for business hours configuration"""
    
    def test_business_hours_weekday_check(self):
        """Business hours should correctly identify business hours"""
        config = BusinessHoursConfig(
            start_hour=9,
            end_hour=17,
            timezone="UTC",
            business_days=[0, 1, 2, 3, 4]  # Mon-Fri
        )
        
        # Wednesday at 10am - should be business hours
        wednesday_10am = datetime(2024, 1, 17, 10, 0, 0)  # Wed
        assert config.is_business_hour(wednesday_10am) is True
        
        # Wednesday at 8am - before business hours
        wednesday_8am = datetime(2024, 1, 17, 8, 0, 0)
        assert config.is_business_hour(wednesday_8am) is False
        
        # Wednesday at 6pm - after business hours
        wednesday_6pm = datetime(2024, 1, 17, 18, 0, 0)
        assert config.is_business_hour(wednesday_6pm) is False
    
    def test_business_hours_weekend_check(self):
        """Weekends should not be business hours"""
        config = BusinessHoursConfig(
            start_hour=9,
            end_hour=17,
            timezone="UTC",
            business_days=[0, 1, 2, 3, 4]  # Mon-Fri
        )
        
        # Saturday at noon - not business hours
        saturday_noon = datetime(2024, 1, 20, 12, 0, 0)  # Sat
        assert config.is_business_hour(saturday_noon) is False
        
        # Sunday at 10am - not business hours
        sunday_10am = datetime(2024, 1, 21, 10, 0, 0)  # Sun
        assert config.is_business_hour(sunday_10am) is False


class TestMetricsCalculation:
    """Tests for aggregate metrics calculation"""
    
    @pytest.fixture
    def engine(self):
        return SLAEngine()
    
    def test_empty_instances_metrics(self, engine):
        """Empty instance list should return zero metrics"""
        metrics = engine.calculate_sla_metrics([], {})
        
        assert metrics["total_count"] == 0
        assert metrics["compliance_rate"] == 1.0  # No failures = 100%
    
    def test_metrics_with_mixed_statuses(self, engine):
        """Metrics should correctly aggregate different statuses"""
        base_params = {
            "org_id": uuid4(),
            "definition_id": uuid4(),
            "workflow_id": uuid4(),
            "started_at": datetime.utcnow() - timedelta(minutes=30),
            "created_at": datetime.utcnow(),
        }
        
        instances = [
            SLAInstance(id=uuid4(), status=SLAStatus.MET, **base_params),
            SLAInstance(id=uuid4(), status=SLAStatus.MET, **base_params),
            SLAInstance(id=uuid4(), status=SLAStatus.SOFT_BREACH, **base_params),
            SLAInstance(id=uuid4(), status=SLAStatus.HARD_BREACH, **base_params),
            SLAInstance(id=uuid4(), status=SLAStatus.ACTIVE, **base_params),
        ]
        
        metrics = engine.calculate_sla_metrics(instances, {})
        
        assert metrics["total_count"] == 5
        assert metrics["met_count"] == 2
        assert metrics["soft_breach_count"] == 1
        assert metrics["hard_breach_count"] == 1
        assert metrics["breached_count"] == 2
        assert metrics["active_count"] == 1
        
        # Compliance: 2 met / (2 met + 2 breached) = 0.5
        assert metrics["compliance_rate"] == 0.5
        assert metrics["compliance_percentage"] == 50.0
