Deploying Loopp Refund Agent to Streamlit Cloud

PREREQUISITES
- A GitHub account
- A Streamlit Community Cloud account (free tier works)
- A Gemini API key from Google AI Studio (https://aistudio.google.com/apikey)

STEP 1: Prepare Your Repository

Make sure your repository contains these files:

app.py
database.py
graph.py
main.py
policy.py
policy.md
requirements.txt
.gitignore (optional)

requirements.txt should contain:
streamlit>=1.58.0
langgraph>=1.2.0
pandas>=2.0.0
python-dotenv>=1.0.0

Note: langgraph will pull its own dependencies (langchain-core, pydantic). No need to list fastapi, uvicorn, etc.

STEP 2: Push to GitHub

git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/yourusername/refund-agent.git
git push -u origin main

STEP 3: Deploy on Streamlit Cloud

1. Go to share.streamlit.io and sign in with GitHub.
2. Click "New app".
3. Select your repository, branch (main), and main file (app.py).
4. Click "Advanced settings".
5. Add your Gemini API key as a secret:
   - Key: GEMINI_API_KEY
   - Value: your-api-key-here
6. Click "Deploy".

STEP 4: Environment Variables (for retry demo)

If you want to demonstrate retries in the live version, add to Streamlit Cloud secrets:
- Key: DEMO_RETRY
- Value: true

Important: In the deployed version, keep DEMO_SIMULATE_RETRY = False in graph.py unless you want simulated failures for every user.

STEP 5: Verify Deployment

After deployment, test these features:
- Chat assistant: "buy keyboard", "refund keyboard", "refund status"
- Customer Portal: purchase and refund with unit selection
- Admin dashboard: check traces, tokens, latency

TROUBLESHOOTING

Issue: No module named 'langgraph'
Solution: Ensure langgraph>=1.2.0 is in requirements.txt

Issue: GEMINI_API_KEY not found
Solution: Add the secret in Streamlit Cloud advanced settings

Issue: Rate limit errors (429)
Solution: The app has built-in cooldown and retries; reduce test frequency

Issue: Chat context mixed between users
Solution: Not an issue in deployed version – each browser session is independent

LOCAL TESTING BEFORE DEPLOYMENT

git clone https://github.com/yourusername/refund-agent.git
cd refund-agent

python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

pip install -r requirements.txt

echo "GEMINI_API_KEY=your_key_here" > .env

streamlit run app.py