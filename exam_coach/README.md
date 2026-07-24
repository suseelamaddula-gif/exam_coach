# AI Exam Preparation Coach

A Flask app that implements the prompt-engineered exam coach: personalized
study plans, daily tasks, revision plans, mock test schedules, weakness
analysis, motivation, and multi-turn chat updates — all powered by the
Anthropic Claude API.

## Project structure
```
exam_coach/
├── app.py              # Flask backend, wires prompts to Claude API, session memory
├── prompts.py           # All 10 prompt templates (system, plan, daily, revision, etc.)
├── templates/
│   └── index.html      # Frontend UI (form + quick tools + chat)
├── requirements.txt
├── .env.example
└── README.md
```

## Setup in VS Code

1. **Open the folder** `exam_coach` in VS Code.

2. **Create a virtual environment** (Terminal → New Terminal):
   ```bash
   python -m venv venv
   ```
   Activate it:
   - Windows: `venv\Scripts\activate`
   - Mac/Linux: `source venv/bin/activate`

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Add your API key.**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and paste your real Anthropic API key
   (get one at https://console.anthropic.com/):
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxxxxxx
   FLASK_SECRET_KEY=any-random-string
   ```

5. **Run the app:**
   ```bash
   python app.py
   ```
   Open your browser at **http://127.0.0.1:5000**

## How to use it

1. Fill in your exam details on the left (exam name, date, syllabus,
   strong/weak subjects, daily hours) and click **Save Details**.
2. Click **Generate Study Plan** to get your personalized day-by-day plan
   (or use **One-Shot Master Plan** to get everything in a single response).
3. Use the **Quick Tools** panel any time for:
   - Today's Task
   - Revision Plan
   - Mock Test Schedule
   - Weakness Analysis (paste your latest mock score)
   - Motivation
4. Use the **chat box** for ongoing updates like:
   - "I missed yesterday's OS session"
   - "I completed DBMS"
   - "My exam got postponed to 15 October"
   The AI remembers the conversation and adjusts the plan instead of
   starting over — this is the multi-turn behavior.

## Swapping in a different model

`app.py` sets:
```python
MODEL = "claude-sonnet-4-6"
```
Change this string if you want to point at a different Claude model.

## Notes on the code

- **Personalized planning** happens in `prompts.py` → `STUDY_PLAN_PROMPT` /
  `MASTER_PROMPT`, which are filled with the student's own data before
  being sent to the model.
- **Multi-turn conversations** are handled by keeping a per-session
  `history` list in `SESSIONS` (in `app.py`) and passing it back into
  every `call_claude()` request, so the model has full context.
- **Prompt engineering** is centralized in `prompts.py` so each task
  (plan, daily task, revision, mock test, weakness, motivation, chat)
  has its own focused, single-purpose prompt rather than one giant prompt.

## Production notes

- `SESSIONS` is in-memory and will reset if the server restarts — swap
  it for a real database (SQLite, Postgres, Redis) for production use.
- Add authentication if deploying for multiple real users.
