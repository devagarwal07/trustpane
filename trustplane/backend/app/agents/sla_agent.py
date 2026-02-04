"""
SLA Risk Agent

Analyzes SLA compliance, predicts breaches, and recommends actions.
This agent monitors SLA health and provides early warning for at-risk workflows.
"""

from typing import Any, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.agents.base import (
    BaseAgent, AgentType, AgentDecision, AgentContext,
    DecisionConfidence, DecisionType
)


class SLAAgent(BaseAgent):
    """
    SLA Risk Assessment Agent.
    
    Responsibilities:
    - Monitor SLA timers and deadlines
    - Predict breach probability
    - Recommend escalations
    - Suggest priority adjustments
    - Flag at-risk workflows
    
    Decision output includes:
    - Risk level (low/medium/high/critical)
    - Breach probability (0.0 to 1.0)
    - Time to breach
    - Recommended actions
    """
    
    # Risk thresholds
    CRITICAL_THRESHOLD_MINUTES = 15
    HIGH_THRESHOLD_MINUTES = 60
    MEDIUM_THRESHOLD_MINUTES = 240
    
    # Breach probability thresholds
    HIGH_BREACH_PROB = 0.8
    MEDIUM_BREACH_PROB = 0.5
    
    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(
            agent_type=AgentType.SLA_RISK,
            agent_id=agent_id,
            model="gpt-4o",
            temperature=0.0,
        )
    
    @property
    def system_prompt(self) -> str:
        return """You are the SLA Risk Agent for TrustPlane, a B2B SaaS platform.

Your role is to analyze SLA compliance data and make risk assessments.

RULES:
1. Be conservative - flag risks early rather than late
2. Provide specific, actionable recommendations  
3. Always explain your reasoning with evidence
4. Never make assumptions about missing data
5. If unsure, recommend human review
6. Consider historical patterns when available

INPUTS YOU RECEIVE:
- SLA deadline and time remaining
- Current breach level (none/soft/hard)
- Workflow state and priority
- Historical similar workflows
- Event history

OUTPUT (JSON):
{
    "risk_level": "low|medium|high|critical",
    "breach_probability": 0.0 to 1.0,
    "time_to_breach_minutes": number or null,
    "contributing_factors": ["factor1", "factor2"],
    "recommendations": ["action1", "action2"],
    "suggested_priority": "low|normal|high|urgent" or null,
    "should_escalate": boolean,
    "escalation_reason": string or null,
    "confidence": "high|medium|low",
    "reasoning": "detailed explanation"
}

RISK LEVELS:
- critical: <15 min to breach OR hard breach imminent
- high: <1 hour to breach OR soft breach occurred  
- medium: <4 hours to breach OR workflow stalled
- low: On track, no concerns

Remember: You analyze and recommend. You do NOT execute changes."""

    async def analyze(self, context: AgentContext) -> dict[str, Any]:
        """
        Analyze SLA risk factors.
        
        Examines:
        - Time remaining until deadline
        - Current breach status
        - Workflow velocity
        - Historical patterns
        """
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "sla_id": str(context.sla_id) if context.sla_id else None,
            "workflow_id": str(context.workflow_id) if context.workflow_id else None,
        }
        
        # Calculate time-based risk
        time_remaining = context.sla_time_remaining_seconds
        if time_remaining is not None:
            minutes_remaining = time_remaining / 60
            
            analysis["minutes_remaining"] = minutes_remaining
            analysis["time_risk"] = self._calculate_time_risk(minutes_remaining)
        else:
            analysis["minutes_remaining"] = None
            analysis["time_risk"] = "unknown"
        
        # Analyze current breach status
        breach_level = context.sla_breach_level or "none"
        analysis["current_breach_level"] = breach_level
        analysis["breach_risk"] = self._assess_breach_risk(breach_level)
        
        # Analyze workflow state
        workflow_state = context.workflow_state
        analysis["workflow_state"] = workflow_state
        analysis["state_risk"] = self._assess_state_risk(workflow_state)
        
        # Check if SLA is paused
        analysis["is_paused"] = context.sla_is_paused or False
        
        # Analyze velocity from event history
        if context.event_history:
            analysis["velocity"] = self._calculate_velocity(context.event_history)
        else:
            analysis["velocity"] = {"status": "unknown", "events_per_hour": 0}
        
        # Historical pattern analysis
        if context.similar_workflows:
            analysis["historical_pattern"] = self._analyze_historical(context.similar_workflows)
        else:
            analysis["historical_pattern"] = {"available": False}
        
        # Calculate overall risk score
        analysis["risk_score"] = self._calculate_risk_score(analysis)
        
        return analysis
    
    async def decide(self, analysis: dict[str, Any], context: AgentContext) -> AgentDecision:
        """
        Make SLA risk decision based on analysis.
        """
        risk_score = analysis.get("risk_score", 0.5)
        minutes_remaining = analysis.get("minutes_remaining")
        breach_level = analysis.get("current_breach_level", "none")
        is_paused = analysis.get("is_paused", False)
        
        # Determine risk level
        risk_level = self._determine_risk_level(risk_score, minutes_remaining, breach_level)
        
        # Build recommendations
        recommendations = self._build_recommendations(analysis, risk_level)
        
        # Determine decision type
        if risk_level == "critical":
            decision_type = DecisionType.ESCALATE
            requires_human = True
            is_urgent = True
        elif risk_level == "high":
            decision_type = DecisionType.ALERT
            requires_human = True
            is_urgent = True
        elif risk_level == "medium":
            decision_type = DecisionType.RECOMMEND
            requires_human = False
            is_urgent = False
        else:
            decision_type = DecisionType.APPROVE
            requires_human = False
            is_urgent = False
        
        # Calculate confidence
        confidence_factors = {
            "data_completeness": 1.0 if minutes_remaining is not None else 0.5,
            "breach_clarity": 1.0 if breach_level != "unknown" else 0.6,
            "history_available": 0.9 if analysis.get("historical_pattern", {}).get("available") else 0.7,
        }
        confidence = self._calculate_confidence(confidence_factors)
        
        # Build reasoning
        reasoning = self._build_reasoning(analysis, risk_level)
        
        # Build evidence
        evidence = []
        if minutes_remaining is not None:
            evidence.append(f"Time remaining: {minutes_remaining:.0f} minutes")
        if breach_level != "none":
            evidence.append(f"Current breach level: {breach_level}")
        if analysis.get("velocity", {}).get("status") == "slow":
            evidence.append("Workflow velocity is slower than expected")
        
        return AgentDecision(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            decision_type=decision_type,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            recommendations=recommendations,
            suggested_action=recommendations[0] if recommendations else None,
            requires_human_review=requires_human,
            is_urgent=is_urgent,
            model_used=self.model,
        )
    
    def _calculate_time_risk(self, minutes_remaining: float) -> str:
        """Calculate risk based on time remaining."""
        if minutes_remaining <= self.CRITICAL_THRESHOLD_MINUTES:
            return "critical"
        elif minutes_remaining <= self.HIGH_THRESHOLD_MINUTES:
            return "high"
        elif minutes_remaining <= self.MEDIUM_THRESHOLD_MINUTES:
            return "medium"
        else:
            return "low"
    
    def _assess_breach_risk(self, breach_level: str) -> str:
        """Assess risk based on current breach level."""
        if breach_level == "hard":
            return "critical"
        elif breach_level == "soft":
            return "high"
        else:
            return "low"
    
    def _assess_state_risk(self, workflow_state: Optional[str]) -> str:
        """Assess risk based on workflow state."""
        if not workflow_state:
            return "unknown"
        
        high_risk_states = ["blocked", "pending_approval", "on_hold"]
        medium_risk_states = ["in_review", "pending_action"]
        
        if workflow_state.lower() in high_risk_states:
            return "high"
        elif workflow_state.lower() in medium_risk_states:
            return "medium"
        else:
            return "low"
    
    def _calculate_velocity(self, event_history: list[dict]) -> dict[str, Any]:
        """Calculate workflow velocity from event history."""
        if len(event_history) < 2:
            return {"status": "insufficient_data", "events_per_hour": 0}
        
        # Get time span
        timestamps = []
        for event in event_history:
            if "timestamp" in event:
                try:
                    ts = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
                    timestamps.append(ts)
                except:
                    pass
        
        if len(timestamps) < 2:
            return {"status": "insufficient_data", "events_per_hour": 0}
        
        timestamps.sort()
        time_span = (timestamps[-1] - timestamps[0]).total_seconds() / 3600  # hours
        
        if time_span == 0:
            return {"status": "instant", "events_per_hour": len(timestamps)}
        
        events_per_hour = len(timestamps) / time_span
        
        # Classify velocity
        if events_per_hour < 0.5:
            status = "slow"
        elif events_per_hour < 2:
            status = "normal"
        else:
            status = "fast"
        
        return {
            "status": status,
            "events_per_hour": round(events_per_hour, 2),
            "event_count": len(timestamps),
            "time_span_hours": round(time_span, 2),
        }
    
    def _analyze_historical(self, similar_workflows: list[dict]) -> dict[str, Any]:
        """Analyze historical similar workflows."""
        if not similar_workflows:
            return {"available": False}
        
        total = len(similar_workflows)
        breached = sum(1 for w in similar_workflows if w.get("breached", False))
        
        breach_rate = breached / total if total > 0 else 0
        
        return {
            "available": True,
            "sample_size": total,
            "breach_rate": round(breach_rate, 2),
            "suggests_risk": breach_rate > 0.3,
        }
    
    def _calculate_risk_score(self, analysis: dict[str, Any]) -> float:
        """Calculate overall risk score (0.0 to 1.0)."""
        scores = []
        
        # Time risk
        time_risk = analysis.get("time_risk", "unknown")
        time_scores = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.2, "unknown": 0.5}
        scores.append(time_scores.get(time_risk, 0.5))
        
        # Breach risk
        breach_risk = analysis.get("breach_risk", "low")
        breach_scores = {"critical": 1.0, "high": 0.8, "medium": 0.5, "low": 0.2}
        scores.append(breach_scores.get(breach_risk, 0.5))
        
        # State risk
        state_risk = analysis.get("state_risk", "unknown")
        state_scores = {"high": 0.8, "medium": 0.5, "low": 0.2, "unknown": 0.4}
        scores.append(state_scores.get(state_risk, 0.4))
        
        # Velocity risk
        velocity = analysis.get("velocity", {})
        if velocity.get("status") == "slow":
            scores.append(0.7)
        elif velocity.get("status") == "normal":
            scores.append(0.3)
        elif velocity.get("status") == "fast":
            scores.append(0.1)
        
        # Historical risk
        historical = analysis.get("historical_pattern", {})
        if historical.get("suggests_risk"):
            scores.append(0.6)
        elif historical.get("available"):
            scores.append(0.3)
        
        return sum(scores) / len(scores) if scores else 0.5
    
    def _determine_risk_level(
        self,
        risk_score: float,
        minutes_remaining: Optional[float],
        breach_level: str
    ) -> str:
        """Determine overall risk level."""
        # Hard rules first
        if breach_level == "hard":
            return "critical"
        if minutes_remaining is not None and minutes_remaining <= self.CRITICAL_THRESHOLD_MINUTES:
            return "critical"
        if breach_level == "soft":
            return "high"
        if minutes_remaining is not None and minutes_remaining <= self.HIGH_THRESHOLD_MINUTES:
            return "high"
        
        # Score-based
        if risk_score >= 0.8:
            return "critical"
        elif risk_score >= 0.6:
            return "high"
        elif risk_score >= 0.4:
            return "medium"
        else:
            return "low"
    
    def _build_recommendations(self, analysis: dict[str, Any], risk_level: str) -> list[str]:
        """Build actionable recommendations."""
        recommendations = []
        
        if risk_level == "critical":
            recommendations.append("Immediate escalation required - SLA breach imminent")
            recommendations.append("Assign additional resources to expedite resolution")
            recommendations.append("Notify stakeholders of potential breach")
        
        elif risk_level == "high":
            recommendations.append("Escalate to team lead for prioritization")
            recommendations.append("Consider reassigning to available team member")
            if analysis.get("velocity", {}).get("status") == "slow":
                recommendations.append("Investigate bottleneck causing slow progress")
        
        elif risk_level == "medium":
            recommendations.append("Monitor closely - approaching risk threshold")
            if analysis.get("state_risk") == "high":
                recommendations.append("Review workflow state - may be blocked")
        
        else:
            recommendations.append("Continue monitoring - no immediate action needed")
        
        return recommendations
    
    def _build_reasoning(self, analysis: dict[str, Any], risk_level: str) -> str:
        """Build detailed reasoning explanation."""
        parts = []
        
        parts.append(f"Risk assessment: {risk_level.upper()}")
        
        minutes = analysis.get("minutes_remaining")
        if minutes is not None:
            parts.append(f"Time remaining: {minutes:.0f} minutes until deadline")
        
        breach = analysis.get("current_breach_level", "none")
        if breach != "none":
            parts.append(f"Current breach status: {breach}")
        
        velocity = analysis.get("velocity", {})
        if velocity.get("status") == "slow":
            parts.append(f"Workflow velocity is slow ({velocity.get('events_per_hour', 0)} events/hour)")
        
        historical = analysis.get("historical_pattern", {})
        if historical.get("suggests_risk"):
            parts.append(f"Historical data suggests elevated risk ({historical.get('breach_rate', 0)*100:.0f}% breach rate)")
        
        risk_score = analysis.get("risk_score", 0)
        parts.append(f"Overall risk score: {risk_score:.2f}")
        
        return ". ".join(parts)


# Factory function
def create_sla_agent(agent_id: Optional[str] = None) -> SLAAgent:
    """Create an SLA agent instance."""
    return SLAAgent(agent_id=agent_id)
