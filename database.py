# database.py
import streamlit as st
import uuid
from datetime import datetime
import time

MOCK_CLIENTS = {
    "CUST-001": {"name": "Alex Mercer", "tier": "PLATINUM", "email": "alex@example.com"},
    "CUST-002": {"name": "Devon Vance", "tier": "GOLD", "email": "devon@example.com"},
    "CUST-003": {"name": "Jordan Hayes", "tier": "STANDARD", "email": "jordan@example.com"},
    "CUST-004": {"name": "Elena Rodriguez", "tier": "PLATINUM", "email": "elena@example.com"},
    "CUST-005": {"name": "Marcus Chen", "tier": "GOLD", "email": "marcus@example.com"},
    "CUST-006": {"name": "Sarah Jenkins", "tier": "STANDARD", "email": "sarah@example.com"},
    "CUST-007": {"name": "David Park", "tier": "GOLD", "email": "david@example.com"},
    "CUST-008": {"name": "Aisha Khan", "tier": "PLATINUM", "email": "aisha@example.com"},
    "CUST-009": {"name": "Robert Miller", "tier": "STANDARD", "email": "robert@example.com"},
    "CUST-010": {"name": "Lisa Wong", "tier": "GOLD", "email": "lisa@example.com"},
    "CUST-011": {"name": "James Wilson", "tier": "STANDARD", "email": "james@example.com"},
    "CUST-012": {"name": "Maria Garcia", "tier": "PLATINUM", "email": "maria@example.com"},
    "CUST-013": {"name": "Kevin White", "tier": "GOLD", "email": "kevin@example.com"},
    "CUST-014": {"name": "Nina Patel", "tier": "STANDARD", "email": "nina@example.com"},
    "CUST-015": {"name": "Tom Baker", "tier": "GOLD", "email": "tom@example.com"}
}

CATALOG = {
    "ITEM-001": {"name": "Developer Mechanical Keyboard", "price": 149.99, "refundable": True},
    "ITEM-002": {"name": "High-Density Ergonomic Chair", "price": 499.99, "refundable": True},
    "ITEM-003": {"name": "4K Ultra-Wide Monitor", "price": 899.99, "refundable": False}
}

MAX_STRIKES = 3
MAX_TRACE_HISTORY = 20
COOLDOWN_SECONDS = 10

def initialize_demo_state():
    """Initialize all session state data structures with per-unit tracking"""
    
    if "units" not in st.session_state:
        st.session_state["units"] = {}
        st.session_state["next_unit_id"] = 1000
        
        # Seed purchase data as individual units
        seed_data = [
            ("CUST-001", "ITEM-001", "2024-01-15"),
            ("CUST-001", "ITEM-001", "2024-01-15"),
            ("CUST-004", "ITEM-002", "2024-01-20"),
            ("CUST-008", "ITEM-003", "2024-02-01"),
            ("CUST-002", "ITEM-003", "2024-02-05"),
            ("CUST-005", "ITEM-001", "2024-02-10"),
            ("CUST-007", "ITEM-002", "2024-02-15"),
            ("CUST-007", "ITEM-002", "2024-02-15"),
            ("CUST-003", "ITEM-002", "2024-02-20"),
            ("CUST-006", "ITEM-001", "2024-02-25"),
        ]
        
        for cust_id, item_id, date in seed_data:
            unit_id = f"UNIT-{st.session_state['next_unit_id']}"
            st.session_state["next_unit_id"] += 1
            
            st.session_state["units"][unit_id] = {
                "unit_id": unit_id,
                "customer_id": cust_id,
                "item_id": item_id,
                "purchase_date": date,
                "status": "ACTIVE",
                "strikes": 0,
                "refund_attempts": [],
                "original_transaction_id": f"TX-{uuid.uuid4().hex[:8].upper()}"
            }
        
        # Seed a refund trace for demo (CUST-006's keyboard was refunded)
        for unit_id, unit in st.session_state["units"].items():
            if unit["customer_id"] == "CUST-006" and unit["item_id"] == "ITEM-001":
                unit["status"] = "REFUNDED"
                unit["refund_attempts"].append({
                    "timestamp": "2024-02-28T10:30:00",
                    "reason": "Item arrived with damaged packaging",
                    "decision": "Approved",
                    "evidence": "Auto-approved via policy - damage claim under $500"
                })
                break
    
    if "human_queue" not in st.session_state:
        st.session_state["human_queue"] = []
    
    if "audit_trail" not in st.session_state:
        st.session_state["audit_trail"] = []
    
    if "compact_store" not in st.session_state:
        st.session_state["compact_store"] = {}
    
    if "processing_units" not in st.session_state:
        st.session_state["processing_units"] = []
    
    if "cooldown" not in st.session_state:
        st.session_state["cooldown"] = {}

def get_cooldown_remaining(customer_id: str) -> int:
    """Return seconds remaining until customer can make another agent request."""
    if "cooldown" not in st.session_state:
        st.session_state["cooldown"] = {}
    
    last_call = st.session_state["cooldown"].get(customer_id, 0)
    elapsed = time.time() - last_call
    remaining = max(0, COOLDOWN_SECONDS - elapsed)
    return int(remaining)

def set_cooldown(customer_id: str):
    """Record the time of the last agent call for this customer."""
    if "cooldown" not in st.session_state:
        st.session_state["cooldown"] = {}
    st.session_state["cooldown"][customer_id] = time.time()

def get_ownership_metrics(customer_id: str, item_id: str) -> tuple[int, int]:
    """Get purchased and refunded counts (for backward compatibility)"""
    initialize_demo_state()
    
    purchased = 0
    refunded = 0
    
    for unit_id, unit in st.session_state["units"].items():
        if unit["customer_id"] == customer_id and unit["item_id"] == item_id:
            purchased += 1
            if unit["status"] == "REFUNDED":
                refunded += 1
    
    return purchased, refunded

def record_successful_purchase(customer_id: str, item_id: str, qty: int):
    """Record a purchase (now handled by graph.py, kept for compatibility)"""
    initialize_demo_state()
    pass

def get_client_transactions(customer_id: str) -> list:
    """Get all transactions for a customer"""
    initialize_demo_state()
    
    units_by_item = {}
    for unit_id, unit in st.session_state["units"].items():
        if unit["customer_id"] == customer_id:
            item_id = unit["item_id"]
            if item_id not in units_by_item:
                units_by_item[item_id] = []
            units_by_item[item_id].append(unit)
    
    virtual_txs = []
    for item_id, units in units_by_item.items():
        item_info = CATALOG[item_id]
        owned_units = [u for u in units if u['status'] in ['ACTIVE', 'STUCK']]
        current_owned = len(owned_units)
        
        traces = []
        for unit in units:
            for attempt in unit.get("refund_attempts", []):
                traces.append({
                    "refund_id": f"REF-{unit['unit_id']}",
                    "decision": attempt.get("decision", "Unknown"),
                    "evidence": attempt.get("evidence", attempt.get("reason", "")),
                    "timestamp": attempt.get("timestamp", ""),
                    "unit_id": unit["unit_id"]
                })
        
        virtual_txs.append({
            "tx_id": f"TX-VIRT-{item_id}",
            "item_id": item_id,
            "product_name": item_info["name"],
            "quantity": current_owned,
            "price": item_info["price"],
            "total_value": item_info["price"] * current_owned,
            "refundable": item_info["refundable"],
            "traces": traces[-5:],
            "units": units
        })
    
    return [tx for tx in virtual_txs if tx["quantity"] > 0 or tx["traces"]]

def get_customer_units(customer_id: str, item_id: str = None) -> list:
    """Get all units for a customer, optionally filtered by item"""
    initialize_demo_state()
    
    units = []
    for unit_id, unit in st.session_state["units"].items():
        if unit["customer_id"] == customer_id:
            if item_id is None or unit["item_id"] == item_id:
                units.append(unit)
    return units

def get_refundable_units(customer_id: str, item_id: str = None) -> list:
    """Get only refundable units (ACTIVE and strikes < MAX_STRIKES)"""
    units = get_customer_units(customer_id, item_id)
    return [u for u in units if u['status'] == 'ACTIVE' and u['strikes'] < MAX_STRIKES]

def get_stuck_units(customer_id: str, item_id: str = None) -> list:
    """Get STUCK units (max strikes reached)"""
    units = get_customer_units(customer_id, item_id)
    return [u for u in units if u['status'] == 'STUCK' or u.get('strikes', 0) >= MAX_STRIKES]

def get_all_owned_units(customer_id: str, item_id: str = None) -> list:
    """Get all units the customer owns (ACTIVE + STUCK)"""
    units = get_customer_units(customer_id, item_id)
    return [u for u in units if u['status'] in ['ACTIVE', 'STUCK']]

def get_current_owned_count(customer_id: str, item_id: str) -> int:
    """Get count of units owned (ACTIVE + STUCK)"""
    return len(get_all_owned_units(customer_id, item_id))

def get_unit_by_id(unit_id: str) -> dict:
    """Get a specific unit by its ID"""
    initialize_demo_state()
    return st.session_state["units"].get(unit_id)

def select_units_for_refund(customer_id: str, item_id: str, requested_qty: int) -> list:
    """Select refundable units to refund (oldest first)"""
    refundable_units = get_refundable_units(customer_id, item_id)
    refundable_units.sort(key=lambda x: x["purchase_date"])
    selected_units = refundable_units[:requested_qty]
    return [u["unit_id"] for u in selected_units]

def increment_unit_strike(unit_id: str, reason: str) -> dict:
    """Increment strike count for a specific unit."""
    initialize_demo_state()
    
    unit = st.session_state["units"].get(unit_id)
    if not unit:
        return {"error": "Unit not found"}
    
    unit["strikes"] += 1
    unit["refund_attempts"].append({
        "timestamp": datetime.now().isoformat(),
        "reason": reason,
        "decision": "Rejected",
        "strike_number": unit["strikes"]
    })
    
    if unit["strikes"] >= MAX_STRIKES and unit["status"] == "ACTIVE":
        unit["status"] = "STUCK"
    
    return unit

def approve_unit_refund(unit_id: str, evidence: str) -> dict:
    """Mark a unit as REFUNDED."""
    initialize_demo_state()
    
    unit = st.session_state["units"].get(unit_id)
    if not unit:
        return {"error": "Unit not found"}
    
    unit["status"] = "REFUNDED"
    unit["refund_attempts"].append({
        "timestamp": datetime.now().isoformat(),
        "reason": unit.get("last_attempt_reason", "Unknown"),
        "decision": "Approved",
        "evidence": evidence
    })
    
    return unit

def create_refund_request(customer_id: str, item_id: str, reason: str, unit_ids: list, refund_value: float) -> dict:
    """Create a new refund request for specific units"""
    initialize_demo_state()
    
    refund_id = f"REF-{len(st.session_state['audit_trail']) + len(st.session_state['human_queue']) + 1000}"
    
    for unit_id in unit_ids:
        unit = st.session_state["units"].get(unit_id)
        if unit:
            unit["last_attempt_reason"] = reason
    
    return {
        "refund_id": refund_id,
        "customer_id": customer_id,
        "item_id": item_id,
        "unit_ids": unit_ids,
        "refund_quantity": len(unit_ids),
        "refund_value": refund_value,
        "reason": reason,
        "created_at": datetime.now().isoformat(),
        "current_stage": "Pending",
        "assigned_to": "AI_Agent",
        "decision": "Pending",
        "evidence": "Awaiting evaluation",
        "retry_count": 0,
        "token_usage": None,
        "latency_ms": None
    }

def push_to_human_queue(request: dict):
    """Add a request to the human review queue"""
    initialize_demo_state()
    request["assigned_to"] = "Human_Vet"
    request["current_stage"] = "Escalated"
    st.session_state["human_queue"].append(request)

def is_unit_pending_refund(unit_id: str) -> bool:
    """Check if a unit already has a pending refund request"""
    initialize_demo_state()
    
    for req in st.session_state.get("ai_temp_holder", []):
        if unit_id in req.get("unit_ids", []):
            return True
    
    for req in st.session_state.get("human_queue", []):
        if unit_id in req.get("unit_ids", []):
            return True
    
    return unit_id in st.session_state.get("processing_units", [])

def lock_unit_for_refund(unit_id: str) -> bool:
    """Lock a unit to prevent concurrent refund requests"""
    initialize_demo_state()
    
    if "processing_units" not in st.session_state:
        st.session_state["processing_units"] = []
    
    if unit_id in st.session_state["processing_units"]:
        return False
    
    st.session_state["processing_units"].append(unit_id)
    return True

def unlock_unit_for_refund(unit_id: str):
    """Unlock a unit after refund request is complete"""
    initialize_demo_state()
    
    if "processing_units" not in st.session_state:
        st.session_state["processing_units"] = []
    
    if unit_id in st.session_state["processing_units"]:
        st.session_state["processing_units"].remove(unit_id)

def unlock_units_for_refund(unit_ids: list):
    """Unlock multiple units after refund request is complete"""
    for unit_id in unit_ids:
        unlock_unit_for_refund(unit_id)

def get_strike_status_for_units(unit_ids: list) -> dict:
    """Get strike status for a list of units"""
    initialize_demo_state()
    
    results = {
        "can_refund": True,
        "stuck_units": [],
        "active_units": [],
        "max_strikes": MAX_STRIKES
    }
    
    for unit_id in unit_ids:
        unit = st.session_state["units"].get(unit_id)
        if unit:
            if unit["status"] == "STUCK" or unit.get("strikes", 0) >= MAX_STRIKES:
                results["can_refund"] = False
                results["stuck_units"].append(unit_id)
            elif unit["status"] == "ACTIVE":
                results["active_units"].append(unit_id)
    
    return results