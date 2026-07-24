Render Deployment Guide for SmartPrep AI

1. Push code to GitHub (repo: suseelamaddula-gif/<your-repo-name>)

2. In Render:
   - New -> Web Service
   - Connect to GitHub and select repository
   - Environment: Python
   - Branch: main (or your deploy branch)
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app
   - Set the following Environment Variables in Render dashboard (copy from .env.example):
     - GROQ_API_KEY
     - AI_MODEL (optional)
     - YOUTUBE_API_KEY (optional)
     - FLASK_SECRET_KEY
     - PORT (Render sets this automatically; no need to set)
     - FLASK_DEBUG=false

3. Deploy and monitor logs. The application will start using Gunicorn and serve the Flask app.

Notes:
- The app uses server-side session storage in-memory. For production, consider configuring a persistent DB.
- If the Groq API key is not set or the AI fails, the app falls back to a deterministic planner so UI remains functional.
