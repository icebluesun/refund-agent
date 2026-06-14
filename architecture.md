Sample Refund Agent – Architecture & Code Explanation

OVERVIEW
The application is a full-stack AI refund assistant built with:
- Frontend: Streamlit (multi-page UI with Chat, Portal, Console, Audit, Analytics)
- Backend logic: LangGraph workflows + Google Gemini 2.5 Flash
- State management: st.session_state (in-memory, no external DB required for demo)

PROJECT STRUCTURE
.
├── app.py              # Main Streamlit UI (6 pages)
├── database.py         # In-memory data models, per-unit tracking, strikes, cooldowns
├── graph.py            # LangGraph workflows (purchase & dispute) + Gemini API retry
├── main.py             # Bridge between UI and LangGraph workflows
├── policy.py           # Loads policy.md as source of truth
├── policy.md           # Human-readable refund policy
├── requirements.txt    # Python dependencies
└── .env                # GEMINI_API_KEY (local only)

DATA MODEL – PER-UNIT TRACKING

Each physical item is a unit stored in st.session_state["units"]:

{
    "UNIT-1001": {
        "unit_id": "UNIT-1001",
        "customer_id": "CUST-001",
        "item_id": "ITEM-001",
        "purchase_date": "2024-01-15",
        "status": "ACTIVE",        # ACTIVE, REFUNDED, or STUCK
        "strikes": 0,              # 0-3, max 3
        "refund_attempts": [],     # List of {timestamp, reason, decision, evidence}
        "original_transaction_id": "TX-ABC123"
    }
}

Strike limit: After 3 rejected refund attempts, a unit becomes STUCK and can never be refunded again.

AGENT WORKFLOW (LangGraph)

Purchase Workflow (graph.py)
1. verify_limits_node – checks ownership cap (max 5 units per customer per item)
2. Creates new units in st.session_state["units"] with status ACTIVE
3. commit_ledger_node – generates transaction ID and returns success

Dispute (Refund) Workflow (graph.py)

The ai_agent_dispute_node processes refund requests in this order:

Priority 1: Unit(s) already stuck -> REJECT + evidence
Priority 2: Non-refundable item (ITEM-003) -> REJECT + strike
Priority 3: Manufacturing defect keywords -> APPROVE
Priority 4: Buyer remorse keywords -> REJECT + strike
Priority 5: Customer-caused damage keywords -> REJECT + strike
Priority 6: High value (>$700) -> ESCALATE to Human
Priority 7: Ambiguous / no match -> Send to Gemini LLM

Damage keywords: damaged, broken, defective, cracked, not working, faulty, came broken, arrived damaged, dead on arrival, doa

Remorse keywords: changed mind, no longer need, don't want, found better, impulse buy

Customer damage keywords: i broke, i smashed, my fault, i dropped, accidentally broke

CHAT ASSISTANT (AI Chat Assistant)

The chat interface supports natural language for both buying and refunding:

User says "buy keyboard" -> Agent asks quantity (or uses number if provided), checks cap, processes purchase
User says "buy 2 chairs" -> Direct purchase if within cap
User says "refund keyboard" -> Shows owned quantity, asks how many (or uses number if provided)
User says "refund 1 keyboard" -> Skips quantity question, asks for reason directly
User says "refund status" -> Shows inventory breakdown per item
User says "show my items" -> Lists all owned items with counts
User says "cancel" -> Aborts current refund flow

Safety checks before processing any refund:
- Cooldown (10 seconds between requests)
- Unit not already pending refund (is_unit_pending_refund())
- Unit not stuck (strikes < 3)
- Lock unit to prevent concurrent refunds

ADMIN DASHBOARD (AI Agent Console)

Displays for each request:
- Decision: Approved, Rejected, or Pending (escalated)
- Retries: Number of API retry attempts (0-2)
- Total Tokens: Sum of prompt + candidate tokens from Gemini
- Latency: API response time in milliseconds
- Evidence: Full AI reasoning citing policy rules
- Token Breakdown: Expandable view of prompt vs candidate tokens

RETRY LOGIC & DEMO MODE

Production retry (graph.py):
def call_gemini_with_retry(prompt, system_instruction, max_retries=1, wait_seconds=3):
    for attempt in range(max_retries + 1):
        try:
            API call
            return result
        except Exception:
            if attempt == max_retries:
                return error
            time.sleep(wait_seconds)

Demo mode (for Loom video):
At the top of graph.py: DEMO_SIMULATE_RETRY = True (Set to False for normal operation)

When True, the first API attempt fails (simulated), waits 10 seconds, then retries successfully.
The UI shows status messages during the wait.

COOLDOWN & RATE LIMITING

Feature                          | Location      | Value
Cooldown between requests        | database.py   | 10 seconds
Minimum interval between Gemini  | graph.py      | 2 seconds
Retry on 429 (rate limit)        | graph.py      | 60 second wait

POLICY ENFORCEMENT (policy.md)

The policy file is loaded at runtime and injected into Gemini's system prompt:

Absolute Rules:
- Final Sale Items (ITEM-003) -> NO REFUNDS
- High Value Escalation (>$700) -> Escalate to Human
- Buyer Remorse -> REJECT
- Customer-Caused Damage -> REJECT

Conditional Approvals:
- Manufacturing Defect + PLATINUM/GOLD + <=$500 -> APPROVE
- Manufacturing Defect + STANDARD + <=$200 -> APPROVE

PRODUCTION IMPROVEMENTS (mentioned in Loom video)

Area           | Current (Demo)                    | Production
Database       | st.session_state (resets on refresh) | PostgreSQL / Supabase
Authentication | None (anyone can act as any customer) | Login with roles (customer vs admin)
Payments       | Mock approval                     | Stripe integration
Notifications  | None                              | Slack/email for human escalations
Monitoring     | None                              | OpenTelemetry + Grafana/Datadog
CI/CD          | Manual deploy                     | GitHub Actions automated tests + deploy
Rate limiting  | Basic cooldown                    | Request queue with proper backpressure

KEY FILES SUMMARY

File           | Purpose                                    | Key Functions/Classes
app.py         | Streamlit UI                               | 6 pages: Chat, Portal, Console, Human Review, Audit Log, Analytics
database.py    | Data layer                                 | MOCK_CLIENTS, CATALOG, per-unit CRUD, strike tracking, cooldown
graph.py       | Agent logic                                | PurchaseState, DisputeState, ai_agent_dispute_node, Gemini retry
main.py        | Bridge                                     | execute_purchase(), execute_dispute_evaluation()
policy.py      | Policy loader                              | load_policy() reads policy.md
policy.md      | Policy text                                | Human-readable rules for agent and reviewers