# main.py
from graph import purchase_app, dispute_app
import database as db
from datetime import datetime

def execute_purchase(customer_id: str, tier: str, item_id: str, qty: int, price: float) -> dict:
    """Execute a purchase through the LangGraph workflow"""
    initial_state = {
        "customer_id": customer_id,
        "customer_tier": tier,
        "item_id": item_id,
        "requested_quantity": qty,
        "price_per_unit": price,
        "is_valid": False,
        "rejection_reason": "",
        "ledger_committed": False,
        "transaction_id": "",
        "audit_trail": []
    }
    return purchase_app.invoke(initial_state)

def execute_dispute_evaluation(refund_record: dict, ledger_context: dict) -> dict:
    """Execute a dispute evaluation through the LangGraph workflow"""
    if not refund_record or not ledger_context:
        return {"error": "Missing required context for evaluation"}
    
    initial_state = {
        "refund_id": refund_record["refund_id"],
        "customer_id": ledger_context.get("customer_id", "UNKNOWN"),
        "customer_tier": ledger_context.get("customer_tier", "STANDARD"),
        "item_id": ledger_context.get("item_id", "UNKNOWN"),
        "item_refundable": db.CATALOG.get(ledger_context.get("item_id", ""), {}).get("refundable", True),
        "unit_ids": refund_record.get("unit_ids", []),
        "refund_quantity": refund_record.get("refund_quantity", 1),
        "refund_value": ledger_context.get("total_cost", refund_record.get("refund_value", 0.0)),
        "reason": refund_record["reason"],
        "current_stage": refund_record.get("current_stage", "Pending"),
        "assigned_to": refund_record.get("assigned_to", "AI_Agent"),
        "decision": refund_record.get("decision", "Pending"),
        "evidence": refund_record.get("evidence", ""),
        "retry_count": 0,
        "token_usage": {},
        "latency_ms": 0,
        "injection_detected": False
    }
    
    result = dispute_app.invoke(initial_state)
    
    # Update the refund record with results
    refund_record.update({
        "decision": result.get("decision"),
        "evidence": result.get("evidence"),
        "current_stage": result.get("current_stage"),
        "assigned_to": result.get("assigned_to"),
        "token_usage": result.get("token_usage", {}),
        "latency_ms": result.get("latency_ms", 0),
        "retry_count": result.get("retry_count", 0)
    })
    
    return result

