"""
Integrity Engine - Hash chain and tamper detection
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import hashlib
import json

from app.core.security import generate_hash, chain_hash


class IntegrityEngine:
    """
    Cryptographic integrity verification engine.
    Ensures event ledger cannot be tampered with.
    """
    
    GENESIS_HASH = "0" * 64
    
    def compute_event_hash(
        self,
        event_data: Dict[str, Any],
        previous_hash: str
    ) -> str:
        """Compute hash for an event, chained to previous"""
        # Serialize event data deterministically
        canonical = json.dumps(event_data, sort_keys=True, default=str)
        return chain_hash(previous_hash, canonical)
    
    def verify_chain(
        self,
        events: List[Dict[str, Any]]
    ) -> tuple[bool, Optional[int], Optional[str]]:
        """
        Verify integrity of entire event chain.
        
        Returns:
            (is_valid, broken_at_index, error_message)
        """
        if not events:
            return True, None, None
        
        for i, event in enumerate(events):
            if i == 0:
                expected_prev = self.GENESIS_HASH
            else:
                expected_prev = events[i - 1]["hash"]
            
            # Verify previous hash reference
            if event.get("previous_hash") != expected_prev:
                return False, i, f"Previous hash mismatch at event {i}"
            
            # Verify event hash
            event_data = event.get("data", {})
            expected_hash = self.compute_event_hash(event_data, expected_prev)
            
            if event.get("hash") != expected_hash:
                return False, i, f"Event hash mismatch at event {i} - possible tampering"
        
        return True, None, None
    
    def detect_gaps(
        self,
        events: List[Dict[str, Any]]
    ) -> List[int]:
        """Detect version gaps in event sequence"""
        gaps = []
        
        for i, event in enumerate(events):
            expected_version = i + 1
            actual_version = event.get("version", 0)
            
            if actual_version != expected_version:
                gaps.append(i)
        
        return gaps
    
    def generate_integrity_report(
        self,
        events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate comprehensive integrity report"""
        is_valid, broken_at, error = self.verify_chain(events)
        gaps = self.detect_gaps(events)
        
        return {
            "valid": is_valid,
            "event_count": len(events),
            "chain_verified": is_valid,
            "broken_at_index": broken_at,
            "error_message": error,
            "version_gaps": gaps,
            "has_gaps": len(gaps) > 0,
            "first_event_hash": events[0]["hash"] if events else None,
            "last_event_hash": events[-1]["hash"] if events else None,
            "verified_at": datetime.utcnow().isoformat()
        }


# Singleton instance
integrity_engine = IntegrityEngine()
