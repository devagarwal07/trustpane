"""
SLA-as-Code Engine - Design Document

This module defines the core SLA engine that enforces service level agreements
as executable code, not just configuration.

Key Concepts:
=============

1. SLA DEFINITION (Template)
   - Defines the "contract" for response/resolution times
   - Soft limit: Warning threshold (e.g., 4 hours)
   - Hard limit: Breach threshold (e.g., 8 hours)
   - Business hours: Whether to count only work hours
   - Excluded states: States that pause the SLA clock

2. SLA INSTANCE (Runtime)
   - Created when a workflow starts
   - Tracks time elapsed against deadlines
   - Handles pausing/resuming when workflow state changes
   - Emits breach events when limits exceeded

3. BUSINESS HOURS
   - Configurable per organization
   - Supports multiple time zones
   - Excludes weekends and holidays
   - Adjusts deadlines accordingly

Time Calculation Model:
=======================

    Workflow Created (t=0)
           │
           ▼
    ┌──────────────────────────────────────────────────┐
    │  SLA CLOCK RUNNING                               │
    │                                                  │
    │  elapsed = (now - start) - paused_duration       │
    │                                                  │
    │  If business_hours_only:                         │
    │    elapsed = business_hours_between(start, now)  │
    └──────────────────────────────────────────────────┘
           │
           │ workflow.pause() or enter excluded_state
           ▼
    ┌──────────────────────────────────────────────────┐
    │  SLA CLOCK PAUSED                                │
    │                                                  │
    │  paused_at = now                                 │
    │  elapsed frozen until resume                     │
    └──────────────────────────────────────────────────┘
           │
           │ workflow.resume() or exit excluded_state
           ▼
    ┌──────────────────────────────────────────────────┐
    │  SLA CLOCK RESUMED                               │
    │                                                  │
    │  paused_duration += (now - paused_at)            │
    │  continue counting                               │
    └──────────────────────────────────────────────────┘


Breach Detection:
=================

    elapsed = calculate_elapsed()
    
    if elapsed >= hard_limit:
        emit SLA_HARD_BREACH event
        status = "hard_breach"
        
    elif elapsed >= soft_limit:
        emit SLA_SOFT_BREACH event  
        status = "soft_breach"
        
    elif workflow.completed:
        emit SLA_MET event
        status = "met"


Event Types:
============

    SLA_STARTED      - SLA tracking begins
    SLA_PAUSED       - Clock paused (workflow paused/excluded state)
    SLA_RESUMED      - Clock resumed
    SLA_SOFT_BREACH  - Soft limit exceeded (warning)
    SLA_HARD_BREACH  - Hard limit exceeded (violation)
    SLA_MET          - Workflow completed within SLA


Example SLA Definition:
=======================

    {
        "name": "P1 Incident Response",
        "soft_limit_minutes": 30,
        "hard_limit_minutes": 60,
        "business_hours_only": false,  # 24/7 for P1
        "excluded_states": ["paused", "waiting_for_customer"],
        "escalation_config": {
            "soft_breach": {"notify": ["team_lead"]},
            "hard_breach": {"notify": ["team_lead", "manager"], "page": true}
        }
    }
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set
from uuid import UUID, uuid4
from enum import Enum


class SLAStatus(str, Enum):
    """SLA instance status"""
    PENDING = "pending"       # Created but not started
    ACTIVE = "active"         # Clock running
    PAUSED = "paused"         # Clock paused
    SOFT_BREACH = "soft_breach"  # Soft limit exceeded
    HARD_BREACH = "hard_breach"  # Hard limit exceeded
    MET = "met"               # Completed within SLA
    CANCELLED = "cancelled"   # Workflow cancelled


class SLAPriority(str, Enum):
    """SLA priority levels"""
    P1_CRITICAL = "p1"
    P2_HIGH = "p2"
    P3_MEDIUM = "p3"
    P4_LOW = "p4"


@dataclass
class BusinessHoursConfig:
    """Business hours configuration"""
    timezone: str = "UTC"
    start_hour: int = 9      # 9 AM
    end_hour: int = 17       # 5 PM
    work_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])  # Mon-Fri
    holidays: List[str] = field(default_factory=list)  # ISO date strings
    
    def is_business_hour(self, dt: datetime) -> bool:
        """Check if datetime falls within business hours"""
        # Check if it's a work day
        if dt.weekday() not in self.work_days:
            return False
        
        # Check if it's a holiday
        date_str = dt.strftime("%Y-%m-%d")
        if date_str in self.holidays:
            return False
        
        # Check if within hours
        return self.start_hour <= dt.hour < self.end_hour


@dataclass
class EscalationConfig:
    """Escalation configuration for breaches"""
    notify_users: List[UUID] = field(default_factory=list)
    notify_roles: List[str] = field(default_factory=list)
    notify_channels: List[str] = field(default_factory=list)  # slack, email, pager
    auto_escalate: bool = False
    escalate_to: Optional[UUID] = None  # User/team to escalate to


@dataclass
class SLADefinition:
    """
    SLA Definition - The "contract" template.
    
    Defines time limits and rules for a class of workflows.
    """
    id: UUID
    org_id: UUID
    name: str
    description: Optional[str]
    
    # Time limits (in minutes)
    soft_limit_minutes: int
    hard_limit_minutes: int
    
    # Business hours
    business_hours_only: bool = False
    business_hours_config: Optional[BusinessHoursConfig] = None
    
    # States that pause the SLA clock
    excluded_states: Set[str] = field(default_factory=set)
    
    # Escalation configuration
    soft_breach_escalation: Optional[EscalationConfig] = None
    hard_breach_escalation: Optional[EscalationConfig] = None
    
    # Priority (for UI ordering)
    priority: SLAPriority = SLAPriority.P3_MEDIUM
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "name": self.name,
            "description": self.description,
            "soft_limit_minutes": self.soft_limit_minutes,
            "hard_limit_minutes": self.hard_limit_minutes,
            "soft_limit_hours": self.soft_limit_minutes / 60,
            "hard_limit_hours": self.hard_limit_minutes / 60,
            "business_hours_only": self.business_hours_only,
            "excluded_states": list(self.excluded_states),
            "priority": self.priority.value,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class SLAInstance:
    """
    SLA Instance - Runtime tracking for a specific workflow.
    
    Tracks time elapsed, handles pausing, detects breaches.
    """
    id: UUID
    org_id: UUID
    definition_id: UUID
    workflow_id: UUID
    
    # Current status
    status: SLAStatus = SLAStatus.PENDING
    
    # Timing
    started_at: Optional[datetime] = None
    paused_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Accumulated pause time
    total_paused_seconds: float = 0.0
    
    # Calculated deadlines (set when started)
    soft_deadline: Optional[datetime] = None
    hard_deadline: Optional[datetime] = None
    
    # Breach timestamps
    soft_breach_at: Optional[datetime] = None
    hard_breach_at: Optional[datetime] = None
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def elapsed_seconds(self, now: Optional[datetime] = None) -> float:
        """
        Calculate elapsed time in seconds, excluding paused time.
        
        elapsed = (now - started_at) - total_paused_seconds
        
        If currently paused, also excludes current pause duration.
        """
        if not self.started_at:
            return 0.0
        
        now = now or datetime.utcnow()
        
        # If completed, calculate to completion time
        end_time = self.completed_at or now
        
        # Total wall-clock time
        total = (end_time - self.started_at).total_seconds()
        
        # Subtract paused time
        total -= self.total_paused_seconds
        
        # If currently paused, subtract current pause duration
        if self.paused_at and not self.completed_at:
            current_pause = (now - self.paused_at).total_seconds()
            total -= current_pause
        
        return max(0.0, total)
    
    def elapsed_minutes(self, now: Optional[datetime] = None) -> float:
        """Elapsed time in minutes"""
        return self.elapsed_seconds(now) / 60
    
    def remaining_to_soft_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds remaining until soft breach"""
        if not self.soft_deadline or not self.started_at:
            return None
        
        now = now or datetime.utcnow()
        remaining = (self.soft_deadline - now).total_seconds()
        return max(0.0, remaining)
    
    def remaining_to_hard_seconds(self, now: Optional[datetime] = None) -> Optional[float]:
        """Seconds remaining until hard breach"""
        if not self.hard_deadline or not self.started_at:
            return None
        
        now = now or datetime.utcnow()
        remaining = (self.hard_deadline - now).total_seconds()
        return max(0.0, remaining)
    
    def is_breached(self) -> bool:
        """Check if SLA is breached (soft or hard)"""
        return self.status in {SLAStatus.SOFT_BREACH, SLAStatus.HARD_BREACH}
    
    def is_terminal(self) -> bool:
        """Check if SLA tracking is complete"""
        return self.status in {
            SLAStatus.MET,
            SLAStatus.HARD_BREACH,
            SLAStatus.CANCELLED
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        now = datetime.utcnow()
        
        return {
            "id": str(self.id),
            "org_id": str(self.org_id),
            "definition_id": str(self.definition_id),
            "workflow_id": str(self.workflow_id),
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "paused_at": self.paused_at.isoformat() if self.paused_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "soft_deadline": self.soft_deadline.isoformat() if self.soft_deadline else None,
            "hard_deadline": self.hard_deadline.isoformat() if self.hard_deadline else None,
            "soft_breach_at": self.soft_breach_at.isoformat() if self.soft_breach_at else None,
            "hard_breach_at": self.hard_breach_at.isoformat() if self.hard_breach_at else None,
            "elapsed_minutes": round(self.elapsed_minutes(now), 2),
            "remaining_to_soft_minutes": round(self.remaining_to_soft_seconds(now) / 60, 2) if self.remaining_to_soft_seconds(now) is not None else None,
            "remaining_to_hard_minutes": round(self.remaining_to_hard_seconds(now) / 60, 2) if self.remaining_to_hard_seconds(now) is not None else None,
            "is_breached": self.is_breached(),
            "is_terminal": self.is_terminal(),
            "total_paused_minutes": round(self.total_paused_seconds / 60, 2),
        }


# =========================================================
# DEFAULT SLA TEMPLATES
# =========================================================

DEFAULT_SLA_TEMPLATES = {
    "p1_critical": {
        "name": "P1 - Critical Incident",
        "description": "Critical production issues affecting all users",
        "soft_limit_minutes": 15,
        "hard_limit_minutes": 30,
        "business_hours_only": False,  # 24/7
        "excluded_states": {"paused"},
        "priority": SLAPriority.P1_CRITICAL,
    },
    "p2_high": {
        "name": "P2 - High Priority",
        "description": "Major issues affecting subset of users",
        "soft_limit_minutes": 60,
        "hard_limit_minutes": 120,
        "business_hours_only": False,
        "excluded_states": {"paused", "waiting_for_customer"},
        "priority": SLAPriority.P2_HIGH,
    },
    "p3_medium": {
        "name": "P3 - Medium Priority",
        "description": "Standard support requests",
        "soft_limit_minutes": 240,  # 4 hours
        "hard_limit_minutes": 480,  # 8 hours
        "business_hours_only": True,
        "excluded_states": {"paused", "waiting_for_customer"},
        "priority": SLAPriority.P3_MEDIUM,
    },
    "p4_low": {
        "name": "P4 - Low Priority",
        "description": "Non-urgent requests and enhancements",
        "soft_limit_minutes": 1440,  # 24 hours
        "hard_limit_minutes": 2880,  # 48 hours
        "business_hours_only": True,
        "excluded_states": {"paused", "waiting_for_customer"},
        "priority": SLAPriority.P4_LOW,
    },
}
