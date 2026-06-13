# policy.py
"""Simple policy loader - all enforcement logic is in policy.md for the LLM"""

import os

def load_policy() -> str:
    """Load the full policy text from policy.md - this is the SOURCE OF TRUTH"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        policy_path = os.path.join(current_dir, "policy.md")
        
        with open(policy_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "# Policy file not found. Please create policy.md"
    

    