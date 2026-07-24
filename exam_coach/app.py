import os
import uuid
import urllib.request
import urllib.parse
import json
import re
import logging
from datetime import datetime, timedelta

from flask import Flask, request, jsonify, session, render_template, Response, stream_with_context
from dotenv import load_dotenv
import prompts
from ai_service import AIService
from rag_service import RAGService

load_dotenv()

# Use absolute paths for template and static folders to avoid TemplateNotFound
# on case-sensitive filesystems or when the app is imported from another cwd.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_FOLDER = os.path.join(BASE_DIR, "templates")
STATIC_FOLDER = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    static_folder=STATIC_FOLDER,
    template_folder=TEMPLATE_FOLDER,
)
# Configure basic logging early so we can log template/static checks
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Log template/static locations and verify index.html presence early
logger.info("Flask BASE_DIR=%s", BASE_DIR)
logger.info("Template folder: %s", TEMPLATE_FOLDER)
logger.info("Static folder: %s", STATIC_FOLDER)
try:
    if not os.path.isdir(TEMPLATE_FOLDER):
        logger.error("Template folder not found: %s", TEMPLATE_FOLDER)
    else:
        files = os.listdir(TEMPLATE_FOLDER)
        logger.debug("Templates present: %s", files[:20])
        if 'index.html' not in files:
            logger.error("index.html not found in templates folder: %s", TEMPLATE_FOLDER)
except Exception as e:
    logger.exception("Error checking template folder: %s", e)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# Initialize modular AI and RAG services
ai_service = AIService()
rag_service = RAGService(ai_service)

def is_ai_configured():
    return ai_service.is_configured()

MODEL = ai_service.get_status().get("model", "None")

# YouTube helper functions and in-memory cache
YOUTUBE_CACHE = {}
TRUSTED_CHANNELS = [
    "Khan Academy",
    "freeCodeCamp.org",
    "Neso Academy",
    "Gate Smashers",
    "Apna College",
    "Physics Wallah",
    "MIT OpenCourseWare",
    "CrashCourse",
    "Unacademy",
    "CodeWithHarry",
    "Jenny's Lectures CS/IT"
]

def parse_iso_duration(duration_str):
    hours = re.search(r'(\d+)H', duration_str)
    minutes = re.search(r'(\d+)M', duration_str)
    seconds = re.search(r'(\d+)S', duration_str)
    
    h = int(hours.group(1)) if hours else 0
    m = int(minutes.group(1)) if minutes else 0
    s = int(seconds.group(1)) if seconds else 0
    
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    elif m > 0 or s > 0:
        return f"{m}:{s:02d}"
    return "0:00"

def get_youtube_fallback(query):
    fallback_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query + ' educational')}"
    fallbacks = []
    channels_sample = [
        {"name": "Khan Academy", "desc": "Free online courses, lessons and practice."},
        {"name": "freeCodeCamp.org", "desc": "Learn to code for free with step-by-step tutorials."},
        {"name": "Neso Academy", "desc": "Excellent engineering and computer science lectures."}
    ]
    for i, ch in enumerate(channels_sample):
        fallbacks.append({
            "id": f"fallback_{i}_{str(uuid.uuid4())[:8]}",
            "title": f"Search for '{query}' on {ch['name']}",
            "channel_name": ch["name"],
            "description": f"{ch['desc']} Click below to search for this topic directly on YouTube.",
            "published_at": "Today",
            "url": fallback_url,
            "thumbnail": "", # Display client-side icon placeholder
            "duration": "Search",
            "views": "YouTube Link",
            "is_fallback": True,
            "fallback_search_url": fallback_url
        })
    return fallbacks

def search_youtube_videos(query):
    query = query.strip()
    if not query:
        return []
    
    if query in YOUTUBE_CACHE:
        return YOUTUBE_CACHE[query]
    
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        return get_youtube_fallback(query)
    
    try:
        search_query = f"{query} educational"
        encoded_query = urllib.parse.quote(search_query)
        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={encoded_query}&type=video&maxResults=10&key={api_key}"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            
        items = data.get("items", [])
        videos = []
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            if not video_id:
                continue
            snippet = item.get("snippet", {})
            title = snippet.get("title")
            channel_name = snippet.get("channelTitle")
            description = snippet.get("description")
            published_at = snippet.get("publishedAt", "")
            
            videos.append({
                "id": video_id,
                "title": title,
                "channel_name": channel_name,
                "description": description,
                "published_at": published_at.split("T")[0] if published_at else "",
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url") or snippet.get("thumbnails", {}).get("default", {}).get("url"),
                "duration": "10:00",
                "views": "1K+ views"
            })
            
        # Prioritize trusted channels
        def get_priority(v):
            c_lower = v["channel_name"].lower()
            for idx, tc in enumerate(TRUSTED_CHANNELS):
                if tc.lower() in c_lower:
                    return idx
            return 999
            
        videos.sort(key=get_priority)
        
        # Batch detail lookup for duration and viewCount
        if videos:
            try:
                ids = ",".join([v["id"] for v in videos[:5]])
                details_url = f"https://www.googleapis.com/youtube/v3/videos?part=contentDetails,statistics&id={ids}&key={api_key}"
                req_details = urllib.request.Request(details_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_details) as resp_details:
                    details_data = json.loads(resp_details.read().decode())
                
                details_map = {}
                for d_item in details_data.get("items", []):
                    d_id = d_item.get("id")
                    stats = d_item.get("statistics", {})
                    content = d_item.get("contentDetails", {})
                    
                    duration = parse_iso_duration(content.get("duration", "PT10M"))
                    views_count = int(stats.get("viewCount", 0))
                    if views_count > 1000000:
                        views = f"{views_count/1000000:.1f}M views"
                    elif views_count > 1000:
                        views = f"{views_count/1000:.0f}K views"
                    else:
                        views = f"{views_count} views"
                        
                    details_map[d_id] = {"duration": duration, "views": views}
                
                for v in videos:
                    if v["id"] in details_map:
                        v["duration"] = details_map[v["id"]]["duration"]
                        v["views"] = details_map[v["id"]]["views"]
            except Exception as details_err:
                print("Error details lookup:", details_err)
                
        final_videos = videos[:5]
        YOUTUBE_CACHE[query] = final_videos
        return final_videos
    except Exception as e:
        print("YouTube API error:", e)
        return get_youtube_fallback(query)

def clean_json_response(text):
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# Simple in-memory store: {session_id: {"history": [...], "student": {...}}}
# For production, replace with a real database (SQLite/Postgres/Redis).
SESSIONS = {}


def get_session():
    if "sid" not in session:
        session["sid"] = str(uuid.uuid4())
    sid = session["sid"]
    if sid not in SESSIONS:
        SESSIONS[sid] = {"history": [], "student": {}, "documents": {}}
    elif "documents" not in SESSIONS[sid]:
        SESSIONS[sid]["documents"] = {}
    return SESSIONS[sid]


@app.before_request
def log_request_info():
    logger.info("Incoming %s %s from %s", request.method, request.path, request.remote_addr)
    try:
        logger.debug("Request JSON: %s", request.get_json(silent=True))
    except Exception:
        pass


def call_openai(system_prompt, user_prompt, history=None):
    return ai_service.generate_text(system_prompt, user_prompt, history=history)


def generate_fallback_markdown_plan(student):
    subjects_text = student.get("subjects", "") or "General Studies"
    topics = [t.strip() for t in subjects_text.split(',') if t.strip()]
    if not topics:
        topics = ["General Revision"]
    
    try:
        today = datetime.utcnow().date()
        exam_date = datetime.strptime(student.get("exam_date"), "%Y-%m-%d").date() if student.get("exam_date") else today + timedelta(days=14)
        duration_days = max(1, (exam_date - today).days)
    except Exception:
        duration_days = 14
        today = datetime.utcnow().date()
        
    markdown = "### Offline Study Schedule (Demo Mode)\n\n"
    markdown += "| Date | Time Slot | Subject/Topic | Task Type | Notes |\n"
    markdown += "| --- | --- | --- | --- | --- |\n"
    
    topic_idx = 0
    for d in range(1, duration_days + 1):
        date_str = (today + timedelta(days=d-1)).strftime("%Y-%m-%d")
        topic = topics[topic_idx % len(topics)]
        
        is_revision = (d % 7 == 0) or (d > duration_days - 2)
        is_mock = (d % 7 == 6)
        
        if is_revision:
            markdown += f"| {date_str} | 09:00 AM - 11:00 AM | {topic} | Revision | Review formula sheets, flashcards, and summary notes |\n"
            markdown += f"| {date_str} | 02:00 PM - 04:00 PM | {topic} | Practice | Solve past papers and review weekly error log |\n"
        elif is_mock:
            markdown += f"| {date_str} | 09:00 AM - 12:00 PM | {topic} | Mock Test | Attempt full-length practice exam under timed conditions |\n"
            markdown += f"| {date_str} | 03:00 PM - 05:00 PM | {topic} | Review | Assess mock results and perform deep review of mistakes |\n"
        else:
            markdown += f"| {date_str} | 09:00 AM - 11:00 AM | {topic} | Study | Study primary concepts, definitions, and theories for {topic} |\n"
            markdown += f"| {date_str} | 02:00 PM - 04:00 PM | {topic} | Practice | Work on practice questions and textbook exercises |\n"
        topic_idx += 1
        
    markdown += "\n\n*Note: Running in local offline mode. Add a valid GROQ_API_KEY to your `.env` file for personalized AI plan generation.*"
    return markdown


def generate_fallback_master_plan(student):
    name = student.get("name", "Student")
    exam_name = student.get("exam_name", "Exam")
    subjects = student.get("subjects", "Syllabus")
    strong = student.get("strong_subjects", "")
    weak = student.get("weak_subjects", "")
    
    plan = f"# Master Preparation Strategy for {exam_name}\n\n"
    plan += f"Hello **{name}**! Here is your custom strategic road map for your upcoming exam.\n\n"
    
    plan += "### 🎯 Core Focus Areas\n"
    if weak:
        plan += f"- **High Priority (Weak Subjects)**: Devote 60% of your time to **{weak}**. Focus on foundational concepts first and do active recall.\n"
    if strong:
        plan += f"- **Maintenance (Strong Subjects)**: Allocate 20% of your time to **{strong}** to keep your skills sharp through quick quizzes.\n"
    plan += f"- **Syllabus Coverage**: Ensure all topics in **{subjects}** are scheduled and tracked on your dashboard.\n\n"
    
    plan += "### 📅 Weekly Prep Routine\n"
    plan += "1. **Monday - Friday (Core Study)**: Study main concepts in blocks of 45 minutes with 10-minute breaks.\n"
    plan += "2. **Saturday (Simulated Testing)**: Take mock tests to practice pacing, timing, and stamina.\n"
    plan += "3. **Sunday (Revision & Diagnostics)**: Fill knowledge gaps and update your formula sheets.\n\n"
    
    plan += "### 💡 Key Recommendations\n"
    plan += "- **Spaced Repetition**: Revisit difficult topics 1 day, 3 days, and 7 days after studying them.\n"
    plan += "- **Active Recall**: Test yourself with closed books instead of just highlighting/rereading.\n"
    plan += "- **Well-being**: Get 7-8 hours of sleep, as sleep is crucial for memory consolidation.\n\n"
    plan += "*Note: Running in local offline mode. Add a valid GROQ_API_KEY to your `.env` file to generate a full strategy using LLaMA 3.3.*"
    return plan


def generate_fallback_daily_task(data):
    today = data.get("today", "Today")
    remaining_days = data.get("remaining_days", "14")
    remaining_subjects = data.get("remaining_subjects", "Syllabus")
    study_hours = data.get("study_hours", "4")
    
    task = f"### Daily Checklist for {today} ({remaining_days} Days to Exam)\n\n"
    task += f"**Syllabus Target**: {remaining_subjects}\n"
    task += f"**Target Duration**: {study_hours} hours\n\n"
    
    task += "#### ⏰ Recommended Time Slots\n"
    task += "- **Morning Session (2 Hours)**: Review core formulas and theoretical foundations.\n"
    task += "- **Afternoon Session (2 Hours)**: Solve practice questions and complete diagnostic exercises.\n\n"
    
    task += "#### 🔄 Daily Revision Item\n"
    task += "- Review yesterday's study notes for 15 minutes before starting new topics.\n\n"
    
    task += "#### 📝 Practice Problems\n"
    task += "1. Write down a 3-sentence summary of the main concept in your syllabus target.\n"
    task += "2. Solve at least 3 practice questions related to the core topic.\n\n"
    
    task += "#### 📅 Homework for Tomorrow\n"
    task += "- Preview next subtopic outline and list 3 key terms you need to master.\n\n"
    task += "*Note: Local offline mode.*"
    return task


def generate_fallback_revision(student):
    subjects = student.get("subjects", "Syllabus")
    weak = student.get("weak_subjects", "")
    
    rev = "### Offline Revision Plan\n\n"
    rev += "#### 🗓️ Sunday Revision Routine\n"
    rev += "| Time Slot | Activity | Focus Area |\n"
    rev += "| --- | --- | --- |\n"
    if weak:
        rev += f"| 09:00 AM - 11:00 AM | Weak Area Review | Focus on core fundamentals of **{weak}** |\n"
    rev += f"| 11:30 AM - 01:00 PM | Active Recall | Flashcards and self-testing on **{subjects}** |\n"
    rev += "| 03:00 PM - 05:00 PM | Error Analysis | Re-attempt problems missed during weekly practice |\n\n"
    rev += "#### 🧠 Top Revision Methods\n"
    rev += "- **Feynman Technique**: Explain complex ideas out loud to a blank wall as if teaching a child.\n"
    rev += "- **Spaced Intervals**: Do a quick 10-minute review of weekly concepts every 3 days.\n"
    return rev


def generate_fallback_mock_test_schedule(student):
    subjects = student.get("subjects", "Syllabus")
    
    sch = "### Mock Test Practice Schedule\n\n"
    sch += "#### 📅 Practice Milestones\n"
    sch += f"1. **Baseline Test**: 1-hour diagnostic quiz covering core **{subjects}** concepts.\n"
    sch += "2. **Progress Check**: 2-hour open-book mock test halfway through preparation.\n"
    sch += "3. **Exam Simulation**: Full-length test under actual exam rules (timed, no references) 3 days before the exam.\n\n"
    sch += "#### 📈 Post-Test Review Protocol\n"
    sch += "- Do not just look at the score. Spend double the test duration reviewing correct/incorrect answers.\n"
    sch += "- Document errors in an Error Log, categorizing them into: Calculation, Concept, or Time Pressure errors.\n"
    return sch


def generate_fallback_weakness_analysis(student, score):
    weak = student.get("weak_subjects", "") or "Syllabus Topics"
    
    an = "### Performance Analysis & Action Items\n\n"
    an += f"**Diagnostic Score**: {score}%\n\n"
    an += "#### 🔍 Target Weak Areas\n"
    an += f"- High priority improvement required in: **{weak}**.\n"
    an += "- Focus on fundamental conceptual building blocks before solving advanced exercises.\n\n"
    an += "#### 🛠️ Recommended Action Items\n"
    an += f"1. **Concept Mapping**: Draw out a mind map showing relationships between subtopics of **{weak}**.\n"
    an += "2. **Graded Practice**: Solve 5 easy questions, then 5 medium, then 2 hard questions daily.\n"
    an += "3. **Feedback Loop**: Self-assess using model answers and identify precise gap points.\n"
    return an


def generate_fallback_motivation(name):
    import random
    quotes = [
        "Success is not final, failure is not fatal: it is the courage to continue that counts. — Winston Churchill",
        "Believe you can and you're halfway there. — Theodore Roosevelt",
        "The secret of getting ahead is getting started. — Mark Twain",
        "It always seems impossible until it's done. — Nelson Mandela",
        "Our greatest weakness lies in giving up. The most certain way to succeed is always to try just one more time. — Thomas A. Edison",
        "Work hard in silence, let your success be your noise. — Frank Ocean"
    ]
    return f"Hey {name}, here is a thought to power your study session today:\n\n> \"{random.choice(quotes)}\"\n\nKeep pushing, stay consistent, and take it one session at a time! 🚀"


def generate_fallback_chat_reply(message, student):
    msg_lower = message.lower()
    name = student.get("name", "Student")
    subjects = student.get("subjects", "your subjects")
    
    if any(g in msg_lower for g in ["hello", "hi", "hey", "greetings"]):
        return f"Hello {name}! I am your offline study coach assistant. How can I help you prepare for your exam on **{subjects}** today? (Note: I am running in Offline Demo Mode, but I can still guide you!)"
    elif any(p in msg_lower for p in ["schedule", "plan", "calendar", "timetable"]):
        return f"Your study planner has been configured for **{subjects}**. You can view your study calendar or download the markdown version directly from the Study Planner tab!"
    elif any(w in msg_lower for w in ["weak", "difficult", "hard", "struggle", "fail"]):
        return "Struggling with difficult topics is normal! I recommend: 1. Allocating double study hours for them, 2. Breaking the concept down into 5-minute flashcards, 3. Testing yourself with low-stakes mock quizzes."
    elif "exam" in msg_lower or "date" in msg_lower:
        exam_date = student.get("exam_date", "not set yet")
        exam_name = student.get("exam_name", "your exam")
        return f"You are preparing for **{exam_name}** on **{exam_date}**. Try to cover at least one topic every couple of days and leave the last 2 days for review."
    else:
        return f"Thanks for your message, {name}! To best prepare for your exam on **{subjects}**, I recommend sticking to your daily checklist, practicing active recall, and taking regular study breaks. Let me know if you have specific questions about scheduling, revision, or flashcards!"


def generate_fallback_quiz(subject, topic, difficulty, num_questions):
    questions = []
    for i in range(1, int(num_questions) + 1):
        questions.append({
            "id": i,
            "type": "mcq" if i % 2 == 1 else "short",
            "question": f"Explain the core concept #{i} of {topic} in the context of {subject} ({difficulty} level)?",
            "options": [
                f"Option A: Primary mechanism of {topic}",
                f"Option B: Secondary effect of {topic}",
                f"Option C: Auxiliary function of {topic}",
                f"Option D: None of the above"
            ] if i % 2 == 1 else [],
            "correct_answer": "Option A" if i % 2 == 1 else f"This requires explaining the primary mechanism, secondary effects, and key applications of {topic} within {subject}."
        })
    return questions


def evaluate_fallback_answers(questions, answers):
    total = len(questions)
    correct_count = 0
    
    for q in questions:
        q_id = str(q["id"])
        student_ans = answers.get(q_id, "")
        
        score_awarded = 0.0
        if q["type"] == "mcq":
            if student_ans.strip().lower() == q["correct_answer"].strip().lower():
                score_awarded = 1.0
        else:
            if len(student_ans.strip()) > 15:
                score_awarded = 0.8
            elif len(student_ans.strip()) > 5:
                score_awarded = 0.5
                
        correct_count += score_awarded
        
    accuracy = (correct_count / total * 100) if total > 0 else 0.0
    
    return {
        "score": round(correct_count, 1),
        "total_questions": total,
        "accuracy": round(accuracy, 1),
        "topic_performance": [
            {
                "topic": "Mock Test Topic",
                "score": round(correct_count, 1),
                "total": total
            }
        ],
        "weak_areas": ["In-depth analysis of high-yield concepts"],
        "improvements": ["Review your active recall cards.", "Practice timed quizzes weekly."]
    }


def generate_fallback_flashcards(topic, notes):
    return [
        {
            "question": f"What is the fundamental concept of {topic}?",
            "answer": f"The fundamental concept involves the core theories and basic definitions discussed in the syllabus for {topic}.",
            "key_points": [
                "Essential definition",
                "Primary use-case",
                "Common misconceptions"
            ],
            "mnemonic": f"Remember C-P-U: Core, Primary, Use-case for {topic}!"
        },
        {
            "question": f"Why is {topic} important in study planning?",
            "answer": f"It helps organize study materials and allocate time efficiently to prioritize weak topics.",
            "key_points": [
                "Time management",
                "Prioritization",
                "Systematic review"
            ],
            "mnemonic": "P-T-R: Plan, Track, Review!"
        }
    ]


@app.route("/")
def index():
    return render_template("index.html")


# Serve favicon from static to avoid browser 404s
@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


@app.errorhandler(404)
def handle_404(err):
    # For API routes, return a JSON 404 to preserve API behavior
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Not found'}), 404
    # For non-API routes (SPA), serve index so client-side routing works
    try:
        return render_template('index.html'), 200
    except Exception:
        return "Not Found", 404


@app.errorhandler(500)
def handle_500(err):
    logger.exception('Unhandled exception: %s', err)
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal Server Error'}), 500
    # Render a minimal error page without changing existing UI
    try:
        return render_template('index.html'), 500
    except Exception:
        return "Internal Server Error", 500


@app.route("/api/reset", methods=["POST"])
def reset():
    sid = session.pop("sid", None)
    if sid in SESSIONS:
        del SESSIONS[sid]
    return jsonify({"status": "reset"})


# ---------- STEP 2: Collect student info ----------
@app.route("/api/collect", methods=["POST"])
def collect_info():
    data = request.json or {}
    s = get_session()
    s["student"] = {
        "name": data.get("name", "Student"),
        "exam_name": data.get("exam_name", ""),
        "exam_date": data.get("exam_date", ""),
        "subjects": data.get("subjects", ""),
        "strong_subjects": data.get("strong_subjects", ""),
        "weak_subjects": data.get("weak_subjects", ""),
        "study_hours": data.get("study_hours", ""),
        "preferred_time": data.get("preferred_time", ""),
        "completed": data.get("completed", "None"),
    }
    return jsonify({"status": "saved", "student": s["student"]})


# ---------- STEP 3: Generate personalized study plan ----------
@app.route("/api/generate_plan", methods=["POST"])
def generate_plan():
    try:
        s = get_session()
        if not s["student"]:
            return jsonify({"error": "Please submit student details first"}), 400
        user_prompt = prompts.STUDY_PLAN_PROMPT.format(**s["student"])
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_markdown_plan(s["student"])
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"plan": reply})
    except Exception as e:
        logger.exception('generate_plan error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 4: Today's task ----------
@app.route("/api/daily_task", methods=["POST"])
def daily_task():
    try:
        data = request.json or {}
        s = get_session()
        user_prompt = prompts.DAILY_TASK_PROMPT.format(
            today=data.get("today", ""),    
            remaining_days=data.get("remaining_days", ""),
            remaining_subjects=data.get("remaining_subjects", ""),
            study_hours=data.get("study_hours", s["student"].get("study_hours", "")),
        )
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt, s["history"])
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_daily_task(data)
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"task": reply})
    except Exception as e:
        logger.exception('daily_task error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 5: Revision schedule ----------
@app.route("/api/revision", methods=["POST"])
def revision():
    try:
        s = get_session()
        student = s["student"]
        user_prompt = prompts.REVISION_PROMPT.format(
            subjects=student.get("subjects", ""),
            weak_subjects=student.get("weak_subjects", ""),
            exam_date=student.get("exam_date", ""),
        )
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt, s["history"])
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_revision(student)
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"revision": reply})
    except Exception as e:
        logger.exception('revision error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 6: Mock test schedule ----------
@app.route("/api/mock_test", methods=["POST"])
def mock_test():
    try:
        s = get_session()
        student = s["student"]
        user_prompt = prompts.MOCK_TEST_PROMPT.format(
            subjects=student.get("subjects", ""),
            exam_date=student.get("exam_date", ""),
        )
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt, s["history"])
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_mock_test_schedule(student)
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"mock_test": reply})
    except Exception as e:
        logger.exception('mock_test error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 7: Weakness analysis ----------
@app.route("/api/weakness", methods=["POST"])
def weakness():
    try:
        data = request.json or {}
        s = get_session()
        user_prompt = prompts.WEAKNESS_PROMPT.format(
            weak_subjects=s["student"].get("weak_subjects", ""),
            score=data.get("score", ""),
        )
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt, s["history"])
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_weakness_analysis(s["student"], data.get("score"))
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"analysis": reply})
    except Exception as e:
        logger.exception('weakness error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 8: Motivation ----------
@app.route("/api/motivation", methods=["POST"])
def motivation():
    try:
        data = request.json or {}
        s = get_session()
        user_prompt = prompts.MOTIVATION_PROMPT.format(
            name=s["student"].get("name", "Student"),
            progress=data.get("progress", ""),
        )
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_motivation(s["student"].get("name", "Student"))
        return jsonify({"message": reply})
    except Exception as e:
        logger.exception('motivation error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- STEP 9: Free-form multi-turn chat ----------
@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        data = request.json or {}
        message = data.get("message", "")
        stream_requested = data.get("stream", False)
        lang = data.get("language", "English")
        
        s = get_session()
        
        # Check active session documents for RAG context
        docs = s.get("documents", {})
        context_str = ""
        if docs:
            matches = rag_service.search_similar_chunks(message, docs, top_k=3)
            if matches:
                context_str = "\n\n[RELEVANT ACADEMIC DOCUMENT CONTEXT]:\n" + "\n---\n".join([m["text"] for m in matches])
        
        user_prompt = message
        if context_str:
            user_prompt = f"{message}\n\nUse the following reference context to help answer the student's question:\n{context_str}"
            
        system_prompt = prompts.MULTITURN_SYSTEM_PROMPT
        if lang and lang != "English":
            system_prompt += f"\n- Translate your entire response into {lang}."
            
        if stream_requested:
            def generate():
                full_reply = ""
                # Stream the AI response text
                for chunk in ai_service.generate_stream(system_prompt, user_prompt, s["history"]):
                    full_reply += chunk
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                
                # Append user & assistant messages to session history
                s["history"].append({"role": "user", "content": message})
                s["history"].append({"role": "assistant", "content": full_reply})
                
                # Extract educational keywords for video lookup
                try:
                    kw_prompt = f"Extract a 2-3 word academic/educational search term for the main topic discussed in this message: '{message}'. Output ONLY the search query words, nothing else."
                    extracted = ai_service.generate_text("You are a query extractor helper.", kw_prompt).strip()
                    extracted = extracted.replace('"', '').replace("'", "")
                    if not extracted or len(extracted) > 50 or "[AI_" in extracted:
                        extracted = message[:30]
                except Exception:
                    extracted = message[:30]
                
                videos = search_youtube_videos(extracted)
                yield f"data: {json.dumps({'videos': videos})}\n\n"
                yield "data: [DONE]\n\n"

            return Response(stream_with_context(generate()), mimetype="text/event-stream")
            
        else:
            # Non-streaming flow
            reply = ai_service.generate_text(system_prompt, user_prompt, s["history"])
            is_fallback = False
            if isinstance(reply, str) and reply.startswith("[AI_"):
                is_fallback = True
                reply = generate_fallback_chat_reply(message, s["student"])
                
            s["history"].append({"role": "user", "content": message})
            s["history"].append({"role": "assistant", "content": reply})
            
            try:
                if is_fallback:
                    raise Exception("AI unavailable")
                kw_prompt = f"Extract a 2-3 word academic/educational search term for the main topic discussed in this message: '{message}'. Output ONLY the search query words, nothing else."
                extracted = ai_service.generate_text("You are a query extractor helper.", kw_prompt).strip()
                extracted = extracted.replace('"', '').replace("'", "")
                if not extracted or len(extracted) > 50 or "[AI_" in extracted:
                    extracted = message[:30]
            except Exception:
                extracted = message[:30]
                
            videos = search_youtube_videos(extracted)
            return jsonify({"reply": reply, "videos": videos})
    except Exception as e:
        logger.exception("Error in chat route")
        return jsonify({"error": str(e)}), 503


# ---------- STEP 10: One-shot master plan ----------
@app.route("/api/master_plan", methods=["POST"])
def master_plan():
    try:
        data = request.json or {}
        s = get_session()
        s["student"] = {
            "name": data.get("name", "Student"),
            "exam_name": data.get("exam_name", ""),
            "exam_date": data.get("exam_date", ""),
            "subjects": data.get("subjects", ""),
            "strong_subjects": data.get("strong_subjects", ""),
            "weak_subjects": data.get("weak_subjects", ""),
            "study_hours": data.get("study_hours", ""),
            "preferred_time": data.get("preferred_time", ""),
            "completed": data.get("completed", "None"),
        }
        user_prompt = prompts.MASTER_PROMPT.format(**s["student"])
        reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(reply, str) and reply.startswith("[AI_"):
            reply = generate_fallback_master_plan(s["student"])
        s["history"].append({"role": "user", "content": user_prompt})
        s["history"].append({"role": "assistant", "content": reply})
        return jsonify({"plan": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 503


# ---------- NEW ENHANCEMENTS ROUTES ----------

@app.route("/api/videos/search", methods=["GET", "POST"])
def api_videos_search():
    try:
        if request.method == "POST":
            data = request.json or {}
            query = data.get("query", "")
        else:
            query = request.args.get("query", "")
            
        if not query:
            return jsonify({"error": "Query parameter is required"}), 400
            
        videos = search_youtube_videos(query)
        return jsonify({"videos": videos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/get_saved_plan', methods=['GET'])
def get_saved_plan():
    try:
        s = get_session()
        plan = s.get('study_plan')
        if not plan:
            return jsonify({'error': 'No saved plan found'}), 404
        return jsonify(plan)
    except Exception as e:
        logger.exception('Error fetching saved plan: %s', e)
        return jsonify({'error': str(e)}), 503


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify(ai_service.get_status())


@app.route("/api/generate_plan_json", methods=["POST"])
def generate_plan_json():
    try:
        s = get_session()
        data = request.json or {}
        if data.get("exam_name"):
            s["student"] = {
                "name": data.get("name", "Student"),
                "exam_name": data.get("exam_name", ""),
                "exam_date": data.get("exam_date", ""),
                "subjects": data.get("subjects", ""),
                "strong_subjects": data.get("strong_subjects", ""),
                "weak_subjects": data.get("weak_subjects", ""),
                "study_hours": data.get("study_hours", ""),
                "preferred_time": data.get("preferred_time", ""),
                "completed": data.get("completed", "None"),
            }
        
        if not s["student"]:
            return jsonify({"error": "Please submit student details first"}), 400
        # Build prompt and attempt AI generation
        user_prompt = prompts.STUDY_PLAN_JSON_PROMPT.format(**s["student"])
        try:
            raw_reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
            if isinstance(raw_reply, str) and raw_reply.startswith("[AI_"):
                raise json.JSONDecodeError("AI unavailable", raw_reply, 0)
            reply = clean_json_response(raw_reply)
            plan_data = json.loads(reply)
            # Save generated plan in server-side session store
            s["study_plan"] = plan_data
            s["history"].append({"role": "user", "content": "Generate structured JSON study plan"})
            s["history"].append({"role": "assistant", "content": raw_reply})
            logger.info("Generated study plan saved to session for sid")
            return jsonify(plan_data)
        except Exception as e:
            logger.exception("AI plan generation failed, falling back to deterministic planner: %s", e)
            # Fallback: create a simple deterministic plan by splitting topics across days
            try:
                subjects_text = s["student"].get("subjects", "") or "General Studies"
                topics = [t.strip() for t in subjects_text.split(',') if t.strip()]
                if not topics:
                    topics = ["General Revision"]

                # Calculate days until exam (or use 14 days default)
                try:
                    today = datetime.utcnow().date()
                    exam_date = datetime.strptime(s["student"].get("exam_date"), "%Y-%m-%d").date() if s["student"].get("exam_date") else today + timedelta(days=14)
                    duration_days = max(1, (exam_date - today).days)
                except Exception:
                    duration_days = 14
                    today = datetime.utcnow().date()

                schedule = []
                topic_idx = 0
                for d in range(1, duration_days + 1):
                    date_str = (today + timedelta(days=d-1)).isoformat()
                    # simple allocation: one topic per day, with some time slots
                    topic = topics[topic_idx % len(topics)]
                    time_slots = [
                        {"time": "09:00 AM - 11:00 AM", "subject": topic, "topic": topic + " - Core", "task_type": "Study", "notes": "Read primary material and solve 3 questions.", "completed": False},
                        {"time": "02:00 PM - 04:00 PM", "subject": topic, "topic": topic + " - Practice", "task_type": "Study", "notes": "Practice problems and short quizzes.", "completed": False}
                    ]
                    is_revision = (d % 7 == 0) or (d > duration_days - 2)
                    is_mock = (d % 7 == 6)
                    schedule.append({"day_number": d, "date": date_str, "is_revision_day": is_revision, "is_mock_day": is_mock, "time_slots": time_slots})
                    topic_idx += 1

                plan_data = {
                    "plan_name": f"Study Plan for {s['student'].get('exam_name', 'Exam')}",
                    "duration_days": duration_days,
                    "schedule": schedule
                }
                s["study_plan"] = plan_data
                s["history"].append({"role": "assistant", "content": "Generated fallback deterministic plan"})
                return jsonify(plan_data)
            except Exception as e2:
                logger.exception("Fallback plan creation failed: %s", e2)
                return jsonify({"error": "Failed to generate a study plan."}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/mock_tests/generate", methods=["POST"])
def mock_tests_generate():
    try:
        data = request.json or {}
        subject = data.get("subject", "General")
        topic = data.get("topic", "All")
        difficulty = data.get("difficulty", "Medium")
        num_questions = data.get("num_questions", 5)
        
        s = get_session()
        docs = s.get("documents", {})
        context_str = ""
        if docs:
            # Query active documents for relevance to subject/topic to inject context
            matches = rag_service.search_similar_chunks(f"{subject} {topic}", docs, top_k=5)
            if matches:
                context_str = "\n\nReference Material for generating questions:\n" + "\n---\n".join([m["text"] for m in matches])
        
        user_prompt = prompts.MOCK_TEST_GENERATOR_PROMPT.format(
            subject=subject,
            topic=topic,
            difficulty=difficulty,
            num_questions=num_questions
        )
        if context_str:
            user_prompt += f"\n\nUse the reference text below to generate the questions (make them highly relevant to the text content):\n{context_str}"
        
        raw_reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(raw_reply, str) and raw_reply.startswith("[AI_"):
            raise json.JSONDecodeError("AI unavailable", raw_reply, 0)
            
        reply = clean_json_response(raw_reply)
        
        try:
            quiz_data = json.loads(reply)
            return jsonify({"questions": quiz_data})
        except json.JSONDecodeError:
            quiz_data = generate_fallback_quiz(subject, topic, difficulty, num_questions)
            return jsonify({"questions": quiz_data})
    except Exception as e:
        logger.exception('mock_tests_generate error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


@app.route("/api/mock_tests/evaluate", methods=["POST"])
def mock_tests_evaluate():
    try:
        data = request.json or {}
        questions = data.get("questions", [])
        answers = data.get("answers", {})
        
        user_prompt = prompts.MOCK_TEST_EVALUATOR_PROMPT.format(
            questions_json=json.dumps(questions, indent=2),
            student_answers_json=json.dumps(answers, indent=2)
        )
        
        raw_reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(raw_reply, str) and raw_reply.startswith("[AI_"):
            raise json.JSONDecodeError("AI unavailable", raw_reply, 0)
            
        reply = clean_json_response(raw_reply)
        
        try:
            evaluation_data = json.loads(reply)
            return jsonify(evaluation_data)
        except json.JSONDecodeError:
            evaluation_data = evaluate_fallback_answers(questions, answers)
            return jsonify(evaluation_data)
    except Exception as e:
        logger.exception('mock_tests_evaluate error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


@app.route("/api/flashcards/generate", methods=["POST"])
def flashcards_generate():
    try:
        data = request.json or {}
        topic = data.get("topic", "General Study")
        notes = data.get("notes", "No specific notes provided.")
        
        s = get_session()
        docs = s.get("documents", {})
        # If user left notes blank but has documents, auto-enrich using RAG search
        if docs and (not notes or notes.strip() == "No specific notes provided." or len(notes.strip()) < 10):
            matches = rag_service.search_similar_chunks(topic, docs, top_k=5)
            if matches:
                notes = "\n---\n".join([m["text"] for m in matches])
        
        user_prompt = prompts.FLASHCARD_GENERATOR_PROMPT.format(
            topic=topic,
            notes=notes
        )
        
        raw_reply = call_openai(prompts.SYSTEM_PROMPT, user_prompt)
        if isinstance(raw_reply, str) and raw_reply.startswith("[AI_"):
            raise json.JSONDecodeError("AI unavailable", raw_reply, 0)
            
        reply = clean_json_response(raw_reply)
        
        try:
            flashcards = json.loads(reply)
            return jsonify({"flashcards": flashcards})
        except json.JSONDecodeError:
            flashcards = generate_fallback_flashcards(topic, notes)
            return jsonify({"flashcards": flashcards})
    except Exception as e:
        logger.exception('flashcards_generate error: %s', e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 503


# ---------- DOCUMENT LIBRARY & SEMANTIC SEARCH ROUTES ----------

@app.route("/api/documents/upload", methods=["POST"])
def api_documents_upload():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "Empty filename"}), 400
            
        s = get_session()
        # process and index the document using rag_service
        doc_data = rag_service.process_and_index_document(file.stream, file.filename)
        
        if not doc_data:
            return jsonify({"error": "Failed to process document or extract text"}), 500
            
        doc_id = doc_data["id"]
        # Save in-session document metadata and chunks
        s["documents"][doc_id] = {
            "id": doc_id,
            "filename": doc_data["filename"],
            "character_count": doc_data["character_count"],
            "chunks_count": len(doc_data["chunks"]),
            "chunks": doc_data["chunks"]
        }
        
        return jsonify({
            "status": "success",
            "document": {
                "id": doc_id,
                "filename": doc_data["filename"],
                "character_count": doc_data["character_count"],
                "chunks_count": len(doc_data["chunks"])
            }
        })
    except Exception as e:
        logger.exception("Document upload error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/documents/list", methods=["GET"])
def api_documents_list():
    try:
        s = get_session()
        docs = s.get("documents", {})
        res = []
        for d_id, d in docs.items():
            res.append({
                "id": d_id,
                "filename": d["filename"],
                "character_count": d["character_count"],
                "chunks_count": d["chunks_count"]
            })
        return jsonify({"documents": res})
    except Exception as e:
        logger.exception("Error listing documents: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/documents/delete/<doc_id>", methods=["DELETE"])
def api_documents_delete(doc_id):
    try:
        s = get_session()
        docs = s.get("documents", {})
        if doc_id in docs:
            filename = docs[doc_id]["filename"]
            del docs[doc_id]
            return jsonify({"status": "deleted", "filename": filename})
        return jsonify({"error": "Document not found"}), 404
    except Exception as e:
        logger.exception("Error deleting document: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/search/semantic", methods=["POST"])
def api_search_semantic():
    try:
        data = request.json or {}
        query = data.get("query", "")
        if not query:
            return jsonify({"error": "Query parameter is required"}), 400
            
        s = get_session()
        docs = s.get("documents", {})
        
        # Search relevant chunks
        matches = rag_service.search_similar_chunks(query, docs, top_k=5)
        return jsonify({"query": query, "results": matches})
    except Exception as e:
        logger.exception("Semantic search error: %s", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Use PORT from environment for compatibility with Render and other PaaS
    port = int(os.environ.get("PORT", 5000))
    debug_flag = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", debug=debug_flag, port=port)

