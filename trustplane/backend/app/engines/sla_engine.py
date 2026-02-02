"""
SLA Engine - Core SLA processing logic
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from uuid import UUID
from dataclasses import dataclass
from enum import Enum


@dataclass
class SLATimer:
    """SLA timer state"""
    started_at: datetime
    paused_at: Optional[datetime]
    total_paused_seconds: float
    elapsed_seconds: float
    
    @property
    def is_paused(self) -> bool:
        return self.paused_at is not None
    
    def get_effective_elapsed(self) -> float:
        """Get elapsed time excluding paused periods"""
        if self.is_paused:
            return self.elapsed_seconds
        
        now = datetime.utcnow()
        running_seconds = (now - self.started_at).total_seconds()
        return running_seconds - self.total_paused_seconds


@dataclass
class BreachPrediction:
    """SLA breach prediction result"""
    will_breach: bool
    probability: float  # 0.0 - 1.0
    predicted_breach_at: Optional[datetime]
    time_remaining_seconds: float
    risk_level: str  # low, medium, high, critical
    recommendations: List[str]


class SLAEngine:
    """
    Core SLA processing engine.
    Handles timer logic, breach detection, and predictions.
    """
    
    def calculate_deadlines(
        self,
        started_at: datetime,
        soft_limit_minutes: int,
        hard_limit_minutes: int
    ) -> tuple[datetime, datetime]:
        """Calculate soft and hard deadlines"""
        soft_deadline = started_at + timedelta(minutes=soft_limit_minutes)
        hard_deadline = started_at + timedelta(minutes=hard_limit_minutes)
        return soft_deadline, hard_deadline
    
    def check_breach_status(
        self,
        timer: SLATimer,
        soft_limit_minutes: int,
        hard_limit_minutes: int
    ) -> Dict[str, Any]:
        """Check current breach status"""
        elapsed_minutes = timer.get_effective_elapsed() / 60
        
        if elapsed_minutes >= hard_limit_minutes:
            return {
                "status": "hard_breach",
                "exceeded_by_minutes": elapsed_minutes - hard_limit_minutes
            }
        elif elapsed_minutes >= soft_limit_minutes:
            return {
                "status": "soft_breach",
                "exceeded_by_minutes": elapsed_minutes - soft_limit_minutes
            }
        else:
            return {
                "status": "ok",
                "time_to_soft_breach_minutes": soft_limit_minutes - elapsed_minutes,
                "time_to_hard_breach_minutes": hard_limit_minutes - elapsed_minutes
            }
    
    def predict_breach(
        self,
        timer: SLATimer,
        soft_limit_minutes: int,
        hard_limit_minutes: int,
        historical_completion_rate: float = 0.0  # Minutes per unit of work
    ) -> BreachPrediction:
        """Predict likelihood of SLA breach"""
        elapsed_minutes = timer.get_effective_elapsed() / 60
        remaining_to_hard = hard_limit_minutes - elapsed_minutes
        
        # Simple prediction based on elapsed time percentage
        progress_ratio = elapsed_minutes / hard_limit_minutes
        
        if progress_ratio >= 1.0:
            return BreachPrediction(
                will_breach=True,
                probability=1.0,
                predicted_breach_at=None,
                time_remaining_seconds=0,
                risk_level="critical",
                recommendations=["Immediate escalation required"]
            )
        
        # Risk levels based on time consumption
        if progress_ratio >= 0.9:
            risk_level = "critical"
            probability = 0.95
        elif progress_ratio >= 0.75:
            risk_level = "high"
            probability = 0.7
        elif progress_ratio >= 0.5:
            risk_level = "medium"
            probability = 0.4
        else:
            risk_level = "low"
            probability = 0.1
        
        recommendations = self._generate_recommendations(risk_level, remaining_to_hard)
        
        return BreachPrediction(
            will_breach=probability > 0.5,
            probability=probability,
            predicted_breach_at=datetime.utcnow() + timedelta(minutes=remaining_to_hard) if probability > 0.5 else None,
            time_remaining_seconds=remaining_to_hard * 60,
            risk_level=risk_level,
            recommendations=recommendations
        )
    
    def _generate_recommendations(
        self,
        risk_level: str,
        remaining_minutes: float
    ) -> List[str]:
        """Generate recommendations based on risk level"""
        recommendations = []
        
        if risk_level == "critical":
            recommendations.append("Escalate to senior team member immediately")
            recommendations.append("Consider applying penalty waiver if justified")
            recommendations.append("Document all delays and their causes")
        elif risk_level == "high":
            recommendations.append("Prioritize this workflow")
            recommendations.append("Consider reassigning to available resources")
            recommendations.append("Alert stakeholders of potential delay")
        elif risk_level == "medium":
            recommendations.append("Monitor progress closely")
            recommendations.append(f"~{remaining_minutes:.0f} minutes remaining")
        else:
            recommendations.append("On track - continue normal processing")
        
        return recommendations
    
    def calculate_penalty(
        self,
        breach_type: str,
        exceeded_by_minutes: float,
        penalty_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate penalty based on breach severity and config"""
        base_penalty = penalty_config.get("base_amount", 0)
        per_minute_penalty = penalty_config.get("per_minute", 0)
        max_penalty = penalty_config.get("max_amount", float("inf"))
        
        if breach_type == "hard_breach":
            multiplier = penalty_config.get("hard_breach_multiplier", 2.0)
        else:
            multiplier = penalty_config.get("soft_breach_multiplier", 1.0)
        
        calculated = (base_penalty + (per_minute_penalty * exceeded_by_minutes)) * multiplier
        final_penalty = min(calculated, max_penalty)
        
        return {
            "amount": final_penalty,
            "currency": penalty_config.get("currency", "USD"),
            "breakdown": {
                "base": base_penalty,
                "time_based": per_minute_penalty * exceeded_by_minutes,
                "multiplier": multiplier
            }
        }


# Singleton instance
sla_engine = SLAEngine()
