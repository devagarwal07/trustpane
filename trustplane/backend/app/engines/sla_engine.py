"""
SLA Engine - Core SLA processing logic

This is the BRAIN of the SLA system - pure calculation logic with no I/O.
All state is passed in, results are returned, no side effects.

Why this design?
- Testable: Pure functions are easy to unit test
- Reusable: Can be used in batch processing, real-time checks, etc.
- Predictable: Same inputs always produce same outputs
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from uuid import UUID
from dataclasses import dataclass, field
from enum import Enum
import logging

from app.engines.sla_types import (
    SLADefinition,
    SLAInstance,
    SLAStatus,
    SLAPriority,
    BusinessHoursConfig,
    EscalationConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class SLATimer:
    """SLA timer state for calculations"""
    started_at: datetime
    paused_at: Optional[datetime] = None
    total_paused_seconds: float = 0.0
    business_hours_config: Optional[BusinessHoursConfig] = None
    
    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None
    
    def get_effective_elapsed(self, now: Optional[datetime] = None) -> float:
        """
        Get elapsed time in seconds, excluding paused periods.
        
        If business_hours_config is set, only counts business hours.
        """
        now = now or datetime.utcnow()
        
        # Calculate end time for running timer
        if self.is_paused:
            end_time = self.paused_at
        else:
            end_time = now
        
        if self.business_hours_config:
            # Calculate business hours only
            elapsed = self._calculate_business_hours(
                self.started_at, end_time
            )
        else:
            # Calculate wall-clock time
            elapsed = (end_time - self.started_at).total_seconds()
        
        # Subtract paused time
        elapsed -= self.total_paused_seconds
        
        return max(0.0, elapsed)
    
    def _calculate_business_hours(
        self,
        start: datetime,
        end: datetime
    ) -> float:
        """
        Calculate business hours between two datetimes.
        
        This is a simplified implementation. Production would use
        a proper business hours library.
        """
        if not self.business_hours_config:
            return (end - start).total_seconds()
        
        config = self.business_hours_config
        total_seconds = 0.0
        current = start
        
        # Iterate day by day
        while current < end:
            # Check if it's a business day
            if config.is_business_hour(current):
                # Calculate seconds in this hour that are within range
                hour_start = current.replace(minute=0, second=0, microsecond=0)
                hour_end = hour_start + timedelta(hours=1)
                
                # Clamp to our range
                effective_start = max(current, hour_start)
                effective_end = min(end, hour_end)
                
                if effective_end > effective_start:
                    total_seconds += (effective_end - effective_start).total_seconds()
            
            current = current.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        
        return total_seconds


@dataclass
class BreachPrediction:
    """SLA breach prediction result"""
    will_breach: bool
    probability: float  # 0.0 - 1.0
    predicted_breach_at: Optional[datetime]
    time_remaining_seconds: float
    risk_level: str  # low, medium, high, critical
    recommendations: List[str]
    confidence: float = 0.8  # Confidence in the prediction
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "will_breach": self.will_breach,
            "probability": round(self.probability, 3),
            "predicted_breach_at": self.predicted_breach_at.isoformat() if self.predicted_breach_at else None,
            "time_remaining_minutes": round(self.time_remaining_seconds / 60, 2),
            "risk_level": self.risk_level,
            "recommendations": self.recommendations,
            "confidence": self.confidence,
        }


@dataclass
class BreachCheckResult:
    """Result of checking for SLA breach"""
    is_soft_breached: bool = False
    is_hard_breached: bool = False
    soft_exceeded_by_minutes: float = 0.0
    hard_exceeded_by_minutes: float = 0.0
    time_to_soft_minutes: Optional[float] = None
    time_to_hard_minutes: Optional[float] = None
    elapsed_minutes: float = 0.0
    
    @property
    def status(self) -> SLAStatus:
        if self.is_hard_breached:
            return SLAStatus.HARD_BREACH
        elif self.is_soft_breached:
            return SLAStatus.SOFT_BREACH
        else:
            return SLAStatus.ACTIVE
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "is_soft_breached": self.is_soft_breached,
            "is_hard_breached": self.is_hard_breached,
            "soft_exceeded_by_minutes": round(self.soft_exceeded_by_minutes, 2),
            "hard_exceeded_by_minutes": round(self.hard_exceeded_by_minutes, 2),
            "time_to_soft_minutes": round(self.time_to_soft_minutes, 2) if self.time_to_soft_minutes else None,
            "time_to_hard_minutes": round(self.time_to_hard_minutes, 2) if self.time_to_hard_minutes else None,
            "elapsed_minutes": round(self.elapsed_minutes, 2),
        }


class SLAEngine:
    """
    Core SLA processing engine.
    
    Pure calculation logic - no I/O, no side effects.
    All state is passed in, results are returned.
    """
    
    # =========================================================
    # DEADLINE CALCULATIONS
    # =========================================================
    
    def calculate_deadlines(
        self,
        started_at: datetime,
        soft_limit_minutes: int,
        hard_limit_minutes: int,
        business_hours_config: Optional[BusinessHoursConfig] = None
    ) -> Tuple[datetime, datetime]:
        """
        Calculate soft and hard deadline timestamps.
        
        For business hours mode, this is approximate - actual breach
        detection uses elapsed business hours.
        """
        if business_hours_config:
            # For business hours, estimate based on ~8 hour days
            soft_business_days = soft_limit_minutes / (8 * 60)
            hard_business_days = hard_limit_minutes / (8 * 60)
            
            soft_deadline = started_at + timedelta(days=soft_business_days * 1.5)
            hard_deadline = started_at + timedelta(days=hard_business_days * 1.5)
        else:
            soft_deadline = started_at + timedelta(minutes=soft_limit_minutes)
            hard_deadline = started_at + timedelta(minutes=hard_limit_minutes)
        
        return soft_deadline, hard_deadline
    
    # =========================================================
    # BREACH DETECTION
    # =========================================================
    
    def check_breach(
        self,
        timer: SLATimer,
        soft_limit_minutes: int,
        hard_limit_minutes: int,
        now: Optional[datetime] = None
    ) -> BreachCheckResult:
        """
        Check current breach status.
        
        Returns detailed result with status and time remaining.
        """
        now = now or datetime.utcnow()
        elapsed_seconds = timer.get_effective_elapsed(now)
        elapsed_minutes = elapsed_seconds / 60
        
        result = BreachCheckResult(elapsed_minutes=elapsed_minutes)
        
        # Check hard breach first (more severe)
        if elapsed_minutes >= hard_limit_minutes:
            result.is_hard_breached = True
            result.is_soft_breached = True  # Hard implies soft
            result.hard_exceeded_by_minutes = elapsed_minutes - hard_limit_minutes
            result.soft_exceeded_by_minutes = elapsed_minutes - soft_limit_minutes
        
        # Check soft breach
        elif elapsed_minutes >= soft_limit_minutes:
            result.is_soft_breached = True
            result.soft_exceeded_by_minutes = elapsed_minutes - soft_limit_minutes
            result.time_to_hard_minutes = hard_limit_minutes - elapsed_minutes
        
        # No breach yet
        else:
            result.time_to_soft_minutes = soft_limit_minutes - elapsed_minutes
            result.time_to_hard_minutes = hard_limit_minutes - elapsed_minutes
        
        return result
    
    def check_instance_breach(
        self,
        instance: SLAInstance,
        definition: SLADefinition,
        now: Optional[datetime] = None
    ) -> BreachCheckResult:
        """
        Check breach status for an SLA instance.
        
        Convenience method that builds timer from instance.
        """
        if not instance.started_at:
            return BreachCheckResult()
        
        timer = SLATimer(
            started_at=instance.started_at,
            paused_at=instance.paused_at,
            total_paused_seconds=instance.total_paused_seconds,
            business_hours_config=definition.business_hours_config if definition.business_hours_only else None,
        )
        
        return self.check_breach(
            timer,
            definition.soft_limit_minutes,
            definition.hard_limit_minutes,
            now
        )
    
    # =========================================================
    # BREACH PREDICTION
    # =========================================================
    
    def predict_breach(
        self,
        timer: SLATimer,
        soft_limit_minutes: int,
        hard_limit_minutes: int,
        historical_velocity: Optional[float] = None  # Work units per minute
    ) -> BreachPrediction:
        """
        Predict likelihood of SLA breach based on current progress.
        
        Uses simple heuristics. For production, integrate with ML model.
        """
        elapsed_minutes = timer.get_effective_elapsed() / 60
        remaining_to_hard = hard_limit_minutes - elapsed_minutes
        
        # Already breached
        if elapsed_minutes >= hard_limit_minutes:
            return BreachPrediction(
                will_breach=True,
                probability=1.0,
                predicted_breach_at=None,
                time_remaining_seconds=0,
                risk_level="critical",
                recommendations=["⚠️ SLA already breached - immediate escalation required"],
            )
        
        # Calculate risk based on time consumption
        progress_ratio = elapsed_minutes / hard_limit_minutes
        
        if progress_ratio >= 0.9:
            risk_level = "critical"
            probability = 0.95
            confidence = 0.9
        elif progress_ratio >= 0.75:
            risk_level = "high"
            probability = 0.7
            confidence = 0.75
        elif progress_ratio >= 0.5:
            risk_level = "medium"
            probability = 0.4
            confidence = 0.6
        elif progress_ratio >= 0.25:
            risk_level = "low"
            probability = 0.15
            confidence = 0.5
        else:
            risk_level = "minimal"
            probability = 0.05
            confidence = 0.4
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            risk_level, remaining_to_hard, progress_ratio
        )
        
        # Predict breach time
        predicted_breach_at = None
        if probability > 0.5:
            predicted_breach_at = datetime.utcnow() + timedelta(minutes=remaining_to_hard)
        
        return BreachPrediction(
            will_breach=probability > 0.5,
            probability=probability,
            predicted_breach_at=predicted_breach_at,
            time_remaining_seconds=max(0, remaining_to_hard * 60),
            risk_level=risk_level,
            recommendations=recommendations,
            confidence=confidence,
        )
    
    def _generate_recommendations(
        self,
        risk_level: str,
        remaining_minutes: float,
        progress_ratio: float
    ) -> List[str]:
        """Generate actionable recommendations based on risk level"""
        recommendations = []
        
        if risk_level == "critical":
            recommendations.extend([
                "🚨 Escalate to senior team member immediately",
                "Consider reassigning to specialist",
                "Document all delays and causes for post-mortem",
                f"Only {remaining_minutes:.0f} minutes remaining",
            ])
        elif risk_level == "high":
            recommendations.extend([
                "⚠️ Prioritize this workflow over others",
                "Alert stakeholders of potential SLA risk",
                "Consider requesting additional resources",
                f"~{remaining_minutes:.0f} minutes remaining ({(1-progress_ratio)*100:.0f}% of time left)",
            ])
        elif risk_level == "medium":
            recommendations.extend([
                "📊 Monitor progress closely",
                "Ensure no blockers are present",
                f"~{remaining_minutes:.0f} minutes remaining",
            ])
        elif risk_level == "low":
            recommendations.extend([
                "✅ On track - continue normal processing",
                f"Plenty of time remaining (~{remaining_minutes:.0f} min)",
            ])
        else:
            recommendations.append("✅ Well within SLA bounds")
        
        return recommendations
    
    # =========================================================
    # PAUSE/RESUME CALCULATIONS
    # =========================================================
    
    def calculate_pause_duration(
        self,
        paused_at: datetime,
        resumed_at: datetime
    ) -> float:
        """Calculate pause duration in seconds"""
        return (resumed_at - paused_at).total_seconds()
    
    def should_pause_for_state(
        self,
        workflow_state: str,
        excluded_states: set
    ) -> bool:
        """Check if SLA should be paused for this workflow state"""
        return workflow_state.lower() in {s.lower() for s in excluded_states}
    
    # =========================================================
    # PENALTY CALCULATIONS
    # =========================================================
    
    def calculate_penalty(
        self,
        breach_type: str,
        exceeded_by_minutes: float,
        penalty_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate financial penalty for SLA breach.
        
        penalty_config example:
        {
            "base_amount": 100,
            "per_minute": 5,
            "max_amount": 1000,
            "soft_breach_multiplier": 1.0,
            "hard_breach_multiplier": 2.0,
            "currency": "USD"
        }
        """
        base = penalty_config.get("base_amount", 0)
        per_minute = penalty_config.get("per_minute", 0)
        max_amount = penalty_config.get("max_amount", float("inf"))
        
        if breach_type == "hard_breach":
            multiplier = penalty_config.get("hard_breach_multiplier", 2.0)
        else:
            multiplier = penalty_config.get("soft_breach_multiplier", 1.0)
        
        time_penalty = per_minute * exceeded_by_minutes
        calculated = (base + time_penalty) * multiplier
        final = min(calculated, max_amount)
        
        return {
            "amount": round(final, 2),
            "currency": penalty_config.get("currency", "USD"),
            "breach_type": breach_type,
            "exceeded_by_minutes": round(exceeded_by_minutes, 2),
            "breakdown": {
                "base_penalty": base,
                "time_penalty": round(time_penalty, 2),
                "multiplier": multiplier,
                "pre_cap_amount": round(calculated, 2),
                "capped": calculated > max_amount,
            }
        }
    
    # =========================================================
    # REPORTING HELPERS
    # =========================================================
    
    def calculate_sla_metrics(
        self,
        instances: List[SLAInstance],
        definitions: Dict[UUID, SLADefinition]
    ) -> Dict[str, Any]:
        """
        Calculate aggregate SLA metrics for reporting.
        
        Returns compliance rates, average response times, etc.
        """
        if not instances:
            return {
                "total_count": 0,
                "met_count": 0,
                "breached_count": 0,
                "compliance_rate": 1.0,
                "avg_elapsed_minutes": 0,
            }
        
        met_count = sum(1 for i in instances if i.status == SLAStatus.MET)
        soft_breach_count = sum(1 for i in instances if i.status == SLAStatus.SOFT_BREACH)
        hard_breach_count = sum(1 for i in instances if i.status == SLAStatus.HARD_BREACH)
        breached_count = soft_breach_count + hard_breach_count
        
        # Only count completed instances for compliance
        completed = [i for i in instances if i.is_terminal()]
        compliance_rate = met_count / len(completed) if completed else 1.0
        
        # Average elapsed time
        elapsed_times = [i.elapsed_minutes() for i in instances if i.started_at]
        avg_elapsed = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
        
        return {
            "total_count": len(instances),
            "active_count": sum(1 for i in instances if i.status == SLAStatus.ACTIVE),
            "met_count": met_count,
            "soft_breach_count": soft_breach_count,
            "hard_breach_count": hard_breach_count,
            "breached_count": breached_count,
            "compliance_rate": round(compliance_rate, 4),
            "compliance_percentage": round(compliance_rate * 100, 2),
            "avg_elapsed_minutes": round(avg_elapsed, 2),
            "by_status": {
                status.value: sum(1 for i in instances if i.status == status)
                for status in SLAStatus
            },
        }


# Singleton instance
sla_engine = SLAEngine()
