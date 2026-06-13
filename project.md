# Loopp AI Agent Challenge – Original Requirements

## Objective
Build a fully functional web application: **An AI Customer Support Agent** that processes or denies e‑commerce refunds using an LLM (Gemini) to generate boilerplate code, system architecture, and datasets.

## Core Components Required

### 1. Synthetic Data Storage
- Mock CRM database with **15 customer profiles** and order histories.
- A corporate **Refund Policy** text document with strict rules (e.g., final sale items non‑refundable, refunds over $500 require human escalation).

### 2. Backend & Agent Layer
- Local API server (FastAPI/Express) hosting an **agent loop** (LangGraph, CrewAI, or raw function calling).
- The agent must **dynamically call tools** to query the synthetic database and validate user requests against the policy.
- Assume customers will **plead, argue, or try to trick** the agent – the written policy is the **source of truth** and the agent must **hold the line**.

### 3. Frontend UI
- A **customer chat window** to test the agent.
- An **admin dashboard** displaying the agent’s internal reasoning logs (tool I/O, retries, token cost, latency).

## Deliverables (Definition of “Finished”)
- **Loom video walkthrough** (max 5 minutes) showing:
  - Live UI with a successful agent run.
  - A step that **failed or retried** and how you’d debug it from the logs.
  - Call out **what you’d add before production**.
- **Live URL** (optional, but nice to have).

## Evaluation Criteria
- Product completeness (zero configuration errors).
- Agent resilience (edge cases, policy violations, prompt injection).
- System architecture (clean separation between UI, API, and LLM orchestration).

## Timeline
- Estimated 8–10 hours of development, return within 9 calendar days.
- Final round: 1‑hour live demo with the team.