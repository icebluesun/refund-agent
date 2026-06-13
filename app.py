# app.py
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import json
import pandas as pd
import database as db
from main import execute_purchase, execute_dispute_evaluation
from datetime import datetime
import re

st.set_page_config(page_title="Loopp AI Refund Agent", layout="wide")

db.initialize_demo_state()

if "ai_temp_holder" not in st.session_state:
    st.session_state["ai_temp_holder"] = []

# Per-user chat storage - each customer has their own history and context
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = {}  # Dict: customer_id -> list of messages

if "chat_context" not in st.session_state:
    st.session_state.chat_context = {}  # Dict: customer_id -> context dict

def get_default_chat_context():
    """Return default chat context for a new user"""
    return {
        "stage": "idle",
        "intent": None,
        "selected_item_id": None,
        "selected_units": [],
        "pending_reason": None,
        "purchase_quantity": 0
    }

st.sidebar.title("🤖 Loopp Refund System")

# Customer selector for chat
st.sidebar.subheader("Chat Customer")
chat_customer_id = st.sidebar.selectbox(
    "Customer for Chat",
    options=list(db.MOCK_CLIENTS.keys()),
    format_func=lambda x: f"{x} - {db.MOCK_CLIENTS[x]['name']} ({db.MOCK_CLIENTS[x]['tier']})",
    key="chat_customer_select"
)

# Initialize chat storage for this customer if not exists
if chat_customer_id not in st.session_state.chat_messages:
    st.session_state.chat_messages[chat_customer_id] = []

if chat_customer_id not in st.session_state.chat_context:
    st.session_state.chat_context[chat_customer_id] = get_default_chat_context()

if st.sidebar.button("Clear Chat History"):
    # Only clear the selected customer's chat
    st.session_state.chat_messages[chat_customer_id] = []
    st.session_state.chat_context[chat_customer_id] = get_default_chat_context()
    st.rerun()

app_mode = st.sidebar.selectbox(
    "Navigation",
    ["💬 AI Chat Assistant", "🛍️ Customer Portal", "🤖 AI Agent Console", "⚖️ Human Review", "📊 Audit Log", "📈 Agent Analytics"]
)

CATALOG = db.CATALOG

def get_customer_inventory_summary(customer_id: str) -> str:
    """Get a summary of customer's owned items for display"""
    owned_units = db.get_all_owned_units(customer_id)
    units_by_item = {}
    for unit in owned_units:
        if unit["item_id"] not in units_by_item:
            units_by_item[unit["item_id"]] = []
        units_by_item[unit["item_id"]].append(unit)
    
    if not units_by_item:
        return "You don't have any purchases yet."
    
    summary_lines = []
    for item_id, units in units_by_item.items():
        item_info = CATALOG[item_id]
        refundable_units = [u for u in units if u['status'] == 'ACTIVE' and u['strikes'] < db.MAX_STRIKES]
        stuck_units = [u for u in units if u['status'] == 'STUCK' or u['strikes'] >= db.MAX_STRIKES]
        
        line = f"• **{item_info['name']}** (ID: {item_id}) - ${item_info['price']:.2f} each"
        line += f"\n  - {len(refundable_units)} refundable unit(s)"
        if stuck_units:
            line += f"\n  - {len(stuck_units)} stuck unit(s) (max strikes reached)"
        summary_lines.append(line)
    
    return "\n\n".join(summary_lines)

def get_available_products_summary() -> str:
    """Get a summary of available products for purchase"""
    summary_lines = []
    for item_id, item_info in CATALOG.items():
        refundable_text = "Refundable" if item_info["refundable"] else "Final Sale - Non-refundable"
        summary_lines.append(f"• **{item_info['name']}** (ID: {item_id}) - ${item_info['price']:.2f} - {refundable_text}")
    return "\n".join(summary_lines)

def get_max_purchase_allowed(customer_id: str, item_id: str) -> int:
    """Calculate maximum additional units a customer can purchase"""
    current_owned = db.get_current_owned_count(customer_id, item_id)
    max_allowed = 5
    return max(0, max_allowed - current_owned)

def extract_quantity_from_message(message: str) -> int:
    """Extract quantity from message. Returns None if no quantity found."""
    message_lower = message.lower().strip()
    
    # Check for number patterns
    quantity_match = re.search(r'(\d+)', message_lower)
    if quantity_match:
        return int(quantity_match.group(1))
    
    # Check for word patterns
    if message_lower in ["one", "1"]:
        return 1
    elif message_lower in ["two", "2"]:
        return 2
    elif message_lower in ["three", "3"]:
        return 3
    elif message_lower in ["four", "4"]:
        return 4
    elif message_lower in ["five", "5"]:
        return 5
    
    return None

def process_chat_message(user_message: str, customer_id: str) -> dict:
    """Process a chat message with buy and refund capabilities"""
    
    # Check cooldown first
    cooldown = db.get_cooldown_remaining(customer_id)
    if cooldown > 0:
        return {
            "response": f"⏳ Please wait {cooldown} seconds before sending another message.",
            "should_process": False,
            "reasoning": f"Cooldown active: {cooldown} seconds remaining."
        }
    
    message_lower = user_message.lower().strip()
    customer_tier = db.MOCK_CLIENTS[customer_id]['tier']
    
    # Get this customer's context
    context = st.session_state.chat_context.get(customer_id, get_default_chat_context())
    
    # Check for prompt injection
    injection_patterns = ["ignore previous", "override policy", "you are now", "pretend you are", "admin override", "system instruction"]
    for pattern in injection_patterns:
        if pattern in message_lower:
            context["stage"] = "idle"
            context["intent"] = None
            st.session_state.chat_context[customer_id] = context
            return {
                "response": "🔒 I cannot override the refund policy. Please state a valid request (buy or refund).",
                "should_process": False,
                "reasoning": "Prompt injection attempt detected and blocked."
            }
    
    # Greeting handling
    greetings = ["hello", "hi", "hey", "good morning", "good afternoon"]
    if any(g in message_lower for g in greetings) and len(user_message.split()) < 4 and context["stage"] == "idle":
        inventory_summary = get_customer_inventory_summary(customer_id)
        products_summary = get_available_products_summary()
        return {
            "response": f"Hello! I'm Loopp's AI shopping and refund assistant.\n\n**Your current inventory:**\n{inventory_summary}\n\n**Available products to buy:**\n{products_summary}\n\nWhat would you like to do? (e.g., 'buy keyboard', 'refund chair', or 'show my items')",
            "should_process": False,
            "reasoning": f"Greeting detected. Showing inventory and available products."
        }
    
    # Cancel command
    if message_lower in ["cancel", "nevermind", "stop"]:
        context["stage"] = "idle"
        context["intent"] = None
        context["selected_item_id"] = None
        context["selected_units"] = []
        context["pending_reason"] = None
        context["purchase_quantity"] = 0
        st.session_state.chat_context[customer_id] = context
        return {
            "response": "Action cancelled. Let me know if you need help with buying or refunding something!",
            "should_process": False,
            "reasoning": "User cancelled current action."
        }
    
    # Show items command
    if message_lower in ["show my items", "what do i own", "my items", "inventory"]:
        inventory_summary = get_customer_inventory_summary(customer_id)
        context["stage"] = "idle"
        context["intent"] = None
        st.session_state.chat_context[customer_id] = context
        return {
            "response": f"Here's your current inventory:\n\n{inventory_summary}\n\nWould you like to buy more items or request a refund?",
            "should_process": False,
            "reasoning": "User requested to see inventory."
        }
    
    # Show products command
    if message_lower in ["what can i buy", "available products", "products", "catalog"]:
        products_summary = get_available_products_summary()
        return {
            "response": f"**Available products:**\n\n{products_summary}\n\nWhich item would you like to buy? (e.g., 'buy keyboard' or 'buy 2 chairs')",
            "should_process": False,
            "reasoning": "User requested to see available products."
        }
    
    # Show refund status / why only X units
    if message_lower in ["why only 1 unit", "why only one unit", "refund status", "my refund status", "show refund status", "what's wrong with my refund", "why can't i refund", "refund breakdown"]:
        inventory_summary = get_customer_inventory_summary(customer_id)
        
        # Get detailed breakdown by item
        owned_units = db.get_all_owned_units(customer_id)
        units_by_item = {}
        for unit in owned_units:
            if unit["item_id"] not in units_by_item:
                units_by_item[unit["item_id"]] = []
            units_by_item[unit["item_id"]].append(unit)
        
        detailed_breakdown = []
        for item_id, units in units_by_item.items():
            item_info = CATALOG[item_id]
            total = len(units)
            refundable = len([u for u in units if u['status'] == 'ACTIVE' and u['strikes'] < db.MAX_STRIKES])
            stuck = len([u for u in units if u['status'] == 'STUCK' or u['strikes'] >= db.MAX_STRIKES])
            pending = 0
            for u in units:
                if db.is_unit_pending_refund(u['unit_id']):
                    pending += 1
            refunded = len([u for u in units if u['status'] == 'REFUNDED'])
            
            detailed_breakdown.append(f"**{item_info['name']}:**")
            detailed_breakdown.append(f"  • Refundable: {refundable}/{total}")
            if stuck > 0:
                detailed_breakdown.append(f"  • ❌ Stuck: {stuck} (max {db.MAX_STRIKES} strikes reached)")
            if pending > 0:
                detailed_breakdown.append(f"  • ⏳ Pending review: {pending}")
            if refunded > 0:
                detailed_breakdown.append(f"  • ✅ Already refunded: {refunded}")
            detailed_breakdown.append("")
        
        if not detailed_breakdown:
            detailed_breakdown = ["You don't have any purchases yet."]
        
        return {
            "response": f"📊 **Your Refund Status:**\n\n" + "\n".join(detailed_breakdown) + f"\n💡 Each unit allows up to {db.MAX_STRIKES} refund attempts. After {db.MAX_STRIKES} rejections, a unit becomes permanently stuck.\n\nType 'show my items' to see your full inventory.",
            "should_process": False,
            "reasoning": "User asked for refund status breakdown."
        }
    
    # Detect intent: BUY or REFUND
    buy_intent = re.search(r'\b(buy|purchase|get|order)\b', message_lower)
    refund_intent = re.search(r'\b(refund|return|money back|reimburse)\b', message_lower)
    
    # Stage 1: Idle - detect intent
    if context["stage"] == "idle":
        # Check for refund intent
        if refund_intent:
            context["intent"] = "refund"
            # Extract which item user wants to refund
            item_mapping = {
                "keyboard": "ITEM-001",
                "chair": "ITEM-002",
                "monitor": "ITEM-003",
                "screen": "ITEM-003"
            }
            
            detected_item = None
            for item_name, item_id in item_mapping.items():
                if item_name in message_lower:
                    detected_item = item_id
                    break
            
            if detected_item:
                # Check if user owns this item
                owned_units = db.get_all_owned_units(customer_id, detected_item)
                
                # ===== SAFETY CHECKS =====
                # Filter out units that are not refundable (stuck or pending)
                valid_refundable_units = []
                stuck_unit_ids = []
                pending_unit_ids = []
                
                for unit in owned_units:
                    if unit['status'] == 'ACTIVE' and unit['strikes'] < db.MAX_STRIKES:
                        # Check if unit has a pending refund
                        if db.is_unit_pending_refund(unit['unit_id']):
                            pending_unit_ids.append(unit['unit_id'])
                        else:
                            valid_refundable_units.append(unit)
                    elif unit['strikes'] >= db.MAX_STRIKES or unit['status'] == 'STUCK':
                        stuck_unit_ids.append(unit['unit_id'])
                
                if not valid_refundable_units:
                    item_info = CATALOG[detected_item]
                    
                    # Build detailed breakdown of inventory
                    total_owned = len(owned_units)
                    refunded_count = len([u for u in owned_units if u['status'] == 'REFUNDED'])
                    stuck_count = len(stuck_unit_ids)
                    pending_count = len(pending_unit_ids)
                    refundable_count = len(valid_refundable_units)
                    
                    response_parts = [f"📊 **Inventory breakdown for {item_info['name']}:**"]
                    response_parts.append(f"• Total owned: {total_owned} unit(s)")
                    response_parts.append(f"• Refundable: {refundable_count} unit(s)")
                    
                    if stuck_count > 0:
                        response_parts.append(f"• ❌ Stuck (max strikes reached): {stuck_count} unit(s) - cannot refund")
                    if pending_count > 0:
                        response_parts.append(f"• ⏳ Pending refund requests: {pending_count} unit(s) - being reviewed")
                    if refunded_count > 0:
                        response_parts.append(f"• ✅ Already refunded: {refunded_count} unit(s)")
                    
                    if stuck_count > 0:
                        response_parts.append(f"\n💡 Units become stuck after {db.MAX_STRIKES} rejected refund attempts.")
                    if pending_count > 0:
                        response_parts.append(f"\n💡 Pending requests are being processed by AI or waiting for human review.")
                    
                    if total_owned == 0:
                        response_parts = [f"You don't own any {item_info['name']} units. Would you like to buy one?"]
                    
                    st.session_state.chat_context[customer_id] = context
                    return {
                        "response": "\n".join(response_parts),
                        "should_process": False,
                        "reasoning": f"Inventory breakdown for {detected_item}: Total={total_owned}, Refundable={refundable_count}, Stuck={stuck_count}, Pending={pending_count}, Refunded={refunded_count}"
                    }
                
                context["selected_item_id"] = detected_item
                context["selected_units"] = valid_refundable_units
                
                # SMART FIX: Check if quantity is already in the message
                quantity = extract_quantity_from_message(user_message)
                
                if quantity is not None:
                    # Quantity provided in the same message!
                    max_qty = len(valid_refundable_units)
                    if quantity < 1 or quantity > max_qty:
                        return {
                            "response": f"You only have {max_qty} refundable unit(s). Please enter a number between 1 and {max_qty}.\n\nType 'refund status' to see why.",
                            "should_process": False,
                            "reasoning": f"Quantity {quantity} out of range (1-{max_qty})."
                        }
                    
                    # Select the requested number of units
                    context["selected_units"] = valid_refundable_units[:quantity]
                    context["stage"] = "awaiting_reason"
                    st.session_state.chat_context[customer_id] = context
                    
                    item_info = CATALOG[detected_item]
                    refund_value = quantity * item_info["price"]
                    
                    return {
                        "response": f"{quantity} {item_info['name']}(s) selected (${refund_value:.2f}).\n\nWhat's the reason for the refund? (e.g., 'arrived damaged', 'changed my mind', 'defective')",
                        "should_process": False,
                        "reasoning": f"Quantity {quantity} detected in message. Asking for refund reason."
                    }
                else:
                    # No quantity provided, ask for it
                    context["stage"] = "awaiting_quantity"
                    st.session_state.chat_context[customer_id] = context
                    
                    item_info = CATALOG[detected_item]
                    if len(valid_refundable_units) > 1:
                        return {
                            "response": f"You have {len(valid_refundable_units)} refundable {item_info['name']}(s) (${item_info['price']:.2f} each).\n\nHow many would you like to refund? (1-{len(valid_refundable_units)})\n\nType 'refund status' to see detailed breakdown.",
                            "should_process": False,
                            "reasoning": f"Refund intent for {detected_item}. No quantity provided, asking for quantity."
                        }
                    else:
                        # Only 1 unit available, auto-select it
                        context["selected_units"] = valid_refundable_units[:1]
                        context["stage"] = "awaiting_reason"
                        st.session_state.chat_context[customer_id] = context
                        return {
                            "response": f"You have 1 refundable {item_info['name']} (${item_info['price']:.2f}).\n\nWhat's the reason for the refund? (e.g., 'arrived damaged', 'changed my mind')",
                            "should_process": False,
                            "reasoning": f"Only 1 unit available. Asking for refund reason."
                        }
            else:
                # No item specified, show refundable items
                inventory_summary = get_customer_inventory_summary(customer_id)
                return {
                    "response": f"Which item would you like to refund?\n\n{inventory_summary}\n\nPlease specify the item (e.g., 'refund keyboard').\n\nOr type 'refund status' to see detailed breakdown.",
                    "should_process": False,
                    "reasoning": "Refund intent detected but no item specified."
                }
        
        # Check for buy intent
        elif buy_intent:
            context["intent"] = "buy"
            
            # Extract which item user wants to buy
            item_mapping = {
                "keyboard": "ITEM-001",
                "chair": "ITEM-002",
                "monitor": "ITEM-003",
                "screen": "ITEM-003"
            }
            
            detected_item = None
            for item_name, item_id in item_mapping.items():
                if item_name in message_lower:
                    detected_item = item_id
                    break
            
            # Extract quantity from message
            quantity = extract_quantity_from_message(user_message)
            requested_qty = quantity if quantity is not None else 1
            
            if detected_item:
                item_info = CATALOG[detected_item]
                max_allowed = get_max_purchase_allowed(customer_id, detected_item)
                
                if max_allowed <= 0:
                    return {
                        "response": f"You already own 5 {item_info['name']}(s) (maximum allowed). You cannot purchase more of this item.",
                        "should_process": False,
                        "reasoning": f"Purchase blocked: customer already owns 5 units of {detected_item}."
                    }
                
                if requested_qty > max_allowed:
                    return {
                        "response": f"You can only buy {max_allowed} more {item_info['name']}(s) (maximum 5 total). Would you like to buy {max_allowed} instead?",
                        "should_process": False,
                        "reasoning": f"Requested {requested_qty} but only {max_allowed} allowed."
                    }
                
                # Process purchase
                result = execute_purchase(customer_id, customer_tier, detected_item, requested_qty, item_info["price"])
                
                # Set cooldown after API call
                db.set_cooldown(customer_id)
                
                if result.get("ledger_committed"):
                    response_text = f"✅ **PURCHASE COMPLETE!**\n\nYou bought {requested_qty} {item_info['name']}(s) for ${requested_qty * item_info['price']:.2f}.\n\nYour total owned: {db.get_current_owned_count(customer_id, detected_item)}/{5} {item_info['name']}(s)."
                else:
                    response_text = f"❌ **PURCHASE FAILED**\n\n{result.get('rejection_reason', 'Unknown error')}"
                
                context["stage"] = "idle"
                context["intent"] = None
                st.session_state.chat_context[customer_id] = context
                
                return {
                    "response": response_text,
                    "should_process": True,
                    "result": result,
                    "reasoning": f"Processed purchase of {requested_qty} {detected_item}."
                }
            else:
                # No item specified, show available products
                products_summary = get_available_products_summary()
                return {
                    "response": f"**Available products:**\n\n{products_summary}\n\nWhich item would you like to buy? (e.g., 'buy keyboard' or 'buy 2 chairs')",
                    "should_process": False,
                    "reasoning": "Buy intent detected but no item specified."
                }
        
        else:
            # No clear intent, ask user
            return {
                "response": f"I can help you **buy** items or request **refunds**.\n\n**To buy:** say 'buy keyboard' or 'buy 2 chairs'\n**To refund:** say 'refund keyboard' or 'return chair'\n**To see refund status:** say 'refund status'\n\nWhat would you like to do?",
                "should_process": False,
                "reasoning": "No clear intent detected, prompting user."
            }
    
    # Stage 2: Awaiting quantity (for refund) - only reached if user didn't provide quantity initially
    elif context["stage"] == "awaiting_quantity" and context["intent"] == "refund":
        # Try to extract quantity
        quantity = extract_quantity_from_message(user_message)
        
        if quantity is None:
            max_qty = len(context["selected_units"])
            return {
                "response": f"Please tell me how many you want to refund (1-{max_qty}). For example, type '2' or 'one'.\n\nType 'refund status' to see your current refundable units.",
                "should_process": False,
                "reasoning": "Invalid quantity format, asking again."
            }
        
        max_qty = len(context["selected_units"])
        if quantity < 1 or quantity > max_qty:
            return {
                "response": f"Please enter a number between 1 and {max_qty}. You have {max_qty} refundable unit(s).",
                "should_process": False,
                "reasoning": f"Quantity {quantity} out of range."
            }
        
        context["selected_units"] = context["selected_units"][:quantity]
        context["stage"] = "awaiting_reason"
        st.session_state.chat_context[customer_id] = context
        
        item_info = CATALOG[context["selected_item_id"]]
        refund_value = quantity * item_info["price"]
        
        return {
            "response": f"{quantity} {item_info['name']}(s) selected (${refund_value:.2f}).\n\nWhat's the reason for the refund? (e.g., 'arrived damaged', 'changed my mind', 'defective')",
            "should_process": False,
            "reasoning": f"Quantity {quantity} selected. Asking for refund reason."
        }
    
    # Stage 3: Awaiting reason (for refund)
    elif context["stage"] == "awaiting_reason" and context["intent"] == "refund":
        refund_reason = user_message
        unit_ids = [u["unit_id"] for u in context["selected_units"]]
        requested_qty = len(unit_ids)
        item_id = context["selected_item_id"]
        item_info = CATALOG[item_id]
        refund_value = requested_qty * item_info["price"]
        
        # FINAL SAFETY CHECK: Verify units are still refundable before processing
        still_valid = []
        invalid_units = []
        for unit_id in unit_ids:
            unit = db.get_unit_by_id(unit_id)
            if unit and unit['status'] == 'ACTIVE' and unit['strikes'] < db.MAX_STRIKES and not db.is_unit_pending_refund(unit_id):
                still_valid.append(unit_id)
            else:
                invalid_units.append(unit_id)
        
        if invalid_units:
            context["stage"] = "idle"
            context["intent"] = None
            context["selected_units"] = []
            st.session_state.chat_context[customer_id] = context
            return {
                "response": f"❌ Some units are no longer refundable: {', '.join(invalid_units)}.\n\nPlease start over with a new refund request. Type 'refund status' to see current status.",
                "should_process": False,
                "reasoning": f"Units {invalid_units} are no longer refundable (stuck or pending)."
            }
        
        if not still_valid:
            context["stage"] = "idle"
            context["intent"] = None
            st.session_state.chat_context[customer_id] = context
            return {
                "response": "No valid units to refund. They may have been refunded already or reached the strike limit.\n\nType 'refund status' to see your current status.",
                "should_process": False,
                "reasoning": "No valid units remaining."
            }
        
        # Update unit_ids to only valid ones
        unit_ids = still_valid
        requested_qty = len(unit_ids)
        refund_value = requested_qty * item_info["price"]
        
        # Lock units to prevent concurrent processing
        locked = True
        for unit_id in unit_ids:
            if not db.lock_unit_for_refund(unit_id):
                locked = False
                break
        
        if not locked:
            db.unlock_units_for_refund(unit_ids)
            return {
                "response": "Some units are already being processed. Please wait a moment and try again.",
                "should_process": False,
                "reasoning": "Units already locked for refund."
            }
        
        # Create and process refund request
        req = db.create_refund_request(customer_id, item_id, refund_reason, unit_ids, refund_value)
        
        ledger_ctx = {
            "customer_id": customer_id,
            "customer_tier": customer_tier,
            "item_id": item_id,
            "total_cost": refund_value,
            "refund_quantity": requested_qty
        }
        
        result = execute_dispute_evaluation(req, ledger_ctx)
        
        # Unlock units
        db.unlock_units_for_refund(unit_ids)
        
        # Set cooldown after API call
        db.set_cooldown(customer_id)
        
        decision = result.get("decision", "Pending")
        evidence = result.get("evidence", "")
        
        if decision == "Approved":
            response_text = f"✅ **REFUND APPROVED**\n\n{evidence}\n\nRefund of ${refund_value:.2f} for {requested_qty} {item_info['name']}(s) will be processed."
        elif decision == "Rejected":
            unit = db.get_unit_by_id(unit_ids[0]) if unit_ids else None
            strikes = unit.get('strikes', 0) if unit else 0
            response_text = f"❌ **REFUND REJECTED**\n\n{evidence}\n\nYou have {db.MAX_STRIKES - strikes} attempt(s) remaining for this item."
        else:
            response_text = f"⚠️ **ESCALATED TO HUMAN REVIEW**\n\n{evidence}\n\nA human agent will review your case shortly."
            db.push_to_human_queue(req)
        
        # Reset context
        context["stage"] = "idle"
        context["intent"] = None
        context["selected_item_id"] = None
        context["selected_units"] = []
        context["pending_reason"] = None
        st.session_state.chat_context[customer_id] = context
        
        return {
            "response": response_text,
            "should_process": True,
            "result": result,
            "reasoning": evidence
        }
    
    # Fallback - reset if something went wrong
    context["stage"] = "idle"
    context["intent"] = None
    st.session_state.chat_context[customer_id] = context
    return {
        "response": "I'm here to help you buy items or request refunds. Try saying 'buy keyboard', 'refund chair', or 'refund status'.",
        "should_process": False,
        "reasoning": "Fallback response after context reset."
    }

# Chat Interface
if app_mode == "💬 AI Chat Assistant":
    st.title("💬 AI Shopping & Refund Assistant")
    st.caption(f"Chatting as: {chat_customer_id} - {db.MOCK_CLIENTS[chat_customer_id]['name']} ({db.MOCK_CLIENTS[chat_customer_id]['tier']})")
    st.markdown("I can help you **buy** items or request **refunds**. Just tell me what you want to do!")
    
    # Get this customer's message history
    customer_messages = st.session_state.chat_messages.get(chat_customer_id, [])
    
    # Display chat history for this customer only
    for msg in customer_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("trace"):
                with st.expander("🔍 Agent Reasoning"):
                    st.caption(msg["trace"])
    
    # Chat input
    if prompt := st.chat_input("Type your message here..."):
        # Add user message to this customer's history
        st.session_state.chat_messages[chat_customer_id].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Process with agent
        with st.chat_message("assistant"):
            with st.spinner("🤖 Thinking..."):
                result = process_chat_message(prompt, chat_customer_id)
                st.markdown(result["response"])
                
                # Store with reasoning trace
                st.session_state.chat_messages[chat_customer_id].append({
                    "role": "assistant", 
                    "content": result["response"],
                    "trace": result.get("reasoning", "")
                })
        
        st.rerun()

# Customer Portal
elif app_mode == "🛍️ Customer Portal":
    st.title("🛍️ Customer Portal")
    st.caption("Simulate purchases and request refunds - agent responds automatically")
    
    col_buy, col_history = st.columns([1, 1])
    
    with col_buy:
        st.subheader("Make a Purchase")
        client_ids = list(db.MOCK_CLIENTS.keys())
        
        selected_cust_id = st.selectbox(
            "Customer", 
            options=client_ids,
            format_func=lambda x: f"{x} - {db.MOCK_CLIENTS[x]['name']} ({db.MOCK_CLIENTS[x]['tier']})",
            key="customer_select"
        )
        
        client_profile = db.MOCK_CLIENTS[selected_cust_id]
        st.info(f"**Tier:** {client_profile['tier']} | **Email:** {client_profile['email']}")
        
        item_id = st.selectbox(
            "Product", 
            options=list(CATALOG.keys()), 
            format_func=lambda x: f"{CATALOG[x]['name']} (${CATALOG[x]['price']}) {'🔒 Non-refundable' if not CATALOG[x]['refundable'] else '✅ Refundable'}",
            key="product_select"
        )
        
        qty = st.number_input("Quantity", min_value=1, max_value=5, value=1)
        
        if st.button("💳 Purchase", type="primary", width='stretch'):
            # Check cooldown before purchase
            cooldown = db.get_cooldown_remaining(selected_cust_id)
            if cooldown > 0:
                st.error(f"⏳ Please wait {cooldown} seconds before making another purchase.")
            else:
                unit_price = CATALOG[item_id]["price"]
                with st.spinner("Processing..."):
                    result = execute_purchase(selected_cust_id, client_profile["tier"], item_id, qty, unit_price)
                    db.set_cooldown(selected_cust_id)
                    
                if result.get("ledger_committed"):
                    st.success(f"✅ Purchase complete! Created {qty} new unit(s).")
                    st.rerun()
                else:
                    st.error(f"❌ Purchase failed: {result.get('rejection_reason')}")
    
    with col_history:
        st.subheader("Your Inventory")
        
        transactions = db.get_client_transactions(selected_cust_id)
        
        if not transactions:
            st.info("No purchases yet.")
        else:
            for tx in transactions:
                with st.container(border=True):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.markdown(f"**{tx['product_name']}**")
                        st.caption(f"Item: `{tx['item_id']}` | Qty owned: {tx['quantity']}")
                        st.caption(f"Unit price: ${tx['price']:.2f} | Total value: ${tx['total_value']:.2f}")
                        if not tx['refundable']:
                            st.error("🔒 Non-refundable item")
                        
                        if tx.get('units'):
                            with st.expander(f"View {len(tx['units'])} unit(s) details"):
                                for unit in tx['units']:
                                    is_stuck = unit['status'] == 'STUCK' or unit.get('strikes', 0) >= db.MAX_STRIKES
                                    is_active = unit['status'] == 'ACTIVE' and not is_stuck
                                    is_refunded = unit['status'] == 'REFUNDED'
                                    is_pending = db.is_unit_pending_refund(unit['unit_id'])
                                    
                                    if is_stuck:
                                        st.error(f"🔒 Unit {unit['unit_id']} - STUCK ({unit.get('strikes', 0)}/{db.MAX_STRIKES} strikes)")
                                    elif is_active:
                                        if is_pending:
                                            st.warning(f"⏳ Unit {unit['unit_id']} - PENDING")
                                        elif unit.get('strikes', 0) > 0:
                                            st.warning(f"⚠️ Unit {unit['unit_id']} - Strikes: {unit.get('strikes', 0)}/{db.MAX_STRIKES}")
                                        else:
                                            st.success(f"✅ Unit {unit['unit_id']} - No strikes")
                                    elif is_refunded:
                                        st.caption(f"📦 Unit {unit['unit_id']} - Refunded")
                    
                    with col2:
                        refundable_units = []
                        for u in tx.get('units', []):
                            is_refundable = u['status'] == 'ACTIVE' and u.get('strikes', 0) < db.MAX_STRIKES
                            is_pending = db.is_unit_pending_refund(u['unit_id'])
                            if is_refundable and not is_pending:
                                refundable_units.append(u)
                        
                        if refundable_units and tx['refundable']:
                            with st.popover("Request Refund"):
                                st.markdown("**Select units to refund:**")
                                
                                selected_units = []
                                for unit in refundable_units:
                                    strike_text = f"⚠️ {unit['strikes']}/{db.MAX_STRIKES} strikes" if unit['strikes'] > 0 else "✅ No strikes"
                                    if st.checkbox(
                                        f"Unit {unit['unit_id']} - {strike_text}",
                                        key=f"select_{unit['unit_id']}"
                                    ):
                                        selected_units.append(unit)
                                
                                if selected_units:
                                    refund_qty = len(selected_units)
                                    refund_value = refund_qty * tx['price']
                                    st.info(f"Refund value: **${refund_value:.2f}** for {refund_qty} unit(s)")
                                    
                                    reason = st.text_area(
                                        "Reason for refund:", 
                                        key=f"reason_{tx['item_id']}",
                                        placeholder="e.g., Item arrived damaged, defective, wrong item sent, etc."
                                    )
                                    
                                    if st.button("Submit Refund Request", key=f"submit_{tx['item_id']}", width='stretch'):
                                        if reason.strip():
                                            unit_ids = [u["unit_id"] for u in selected_units]
                                            
                                            # Check cooldown
                                            cooldown = db.get_cooldown_remaining(selected_cust_id)
                                            if cooldown > 0:
                                                st.error(f"⏳ Please wait {cooldown} seconds before requesting another refund.")
                                            else:
                                                locked = True
                                                for unit_id in unit_ids:
                                                    if not db.lock_unit_for_refund(unit_id):
                                                        locked = False
                                                        st.error(f"Unit {unit_id} is already being processed")
                                                        break
                                                
                                                if not locked:
                                                    db.unlock_units_for_refund(unit_ids)
                                                    st.rerun()
                                                
                                                with st.spinner(f"🤖 Agent processing..."):
                                                    try:
                                                        req = db.create_refund_request(
                                                            selected_cust_id, tx["item_id"], reason, unit_ids, refund_value
                                                        )
                                                        
                                                        ledger_ctx = {
                                                            "customer_id": selected_cust_id,
                                                            "customer_tier": db.MOCK_CLIENTS[selected_cust_id]['tier'],
                                                            "item_id": tx["item_id"],
                                                            "total_cost": refund_value,
                                                            "refund_quantity": refund_qty
                                                        }
                                                        
                                                        result = execute_dispute_evaluation(req, ledger_ctx)
                                                        
                                                        # Set cooldown after API call
                                                        db.set_cooldown(selected_cust_id)
                                                        
                                                        st.markdown("---")
                                                        st.subheader("🤖 Agent Decision")
                                                        
                                                        col_r1, col_r2, col_r3, col_r4 = st.columns(4)
                                                        with col_r1:
                                                            st.metric("Decision", result.get("decision", "Pending"))
                                                        with col_r2:
                                                            st.metric("Units", refund_qty)
                                                        with col_r3:
                                                            tokens = result.get("token_usage", {})
                                                            st.metric("Tokens", tokens.get("total_tokens", 0))
                                                        with col_r4:
                                                            st.metric("Latency", f"{result.get('latency_ms', 0):.0f}ms")
                                                        
                                                        st.markdown("**Evidence / Reasoning:**")
                                                        st.info(result.get("evidence", "No evidence provided"))
                                                        
                                                        if result.get("decision") == "Pending":
                                                            db.push_to_human_queue(req)
                                                            st.warning("⚠️ Case escalated to Human Review")
                                                        
                                                        db.unlock_units_for_refund(unit_ids)
                                                        st.rerun()
                                                    except Exception as e:
                                                        db.unlock_units_for_refund(unit_ids)
                                                        st.error(f"Error: {str(e)}")
                                        else:
                                            st.error("Please provide a reason")
                                else:
                                    st.info("Select at least one unit")
                        elif tx['quantity'] > 0 and not tx['refundable']:
                            st.error("🔒 Non-refundable")
                        else:
                            stuck_units = [u for u in tx.get('units', []) if u['status'] == 'STUCK' or u.get('strikes', 0) >= db.MAX_STRIKES]
                            if stuck_units:
                                st.info(f"📦 {len(stuck_units)} stuck unit(s)")
                            else:
                                st.info("No refundable units")

# AI Agent Console
elif app_mode == "🤖 AI Agent Console":
    st.title("🤖 AI Agent Console")
    st.caption("Monitor agent decisions and view reasoning traces")
    
    if "ai_temp_holder" not in st.session_state:
        st.session_state["ai_temp_holder"] = []
    
    pending = st.session_state["ai_temp_holder"].copy()
    
    if pending:
        st.info(f"🤖 Agent is automatically processing {len(pending)} request(s)...")
        
        for req in pending[:]:
            with st.container(border=True):
                st.markdown(f"### Request {req['refund_id']}")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Customer:** {req['customer_id']} - {db.MOCK_CLIENTS[req['customer_id']]['name']}")
                    st.markdown(f"**Tier:** {db.MOCK_CLIENTS[req['customer_id']]['tier']}")
                    st.markdown(f"**Item:** {CATALOG[req['item_id']]['name']}")
                    st.markdown(f"**Units:** {', '.join(req.get('unit_ids', []))}")
                with col2:
                    st.markdown(f"**Refund Quantity:** {req.get('refund_quantity', 1)}")
                    st.markdown(f"**Refund Value:** ${req.get('refund_value', 0):.2f}")
                
                st.markdown(f"**Customer Statement:** \"{req['reason']}\"")
                
                with st.spinner("Agent analyzing..."):
                    strike_status = db.get_strike_status_for_units(req.get("unit_ids", []))
                    
                    if not strike_status["can_refund"]:
                        decision = "Rejected"
                        evidence = f"Cannot refund: Unit(s) {strike_status['stuck_units']} have reached maximum strikes ({db.MAX_STRIKES})."
                        req["decision"] = decision
                        req["evidence"] = evidence
                        req["current_stage"] = "Completed"
                        req["assigned_to"] = "None"
                        
                        st.subheader("📊 Agent Decision")
                        st.error(f"❌ {decision}")
                        st.info(evidence)
                        
                        db.unlock_units_for_refund(req.get("unit_ids", []))
                        st.session_state["ai_temp_holder"].remove(req)
                        st.rerun()
                    else:
                        refund_value = req.get('refund_value', 0)
                        
                        ledger_ctx = {
                            "customer_id": req["customer_id"],
                            "customer_tier": db.MOCK_CLIENTS[req['customer_id']]['tier'],
                            "item_id": req["item_id"],
                            "total_cost": refund_value,
                            "refund_quantity": req.get('refund_quantity', 1)
                        }
                        
                        result = execute_dispute_evaluation(req, ledger_ctx)
                        
                        st.subheader("📊 Agent Trace")
                        trace_cols = st.columns(4)
                        with trace_cols[0]:
                            st.metric("Decision", result.get("decision", "Pending"))
                        with trace_cols[1]:
                            st.metric("Retries", result.get("retry_count", 0))
                        with trace_cols[2]:
                            tokens = result.get("token_usage", {})
                            st.metric("Total Tokens", tokens.get("total_tokens", 0))
                        with trace_cols[3]:
                            st.metric("Latency", f"{result.get('latency_ms', 0):.0f}ms")
                        
                        st.markdown("**Evidence / Reasoning:**")
                        st.info(result.get("evidence", "No evidence provided"))
                        
                        if result.get("token_usage"):
                            with st.expander("Token Breakdown"):
                                st.json(result.get("token_usage", {}))
                        
                        if result.get("decision") in ["Approved", "Rejected"]:
                            st.markdown("**Unit Outcomes:**")
                            for unit_id in req.get("unit_ids", []):
                                unit = db.get_unit_by_id(unit_id)
                                if unit:
                                    if result.get("decision") == "Approved":
                                        st.success(f"✅ Unit {unit_id} - Refunded")
                                    else:
                                        if unit.get("status") == "STUCK" or unit.get("strikes", 0) >= db.MAX_STRIKES:
                                            st.error(f"🔒 Unit {unit_id} - STUCK ({unit.get('strikes', 0)}/{db.MAX_STRIKES} strikes)")
                                        else:
                                            st.warning(f"⚠️ Unit {unit_id} - Strike {unit.get('strikes', 0)}/{db.MAX_STRIKES} ({db.MAX_STRIKES - unit.get('strikes', 0)} left)")
                        
                        db.unlock_units_for_refund(req.get("unit_ids", []))
                        st.session_state["ai_temp_holder"].remove(req)
                
                st.divider()
        
        st.rerun()
    
    else:
        st.info("No pending requests. All requests are processed automatically when submitted.")

# Human Review
elif app_mode == "⚖️ Human Review":
    st.title("⚖️ Human Review Dashboard")
    st.caption("Review escalated cases and override AI decisions")
    
    pending = st.session_state.get("human_queue", [])
    st.metric("Cases Pending Review", len(pending))
    
    if not pending:
        st.success("No pending cases. All caught up!")
    else:
        for idx, req in enumerate(pending):
            with st.container(border=True):
                st.error(f"🔴 CASE {req['refund_id']} - Requires Review")
                
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Customer:** {req['customer_id']} - {db.MOCK_CLIENTS[req['customer_id']]['name']}")
                    st.markdown(f"**Tier:** {db.MOCK_CLIENTS[req['customer_id']]['tier']}")
                    st.markdown(f"**Item:** {CATALOG[req['item_id']]['name']}")
                    st.markdown(f"**Units:** {', '.join(req.get('unit_ids', []))}")
                    st.markdown(f"**Refund Quantity:** {req.get('refund_quantity', 1)}")
                    st.markdown(f"**Refund Value:** ${req.get('refund_value', 0):.2f}")
                with col2:
                    st.markdown(f"**Customer Statement:** \"{req['reason']}\"")
                
                st.markdown("---")
                st.markdown("**🤖 AI Agent's Reasoning (Escalation Reason):**")
                st.info(req.get('evidence', 'Unknown'))
                st.markdown("---")
                
                st.markdown("**Unit Status:**")
                for unit_id in req.get("unit_ids", []):
                    unit = db.get_unit_by_id(unit_id)
                    if unit:
                        is_stuck = unit['status'] == 'STUCK' or unit.get('strikes', 0) >= db.MAX_STRIKES
                        if is_stuck:
                            st.error(f"🔒 Unit {unit_id} - STUCK ({unit.get('strikes', 0)}/{db.MAX_STRIKES} strikes)")
                        else:
                            st.caption(f"📦 Unit {unit_id} - Strikes: {unit.get('strikes', 0)}/{db.MAX_STRIKES}")
                
                st.markdown("---")
                st.markdown("**👨‍💼 Human Override Decision:**")
                
                col_approve, col_reject = st.columns(2)
                with col_approve:
                    if st.button("✅ Approve Refund (Override AI)", key=f"approve_{req['refund_id']}", width='stretch'):
                        req["decision"] = "Approved"
                        req["evidence"] = f"Human override approved: {req.get('evidence', '')}"
                        for unit_id in req.get("unit_ids", []):
                            db.approve_unit_refund(unit_id, req["evidence"])
                            db.unlock_unit_for_refund(unit_id)
                        st.session_state["human_queue"].pop(idx)
                        st.success("✅ Refund APPROVED by human override and logged to audit trail")
                        st.rerun()
                with col_reject:
                    if st.button("❌ Reject Refund (Override AI)", key=f"reject_{req['refund_id']}", width='stretch'):
                        req["decision"] = "Rejected"
                        req["evidence"] = f"Human override rejected: {req.get('evidence', '')}"
                        for unit_id in req.get("unit_ids", []):
                            db.increment_unit_strike(unit_id, req["reason"])
                            db.unlock_unit_for_refund(unit_id)
                        st.session_state["human_queue"].pop(idx)
                        st.error("❌ Refund REJECTED by human override and logged to audit trail")
                        st.rerun()

# Audit Log
elif app_mode == "📊 Audit Log":
    st.title("📊 Consolidated Audit Log")
    st.caption("Complete history of all refund decisions with AI reasoning")
    
    all_decisions = []
    for unit_id, unit in st.session_state.get("units", {}).items():
        for attempt in unit.get("refund_attempts", []):
            all_decisions.append({
                "refund_id": f"{unit_id}_{attempt.get('timestamp', '')[:19]}",
                "timestamp": attempt.get("timestamp", ""),
                "customer_id": unit.get("customer_id", "Unknown"),
                "item_id": unit.get("item_id", "Unknown"),
                "unit_id": unit_id,
                "decision": attempt.get("decision", "Unknown"),
                "evidence": attempt.get("evidence", attempt.get("reason", "")),
                "reason": attempt.get("reason", ""),
                "strike_number": attempt.get("strike_number")
            })
    
    if not all_decisions:
        st.info("No refund decisions logged yet.")
    else:
        all_decisions = sorted(all_decisions, key=lambda x: x.get('timestamp', ''), reverse=True)
        
        table_data = []
        for d in all_decisions:
            timestamp = d.get('timestamp', 'Unknown')
            if 'T' in timestamp:
                timestamp = timestamp.split('T')[0]
            
            evidence_short = d.get('evidence', 'No evidence')
            if len(evidence_short) > 80:
                evidence_short = evidence_short[:80] + "..."
            
            table_data.append({
                "Refund ID": d.get('refund_id', 'Unknown'),
                "Date": timestamp,
                "Customer": d.get('customer_id', 'Unknown'),
                "Item": d.get('item_id', 'Unknown'),
                "Unit": d.get('unit_id', 'Unknown'),
                "Decision": d.get('decision', 'Unknown'),
                "Strike": d.get('strike_number', ''),
                "Evidence": evidence_short
            })
        
        df = pd.DataFrame(table_data)
        
        st.dataframe(
            df,
            column_config={
                "Refund ID": st.column_config.TextColumn("Refund ID", width="small"),
                "Date": st.column_config.TextColumn("Date", width="small"),
                "Customer": st.column_config.TextColumn("Customer", width="small"),
                "Item": st.column_config.TextColumn("Item", width="small"),
                "Unit": st.column_config.TextColumn("Unit", width="small"),
                "Decision": st.column_config.TextColumn("Decision", width="small"),
                "Strike": st.column_config.TextColumn("Strike", width="small"),
                "Evidence": st.column_config.TextColumn("Evidence", width="large"),
            },
            hide_index=True,
            use_container_width=True
        )
        
        st.subheader("📋 Full Details with AI Reasoning")
        st.caption("Click to expand and see complete AI reasoning, customer statements, and metrics")
        
        for d in all_decisions[:20]:
            timestamp_full = d.get('timestamp', 'Unknown')
            if 'T' in timestamp_full:
                timestamp_full = timestamp_full.replace('T', ' ')[:19]
            
            with st.expander(f"{d.get('refund_id', 'Unknown')} - {d.get('decision', 'Unknown')} - {timestamp_full}"):
                st.markdown(f"**Customer ID:** {d.get('customer_id', 'Unknown')}")
                st.markdown(f"**Item ID:** {d.get('item_id', 'Unknown')}")
                st.markdown(f"**Unit ID:** {d.get('unit_id', 'Unknown')}")
                st.markdown(f"**Decision:** {d.get('decision', 'Unknown')}")
                if d.get('strike_number'):
                    st.markdown(f"**Strike Number:** {d.get('strike_number')}/{db.MAX_STRIKES}")
                st.markdown(f"**Customer Statement:** {d.get('reason', 'No reason provided')}")
                st.markdown("---")
                st.markdown("**🤖 AI Agent's Reasoning / Evidence:**")
                st.info(d.get('evidence', 'No evidence provided'))

# Agent Analytics
elif app_mode == "📈 Agent Analytics":
    st.title("📈 Agent Analytics")
    st.caption("Performance metrics and recent AI decisions with reasoning")
    
    all_units = list(st.session_state.get("units", {}).values())
    all_attempts = []
    for unit in all_units:
        all_attempts.extend(unit.get("refund_attempts", []))
    
    if not all_attempts:
        st.info("No data yet. Process some refunds first.")
    else:
        col1, col2, col3, col4 = st.columns(4)
        
        approved = sum(1 for a in all_attempts if a.get('decision') == 'Approved')
        rejected = sum(1 for a in all_attempts if a.get('decision') == 'Rejected')
        
        stuck_units = [u for u in all_units if u.get('status') == 'STUCK' or u.get('strikes', 0) >= db.MAX_STRIKES]
        active_units = [u for u in all_units if u.get('status') == 'ACTIVE' and u.get('strikes', 0) < db.MAX_STRIKES]
        refunded_units = [u for u in all_units if u.get('status') == 'REFUNDED']
        
        with col1:
            st.metric("Total Attempts", len(all_attempts))
        with col2:
            st.metric("Approved", approved)
        with col3:
            st.metric("Rejected", rejected)
        with col4:
            st.metric("Approval Rate", f"{approved/len(all_attempts)*100:.0f}%" if all_attempts else "0%")
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Active Units", len(active_units))
        with col2:
            st.metric("Stuck Units", len(stuck_units))
        with col3:
            st.metric("Refunded Units", len(refunded_units))
        with col4:
            st.metric("Max Strikes", db.MAX_STRIKES)
        
        st.subheader("📋 Recent Decisions with AI Reasoning")
        
        for a in reversed(all_attempts[-10:]):
            timestamp = a.get('timestamp', 'Unknown')
            if 'T' in timestamp:
                timestamp = timestamp[:19]
            
            with st.container(border=True):
                col_date, col_decision = st.columns([2, 1])
                with col_date:
                    st.caption(f"📅 {timestamp}")
                with col_decision:
                    if a.get('decision') == 'Approved':
                        st.markdown("✅ **APPROVED**")
                    elif a.get('decision') == 'Rejected':
                        st.markdown("❌ **REJECTED**")
                    else:
                        st.markdown("⏳ **PENDING**")
                
                st.markdown(f"**Unit:** {a.get('unit_id', 'Unknown')} | **Item:** {a.get('item_id', 'Unknown')}")
                st.markdown(f"**Customer Statement:** \"{a.get('reason', 'No reason')}\"")
                st.markdown("**🤖 AI Reasoning:**")
                st.info(a.get('evidence', 'No evidence provided')[:300] + ("..." if len(a.get('evidence', '')) > 300 else ""))