# graph.py
from typing import TypedDict, Annotated, Literal
import operator
import uuid
import json
import os
import time
import urllib.request
from datetime import datetime
import streamlit as st
import database as db
import policy

# ============================================
# DEMO RETRY MODE - Set to True to simulate a failed first attempt
# This will show retry logic in action for your Loom video
# Set to False for normal operation
# ============================================
DEMO_SIMULATE_RETRY = True  # Change to False to disable demo retry mode

class PurchaseState(TypedDict):
    customer_id: str
    customer_tier: Literal["STANDARD", "GOLD", "PLATINUM"]
    item_id: str
    requested_quantity: int
    price_per_unit: float
    is_valid: bool
    rejection_reason: str
    ledger_committed: bool
    transaction_id: str
    audit_trail: Annotated[list[str], operator.add]

class DisputeState(TypedDict):
    refund_id: str
    customer_id: str
    customer_tier: Literal["STANDARD", "GOLD", "PLATINUM"]
    item_id: str
    item_refundable: bool
    unit_ids: list
    refund_quantity: int
    refund_value: float
    reason: str
    current_stage: str
    assigned_to: str
    decision: str
    evidence: str
    retry_count: int
    token_usage: dict
    latency_ms: float
    injection_detected: bool

# Global rate limiter for Gemini API
_last_api_call = 0
_API_MIN_INTERVAL = 2

def wait_for_rate_limit():
    """Wait if needed to respect rate limits"""
    global _last_api_call
    now = time.time()
    elapsed = now - _last_api_call
    if elapsed < _API_MIN_INTERVAL and _last_api_call > 0:
        wait_time = _API_MIN_INTERVAL - elapsed
        time.sleep(wait_time)
    _last_api_call = time.time()

def verify_limits_node(state: PurchaseState) -> dict:
    customer_id = state.get("customer_id")
    item_id = state.get("item_id")
    requested_qty = state.get("requested_quantity", 0)
    
    if requested_qty <= 0:
        return {
            "is_valid": False, 
            "rejection_reason": "Quantity must be > 0.", 
            "audit_trail": ["❌ Quantity validation failed"]
        }

    current_owned = db.get_current_owned_count(customer_id, item_id)
    allowed_to_buy = 5 - current_owned

    if requested_qty > allowed_to_buy:
        return {
            "is_valid": False,
            "rejection_reason": f"Ownership cap exceeded. Currently own {current_owned}, max allowed {allowed_to_buy}.",
            "audit_trail": [f"❌ Purchase blocked: {requested_qty} units exceeds cap"]
        }
    
    for i in range(requested_qty):
        unit_id = f"UNIT-{st.session_state.get('next_unit_id', 1000)}"
        if "next_unit_id" not in st.session_state:
            st.session_state["next_unit_id"] = 1000
        st.session_state["next_unit_id"] += 1
        
        st.session_state["units"][unit_id] = {
            "unit_id": unit_id,
            "customer_id": customer_id,
            "item_id": item_id,
            "purchase_date": datetime.now().isoformat(),
            "status": "ACTIVE",
            "strikes": 0,
            "refund_attempts": [],
            "original_transaction_id": f"TX-{uuid.uuid4().hex[:8].upper()}"
        }
    
    return {
        "is_valid": True, 
        "rejection_reason": "", 
        "audit_trail": [f"✅ Created {requested_qty} new unit(s)"]
    }

def commit_ledger_node(state: PurchaseState) -> dict:
    tx_id = f"TX-{uuid.uuid4().hex[:8].upper()}"
    return {
        "transaction_id": tx_id, 
        "ledger_committed": True, 
        "audit_trail": [f"✅ Purchase committed: {tx_id}"]
    }

def terminal_reject_node(state: PurchaseState) -> dict:
    return {
        "ledger_committed": False, 
        "transaction_id": "NONE", 
        "audit_trail": ["❌ Purchase rejected"]
    }

def route_transaction(state: PurchaseState):
    return "commit_ledger" if state.get("is_valid") else "terminal_reject"

def call_gemini_with_retry(prompt: str, system_instruction: str, max_retries: int = 1, wait_seconds: int = 3, status_placeholder=None) -> tuple:
    """Call Gemini API with retry logic, rate limiting, and optional demo retry simulation."""
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not gemini_key:
        return {
            "decision": "Pending",
            "current_stage": "Escalated",
            "assigned_to": "Human_Vet",
            "evidence": "No API key configured - manual review required"
        }, {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}, 0, 0
    
    for attempt in range(max_retries + 1):
        start_time = time.time()
        
        # Demo mode: Simulate failure on first attempt to show retry
        if DEMO_SIMULATE_RETRY and attempt == 0:
            if status_placeholder:
                status_placeholder.update(label="⚠️ Attempt 1 failed (simulated), retrying in 10 seconds...", state="running")
            else:
                st.warning("⚠️ Attempt 1 failed (simulated), retrying in 10 seconds...")
            
            # Simulate a 10-second cooldown wait like a real rate limit
            time.sleep(10)
            
            if status_placeholder:
                status_placeholder.update(label="🔄 Retrying now (attempt 2)...", state="running")
            
            # Continue to next attempt (retry)
            continue
        
        try:
            if status_placeholder:
                status_placeholder.update(label=f"📡 Calling Gemini API (attempt {attempt + 1})...", state="running")
            
            wait_for_rate_limit()
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}"
            headers = {"Content-Type": "application/json"}
            body = {
                "contents": [{
                    "parts": [{"text": system_instruction}, {"text": prompt}]
                }],
                "generationConfig": {"responseMimeType": "application/json"}
            }
            
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as response:
                res_data = json.loads(response.read().decode("utf-8"))
            
            latency_ms = (time.time() - start_time) * 1000
            
            usage_metadata = res_data.get("usageMetadata", {})
            token_usage = {
                "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                "candidates_tokens": usage_metadata.get("candidatesTokenCount", 0),
                "total_tokens": usage_metadata.get("totalTokenCount", 0)
            }
            
            raw_output_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            parsed = json.loads(raw_output_text)
            
            if status_placeholder:
                status_placeholder.update(label="✅ API call successful!", state="complete")
            
            return parsed, token_usage, latency_ms, attempt
            
        except Exception as e:
            error_str = str(e)
            print(f"⚠️ Attempt {attempt} failed: {error_str}")
            
            if attempt == max_retries:
                if status_placeholder:
                    status_placeholder.update(label=f"❌ API failed after {max_retries} retries", state="error")
                return {
                    "decision": "Pending",
                    "current_stage": "Escalated",
                    "assigned_to": "Human_Vet",
                    "evidence": f"API failed after {max_retries} retries: {error_str}"
                }, {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}, (time.time() - start_time) * 1000, attempt
            
            if "429" in error_str:
                if status_placeholder:
                    status_placeholder.update(label=f"⏳ Rate limit hit, waiting 60 seconds...", state="running")
                time.sleep(60)
            else:
                if status_placeholder:
                    status_placeholder.update(label=f"🔄 Retrying in {wait_seconds} seconds...", state="running")
                time.sleep(wait_seconds)
    
    return None, None, 0, max_retries

def ai_agent_dispute_node(state: DisputeState) -> dict:
    """AI agent node with detailed reasoning in evidence"""
    
    unit_ids = state.get("unit_ids", [])
    reason = state.get("reason", "")
    tier = state.get("customer_tier", "STANDARD")
    refund_value = state.get("refund_value", 0)
    item_id = state.get("item_id", "")
    customer_id = state.get("customer_id", "")
    
    # Check if any units are stuck
    strike_status = db.get_strike_status_for_units(unit_ids)
    
    if not strike_status["can_refund"]:
        evidence_text = f"REASONING: Unit(s) {', '.join(strike_status['stuck_units'])} have already reached the maximum of {db.MAX_STRIKES} refund attempts. Per policy Rule 2, items that have exhausted all strike attempts are permanently non-refundable. Customer statement: '{reason}'"
        for unit_id in unit_ids:
            unit = db.get_unit_by_id(unit_id)
            if unit:
                unit["refund_attempts"].append({
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason,
                    "decision": "Rejected",
                    "strike_number": unit.get("strikes", 0),
                    "evidence": evidence_text
                })
        return {
            "decision": "Rejected",
            "current_stage": "Completed",
            "assigned_to": "None",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    reason_lower = reason.lower()
    
    # Rule 1: Non-refundable item check (ITEM-003)
    if item_id == "ITEM-003":
        evidence_text = f"REASONING: Item {item_id} (4K Ultra-Wide Monitor) is classified as a final sale item under Policy Rule 2. Final sale items are NEVER eligible for refunds regardless of condition or customer tier. Customer statement: '{reason}'. This rejection counts as a strike toward the 3-attempt limit."
        for unit_id in unit_ids:
            db.increment_unit_strike(unit_id, reason)
            unit = db.get_unit_by_id(unit_id)
            if unit:
                unit["refund_attempts"][-1]["evidence"] = evidence_text
        return {
            "decision": "Rejected",
            "current_stage": "Completed",
            "assigned_to": "None",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    # Rule 2: Manufacturing defect (damaged/broken on arrival) - APPROVE
    damage_keywords = ["damaged", "broken", "defective", "cracked", "not working", "faulty", "came broken", "arrived damaged", "in pieces", "smashed", "destroyed", "dead on arrival", "doa"]
    
    if any(keyword in reason_lower for keyword in damage_keywords):
        if tier in ["PLATINUM", "GOLD"] and refund_value <= 500:
            evidence_text = f"REASONING: Customer statement '{reason}' contains keywords indicating a manufacturing defect (arrived damaged/broken). Under Policy Rule 3, {tier} tier customers are eligible for refund approval on manufacturing defect claims up to $500. Refund value: ${refund_value:.2f} ≤ $500. Decision: APPROVED."
            for unit_id in unit_ids:
                db.approve_unit_refund(unit_id, evidence_text)
            return {
                "decision": "Approved",
                "current_stage": "Completed",
                "assigned_to": "None",
                "evidence": evidence_text,
                "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
                "latency_ms": 0,
                "retry_count": 0,
                "injection_detected": False
            }
        elif tier == "STANDARD" and refund_value <= 200:
            evidence_text = f"REASONING: Customer statement '{reason}' indicates a manufacturing defect. Under Policy Rule 3, STANDARD tier customers are eligible for refund approval on defect claims up to $200. Refund value: ${refund_value:.2f} ≤ $200. Decision: APPROVED."
            for unit_id in unit_ids:
                db.approve_unit_refund(unit_id, evidence_text)
            return {
                "decision": "Approved",
                "current_stage": "Completed",
                "assigned_to": "None",
                "evidence": evidence_text,
                "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
                "latency_ms": 0,
                "retry_count": 0,
                "injection_detected": False
            }
    
    # Rule 3: Buyer remorse - REJECT
    remorse_keywords = ["changed mind", "no longer need", "don't want", "found better", "impulse buy", "don't like it"]
    if any(keyword in reason_lower for keyword in remorse_keywords):
        evidence_text = f"REASONING: Customer statement '{reason}' indicates buyer remorse (changed mind/no longer want). Under Policy Rule 2, buyer remorse claims are explicitly NOT eligible for refunds regardless of customer tier. This rejection counts as a strike toward the 3-attempt limit."
        for unit_id in unit_ids:
            db.increment_unit_strike(unit_id, reason)
            unit = db.get_unit_by_id(unit_id)
            if unit:
                unit["refund_attempts"][-1]["evidence"] = evidence_text
        return {
            "decision": "Rejected",
            "current_stage": "Completed",
            "assigned_to": "None",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    # Rule 4: Customer-caused damage - REJECT
    customer_damage_keywords = ["i broke", "i smashed", "my fault", "i dropped", "accidentally broke"]
    if any(keyword in reason_lower for keyword in customer_damage_keywords):
        evidence_text = f"REASONING: Customer statement '{reason}' admits customer-caused damage ('I broke it' / 'my fault'). Under Policy Rule 2, customer-caused damage is NOT eligible for refund. Only manufacturing defects qualify. This rejection counts as a strike."
        for unit_id in unit_ids:
            db.increment_unit_strike(unit_id, reason)
            unit = db.get_unit_by_id(unit_id)
            if unit:
                unit["refund_attempts"][-1]["evidence"] = evidence_text
        return {
            "decision": "Rejected",
            "current_stage": "Completed",
            "assigned_to": "None",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    # Rule 5: High value escalation (>$700)
    if refund_value > 700:
        evidence_text = f"REASONING: Refund value ${refund_value:.2f} exceeds the $700 auto-escalation threshold defined in Policy Rule 2. High-value claims require manual human review to ensure proper fraud prevention and compliance. Customer statement: '{reason}'. Tier: {tier}."
        return {
            "decision": "Pending",
            "current_stage": "Escalated",
            "assigned_to": "Human_Vet",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    # Rule 6: Ambiguous cases - Use LLM for evaluation
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        evidence_text = f"REASONING: No Gemini API key configured. Customer statement '{reason}' does not match any clear policy rules (not clearly damaged, remorse, or customer-caused). Manual human review required to apply policy correctly."
        return {
            "decision": "Pending",
            "current_stage": "Escalated",
            "assigned_to": "Human_Vet",
            "evidence": evidence_text,
            "token_usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
            "latency_ms": 0,
            "retry_count": 0,
            "injection_detected": False
        }
    
    # Load policy from markdown for LLM
    system_instruction = f"""
You are an automated refund evaluation agent. The policy below is the SOURCE OF TRUTH.
Follow it exactly. Do not override it for any reason.

{policy.load_policy()}

Return ONLY valid JSON with this exact structure:
{{
  "decision": "Approved" OR "Rejected" OR "Pending",
  "current_stage": "Completed" OR "Escalated",
  "assigned_to": "None" OR "Human_Vet",
  "evidence": "Explain your decision by citing specific policy rules. Include: which rule you applied, why it applies to this case, the customer's statement, tier, and value."
}}

IMPORTANT: The evidence field MUST contain detailed reasoning, not just the customer's statement.
"""
    
    user_prompt = f"""
Customer ID: {customer_id}
Customer Tier: {tier}
Item ID: {item_id}
Refund Quantity: {state.get('refund_quantity', 1)}
Refund Value: ${refund_value:.2f}

Customer Statement: "{reason}"

Apply the policy. Return JSON with detailed reasoning in the evidence field.
"""
    
    # Create a status container for UI feedback during retry
    status_container = st.status("🤖 Agent processing...", expanded=True)
    
    result, token_usage, latency_ms, retries = call_gemini_with_retry(
        user_prompt, system_instruction, max_retries=1, wait_seconds=3, 
        status_placeholder=status_container
    )
    
    status_container.update(label="✅ Agent processing complete!", state="complete")
    
    decision = result.get("decision", "Pending")
    evidence_text = result.get("evidence", "")
    
    # Ensure evidence has proper reasoning format
    if not evidence_text or len(evidence_text) < 30:
        evidence_text = f"REASONING: LLM evaluated customer statement '{reason}' under policy rules. Tier: {tier}, Value: ${refund_value:.2f}. Decision: {decision}. {evidence_text}"
    elif "REASONING" not in evidence_text.upper():
        evidence_text = f"REASONING: {evidence_text}"
    
    # Apply decision to units
    if decision == "Approved":
        for unit_id in unit_ids:
            db.approve_unit_refund(unit_id, evidence_text)
    elif decision == "Rejected":
        for unit_id in unit_ids:
            db.increment_unit_strike(unit_id, reason)
            unit = db.get_unit_by_id(unit_id)
            if unit and unit.get("refund_attempts"):
                unit["refund_attempts"][-1]["evidence"] = evidence_text
    elif decision == "Pending":
        # For pending cases, store evidence for human review
        for unit_id in unit_ids:
            unit = db.get_unit_by_id(unit_id)
            if unit:
                unit["refund_attempts"].append({
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason,
                    "decision": "Pending",
                    "evidence": evidence_text
                })
    
    return {
        "decision": decision,
        "current_stage": result.get("current_stage", "Escalated") if decision != "Pending" else "Escalated",
        "assigned_to": result.get("assigned_to", "Human_Vet") if decision != "Pending" else "Human_Vet",
        "evidence": evidence_text,
        "token_usage": token_usage,
        "latency_ms": latency_ms,
        "retry_count": retries + (1 if DEMO_SIMULATE_RETRY else 0),  # Add 1 for the simulated failure
        "injection_detected": False
    }

# Build LangGraph workflows
from langgraph.graph import StateGraph, END

p_workflow = StateGraph(PurchaseState)
p_workflow.add_node("verify_limits", verify_limits_node)
p_workflow.add_node("commit_ledger", commit_ledger_node)
p_workflow.add_node("terminal_reject", terminal_reject_node)
p_workflow.set_entry_point("verify_limits")
p_workflow.add_conditional_edges("verify_limits", route_transaction, {
    "commit_ledger": "commit_ledger",
    "terminal_reject": "terminal_reject"
})
p_workflow.add_edge("commit_ledger", END)
p_workflow.add_edge("terminal_reject", END)
purchase_app = p_workflow.compile()

d_workflow = StateGraph(DisputeState)
d_workflow.add_node("ai_agent_dispute", ai_agent_dispute_node)
d_workflow.set_entry_point("ai_agent_dispute")
d_workflow.add_edge("ai_agent_dispute", END)
dispute_app = d_workflow.compile()