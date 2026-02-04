"""
Workflow Agent

Analyzes workflow state, transitions, and recommends next actions.
Provides intelligent routing and assignment recommendations.
"""

from typing import Any, Optional
from datetime import datetime, timedelta
from uuid import UUID

from app.agents.base import (
    BaseAgent, AgentType, AgentDecision, AgentContext,
    DecisionConfidence, DecisionType
)


class WorkflowAgent(BaseAgent):
    """
    Workflow Intelligence Agent.
    
    Responsibilities:
    - Analyze workflow state and history
    - Recommend state transitions
    - Suggest assignee changes
    - Identify bottlenecks
    - Predict completion likelihood
    
    Decision output includes:
    - Recommended transition
    - Suggested assignee
    - Bottleneck identification
    - Completion probability
    """
    
    # State transition rules
    VALID_TRANSITIONS = {
        "draft": ["submitted", "cancelled"],
        "submitted": ["in_review", "rejected", "cancelled"],
        "in_review": ["approved", "changes_requested", "rejected"],
        "changes_requested": ["submitted", "cancelled"],
        "approved": ["in_progress", "on_hold"],
        "in_progress": ["completed", "blocked", "on_hold"],
        "blocked": ["in_progress", "escalated", "cancelled"],
        "escalated": ["in_progress", "resolved"],
        "on_hold": ["in_progress", "cancelled"],
        "completed": [],
        "cancelled": [],
        "rejected": [],
        "resolved": ["completed"],
    }
    
    # Priority-based SLA multipliers
    PRIORITY_MULTIPLIERS = {
        "urgent": 0.25,
        "high": 0.5,
        "normal": 1.0,
        "low": 2.0,
    }
    
    def __init__(self, agent_id: Optional[str] = None):
        super().__init__(
            agent_type=AgentType.WORKFLOW,
            agent_id=agent_id,
            model="gpt-4o",
            temperature=0.0,
        )
    
    @property
    def system_prompt(self) -> str:
        return """You are the Workflow Agent for TrustPlane, a B2B SaaS platform.

Your role is to analyze workflow state and recommend intelligent actions.

RULES:
1. Only recommend valid state transitions
2. Consider workload balance when suggesting assignees
3. Identify bottlenecks proactively
4. Factor in priority when making recommendations
5. Always provide clear reasoning
6. If unsure, recommend human review

INPUTS YOU RECEIVE:
- Current workflow state
- State history (transitions)
- Assignee information
- Priority level
- Related SLA information
- Team workload data

OUTPUT (JSON):
{
    "current_state_assessment": "healthy|at_risk|blocked|stalled",
    "recommended_transition": "state_name" or null,
    "transition_reasoning": "why this transition",
    "suggested_assignee": "user_id" or null,
    "assignee_reasoning": "why this assignee",
    "bottleneck_detected": boolean,
    "bottleneck_description": string or null,
    "completion_probability": 0.0 to 1.0,
    "estimated_completion_hours": number or null,
    "priority_adjustment": "increase|decrease|maintain",
    "recommendations": ["action1", "action2"],
    "confidence": "high|medium|low",
    "reasoning": "detailed explanation"
}

VALID STATE TRANSITIONS:
- draft → submitted, cancelled
- submitted → in_review, rejected, cancelled
- in_review → approved, changes_requested, rejected
- approved → in_progress, on_hold
- in_progress → completed, blocked, on_hold
- blocked → in_progress, escalated, cancelled
- escalated → in_progress, resolved

Remember: You analyze and recommend. You do NOT execute changes."""

    async def analyze(self, context: AgentContext) -> dict[str, Any]:
        """
        Analyze workflow state and history.
        """
        analysis = {
            "timestamp": datetime.utcnow().isoformat(),
            "workflow_id": str(context.workflow_id) if context.workflow_id else None,
        }
        
        # Current state analysis
        current_state = context.workflow_state or "unknown"
        analysis["current_state"] = current_state
        analysis["valid_transitions"] = self.VALID_TRANSITIONS.get(current_state, [])
        
        # Priority analysis
        priority = context.workflow_priority or "normal"
        analysis["priority"] = priority
        analysis["priority_multiplier"] = self.PRIORITY_MULTIPLIERS.get(priority, 1.0)
        
        # Age analysis
        if context.workflow_created_at:
            age = datetime.utcnow() - context.workflow_created_at
            analysis["age_hours"] = age.total_seconds() / 3600
            analysis["age_assessment"] = self._assess_age(age, priority)
        else:
            analysis["age_hours"] = None
            analysis["age_assessment"] = "unknown"
        
        # Event history analysis
        if context.event_history:
            analysis["state_history"] = self._analyze_state_history(context.event_history)
            analysis["bottleneck"] = self._detect_bottleneck(context.event_history, current_state)
        else:
            analysis["state_history"] = {"available": False}
            analysis["bottleneck"] = {"detected": False}
        
        # SLA context
        if context.sla_time_remaining_seconds is not None:
            analysis["sla_pressure"] = self._calculate_sla_pressure(
                context.sla_time_remaining_seconds,
                context.sla_breach_level
            )
        else:
            analysis["sla_pressure"] = "unknown"
        
        # Completion estimate
        analysis["completion_estimate"] = self._estimate_completion(
            current_state,
            analysis.get("state_history", {}),
            analysis.get("sla_pressure", "unknown")
        )
        
        return analysis
    
    async def decide(self, analysis: dict[str, Any], context: AgentContext) -> AgentDecision:
        """
        Make workflow decision based on analysis.
        """
        current_state = analysis.get("current_state", "unknown")
        valid_transitions = analysis.get("valid_transitions", [])
        bottleneck = analysis.get("bottleneck", {})
        sla_pressure = analysis.get("sla_pressure", "unknown")
        completion_estimate = analysis.get("completion_estimate", {})
        
        # Determine recommended action
        recommendations = []
        suggested_transition = None
        suggested_assignee = None
        decision_type = DecisionType.RECOMMEND
        requires_human = False
        is_urgent = False
        
        # Check for bottleneck
        if bottleneck.get("detected"):
            recommendations.append(f"Bottleneck detected: {bottleneck.get('description', 'Unknown cause')}")
            decision_type = DecisionType.ALERT
            is_urgent = bottleneck.get("severity", "low") in ["high", "critical"]
            requires_human = True
        
        # Check SLA pressure
        if sla_pressure in ["critical", "high"]:
            recommendations.append("High SLA pressure - prioritize this workflow")
            is_urgent = True
            
            # Recommend escalation if blocked
            if current_state == "blocked" and "escalated" in valid_transitions:
                suggested_transition = "escalated"
                recommendations.append("Recommend escalation due to blocked state with high SLA pressure")
        
        # Recommend progression for healthy workflows
        if not bottleneck.get("detected") and sla_pressure not in ["critical", "high"]:
            suggested_transition = self._recommend_transition(current_state, valid_transitions, analysis)
            if suggested_transition:
                recommendations.append(f"Recommend transitioning to '{suggested_transition}'")
        
        # Priority adjustment
        priority_adjustment = "maintain"
        if sla_pressure == "critical" and analysis.get("priority") not in ["urgent", "high"]:
            priority_adjustment = "increase"
            recommendations.append("Consider increasing priority due to SLA pressure")
        
        # Calculate confidence
        confidence_factors = {
            "state_known": 1.0 if current_state != "unknown" else 0.3,
            "history_available": 0.9 if analysis.get("state_history", {}).get("available") else 0.6,
            "sla_known": 0.9 if sla_pressure != "unknown" else 0.7,
        }
        confidence = self._calculate_confidence(confidence_factors)
        
        # Build reasoning
        reasoning_parts = [
            f"Current state: {current_state}",
            f"SLA pressure: {sla_pressure}",
        ]
        if bottleneck.get("detected"):
            reasoning_parts.append(f"Bottleneck detected in state: {bottleneck.get('state', 'unknown')}")
        if completion_estimate.get("probability") is not None:
            reasoning_parts.append(f"Completion probability: {completion_estimate.get('probability')*100:.0f}%")
        
        reasoning = ". ".join(reasoning_parts)
        
        # Evidence
        evidence = []
        if analysis.get("age_hours"):
            evidence.append(f"Workflow age: {analysis.get('age_hours'):.1f} hours")
        if analysis.get("state_history", {}).get("transition_count"):
            evidence.append(f"State transitions: {analysis.get('state_history', {}).get('transition_count')}")
        
        return AgentDecision(
            agent_type=self.agent_type,
            agent_id=self.agent_id,
            decision_type=decision_type,
            confidence=confidence,
            reasoning=reasoning,
            evidence=evidence,
            recommendations=recommendations,
            suggested_action=suggested_transition,
            suggested_assignee=suggested_assignee,
            requires_human_review=requires_human,
            is_urgent=is_urgent,
            model_used=self.model,
        )
    
    def _assess_age(self, age: timedelta, priority: str) -> str:
        """Assess workflow age relative to priority."""
        hours = age.total_seconds() / 3600
        multiplier = self.PRIORITY_MULTIPLIERS.get(priority, 1.0)
        
        # Base thresholds (for normal priority)
        if hours > 72 * multiplier:
            return "stale"
        elif hours > 24 * multiplier:
            return "aging"
        elif hours > 8 * multiplier:
            return "active"
        else:
            return "fresh"
    
    def _analyze_state_history(self, event_history: list[dict]) -> dict[str, Any]:
        """Analyze state transition history."""
        transitions = []
        
        for event in event_history:
            if event.get("event_type") in ["workflow.transitioned", "state_changed"]:
                transitions.append({
                    "from": event.get("from_state"),
                    "to": event.get("to_state"),
                    "timestamp": event.get("timestamp"),
                })
        
        if not transitions:
            return {"available": False, "transition_count": 0}
        
        # Calculate average time between transitions
        time_between = []
        for i in range(1, len(transitions)):
            try:
                t1 = datetime.fromisoformat(transitions[i-1]["timestamp"].replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(transitions[i]["timestamp"].replace("Z", "+00:00"))
                time_between.append((t2 - t1).total_seconds() / 3600)
            except:
                pass
        
        avg_time = sum(time_between) / len(time_between) if time_between else None
        
        return {
            "available": True,
            "transition_count": len(transitions),
            "avg_hours_between_transitions": round(avg_time, 2) if avg_time else None,
            "last_transition": transitions[-1] if transitions else None,
        }
    
    def _detect_bottleneck(self, event_history: list[dict], current_state: str) -> dict[str, Any]:
        """Detect if workflow is stuck in a bottleneck."""
        # Find when we entered current state
        entered_current_state = None
        
        for event in reversed(event_history):
            if event.get("to_state") == current_state:
                try:
                    entered_current_state = datetime.fromisoformat(
                        event.get("timestamp", "").replace("Z", "+00:00")
                    )
                except:
                    pass
                break
        
        if not entered_current_state:
            return {"detected": False}
        
        # Calculate time in current state
        time_in_state = (datetime.utcnow() - entered_current_state).total_seconds() / 3600
        
        # Bottleneck states and thresholds
        bottleneck_thresholds = {
            "in_review": 24,
            "pending_approval": 12,
            "blocked": 4,
            "on_hold": 48,
        }
        
        threshold = bottleneck_thresholds.get(current_state.lower(), 72)
        
        if time_in_state > threshold:
            severity = "critical" if time_in_state > threshold * 2 else "high"
            return {
                "detected": True,
                "state": current_state,
                "hours_in_state": round(time_in_state, 1),
                "threshold_hours": threshold,
                "severity": severity,
                "description": f"Workflow has been in '{current_state}' for {time_in_state:.1f} hours (threshold: {threshold}h)",
            }
        
        return {"detected": False}
    
    def _calculate_sla_pressure(self, time_remaining_seconds: int, breach_level: Optional[str]) -> str:
        """Calculate SLA pressure level."""
        if breach_level == "hard":
            return "critical"
        if breach_level == "soft":
            return "high"
        
        hours_remaining = time_remaining_seconds / 3600
        
        if hours_remaining <= 1:
            return "critical"
        elif hours_remaining <= 4:
            return "high"
        elif hours_remaining <= 12:
            return "medium"
        else:
            return "low"
    
    def _estimate_completion(
        self,
        current_state: str,
        state_history: dict[str, Any],
        sla_pressure: str
    ) -> dict[str, Any]:
        """Estimate completion probability and time."""
        # Base completion probability by state
        state_probabilities = {
            "draft": 0.4,
            "submitted": 0.5,
            "in_review": 0.6,
            "approved": 0.8,
            "in_progress": 0.85,
            "blocked": 0.3,
            "escalated": 0.5,
            "on_hold": 0.4,
            "completed": 1.0,
            "cancelled": 0.0,
            "rejected": 0.0,
            "resolved": 0.9,
        }
        
        base_prob = state_probabilities.get(current_state.lower(), 0.5)
        
        # Adjust based on SLA pressure (high pressure = more resources)
        pressure_adjustments = {
            "critical": 0.1,
            "high": 0.05,
            "medium": 0.0,
            "low": -0.05,
        }
        
        adjusted_prob = base_prob + pressure_adjustments.get(sla_pressure, 0.0)
        adjusted_prob = max(0.0, min(1.0, adjusted_prob))
        
        # Estimate hours remaining
        avg_hours = state_history.get("avg_hours_between_transitions")
        remaining_states = self._count_remaining_states(current_state)
        
        if avg_hours and remaining_states > 0:
            estimated_hours = avg_hours * remaining_states
        else:
            estimated_hours = None
        
        return {
            "probability": round(adjusted_prob, 2),
            "estimated_hours": round(estimated_hours, 1) if estimated_hours else None,
            "remaining_states": remaining_states,
        }
    
    def _count_remaining_states(self, current_state: str) -> int:
        """Count approximate remaining states to completion."""
        state_order = ["draft", "submitted", "in_review", "approved", "in_progress", "completed"]
        
        try:
            current_index = state_order.index(current_state.lower())
            return len(state_order) - current_index - 1
        except ValueError:
            return 2  # Default estimate
    
    def _recommend_transition(
        self,
        current_state: str,
        valid_transitions: list[str],
        analysis: dict[str, Any]
    ) -> Optional[str]:
        """Recommend next state transition."""
        if not valid_transitions:
            return None
        
        # Priority order for progression
        progression_priority = [
            "completed", "resolved", "approved", "in_progress",
            "in_review", "submitted"
        ]
        
        for preferred in progression_priority:
            if preferred in valid_transitions:
                return preferred
        
        # Return first valid transition if no preferred found
        return valid_transitions[0] if valid_transitions else None


# Factory function
def create_workflow_agent(agent_id: Optional[str] = None) -> WorkflowAgent:
    """Create a workflow agent instance."""
    return WorkflowAgent(agent_id=agent_id)
