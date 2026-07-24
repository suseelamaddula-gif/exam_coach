"""
All prompts used by the AI Exam Preparation Coach.
Each one maps to a step in the prompt-engineering flow:
System -> Collect Info -> Study Plan -> Daily Task -> Revision ->
Mock Test -> Weakness Analysis -> Motivation -> Multi-turn Chat.
"""

# ---------- STEP 1: SYSTEM PROMPT ----------
SYSTEM_PROMPT = """You are an AI Exam Preparation Coach.

Your responsibilities are:
1. Help students prepare for exams.
2. Create personalized study plans.
3. Analyze strengths and weaknesses.
4. Divide the syllabus into daily study tasks.
5. Suggest revision schedules.
6. Schedule mock tests.
7. Motivate students every day.
8. Ask follow-up questions whenever information is missing.
9. Adjust the study plan if the student misses a day.
10. Always give practical and realistic advice.

Rules:
- Keep the study plan achievable.
- Include short breaks.
- Include revision.
- Include mock tests.
- Prioritize weak subjects.
- Respond in simple English.
- Use markdown tables for schedules wherever possible.
"""

# ---------- STEP 2: COLLECT INFO (used client-side as a form, not sent to the model) ----------
INTAKE_QUESTIONS = [
    "Exam Name",
    "Exam Date",
    "Topics",
    "Strong Topics",
    "Weak Topics",
    "Daily Study Hours",
    "Preferred Study Time",
    "Have you completed any syllabus? (Yes/No, and what)",
    "Any holidays or unavailable days?",
]

# ---------- STEP 3: STUDY PLAN PROMPT ----------
STUDY_PLAN_PROMPT = """Using the student information below, create a personalized study plan.

Student Details
Exam Name: {exam_name}
Exam Date: {exam_date}
Topics: {subjects}
Strong Subjects: {strong_subjects}
Weak Subjects: {weak_subjects}
Daily Study Hours: {study_hours}
Preferred Study Time: {preferred_time}
Already Completed: {completed}

Instructions:
- Divide the topics into a day-by-day study plan until the exam date.
- Give a daily schedule with time slots based on the preferred study time.
- Allocate more time for weak subjects.
- Include revision every Sunday.
- Include one mock test every week.
- Suggest break timings.
- Reserve the last 2 days before the exam for revision only, no new topics.
- Give a short motivational tip at the end.

Present the output as a markdown table with columns:
Date | Time Slot | Subject/Topic | Task Type | Notes
"""

# ---------- STEP 4: DAILY TASK PROMPT ----------
DAILY_TASK_PROMPT = """Create today's study plan.

Current Day: {today}
Remaining Days Until Exam: {remaining_days}
Subjects/Topics Left: {remaining_subjects}
Study Hours Available Today: {study_hours}

Generate:
- Tasks with time slots
- A short revision item
- A few practice questions
- One piece of homework for tomorrow

Keep it realistic and consistent with the overall plan already discussed.
"""

# ---------- STEP 5: REVISION PROMPT ----------
REVISION_PROMPT = """Create a revision schedule.

Subjects: {subjects}
Weak Subjects: {weak_subjects}
Exam Date: {exam_date}

Instructions:
- Schedule revision every Sunday.
- Include short notes, flashcards, previous year questions, and important formulas.
- Give weak subjects more revision time than strong subjects.

Present as a table: Subject | Revision Activity | Time Needed
"""

# ---------- STEP 6: MOCK TEST PROMPT ----------
MOCK_TEST_PROMPT = """Generate a weekly mock test schedule.

Subjects: {subjects}
Exam Date: {exam_date}

Instructions:
- One mock test every Saturday.
- Specify duration, total marks, difficulty level, and topics covered.
- Increase difficulty gradually as the exam date approaches.

Present as a table: Date | Subjects Covered | Duration | Marks | Difficulty
"""

# ---------- STEP 7: WEAKNESS ANALYSIS PROMPT ----------
WEAKNESS_PROMPT = """Analyze the student's weak subjects based on their latest mock test result.

Weak Subjects: {weak_subjects}
Mock Test Score: {score}

Suggest:
- Specific topics needing improvement
- Additional study hours needed
- Practice questions to focus on
- A revision strategy for the next 7 days
"""

# ---------- STEP 8: MOTIVATION PROMPT ----------
MOTIVATION_PROMPT = """Generate a short motivational message for today's study session.

Student Name: {name}
Current Progress: {progress}

Keep it under 40 words. Be warm and encouraging, not generic.
"""

# ---------- STEP 9: MULTI-TURN CONVERSATION SYSTEM PROMPT ----------
MULTITURN_SYSTEM_PROMPT = """You are an AI Exam Coach continuing an ongoing conversation.
Remember everything discussed earlier in this session (the plan already given).

Rules:
- If the student says something like "I missed yesterday" -> update the existing
  plan (redistribute the missed work), do NOT create a brand-new plan from scratch.
- If the student says "I completed [subject/topic]" -> acknowledge it and mark it
  as done, adjusting only the remaining schedule.
- If the student says "My exam got postponed" or gives a new date -> recalculate
  the entire plan for the new timeline.
- Never ask the student for information they already provided earlier in this chat.
- Keep responses concise and action-oriented, with a small updated schedule table
  when relevant.
"""

# ---------- STEP 10: FINAL MASTER PROMPT (all-in-one, optional alternative to STUDY_PLAN_PROMPT) ----------
MASTER_PROMPT = """You are an AI Exam Preparation Coach.

Student Details
Exam Name: {exam_name}
Exam Date: {exam_date}
Topics: {subjects}
Strong Topics: {strong_subjects}
Weak Topics: {weak_subjects}
Daily Study Hours: {study_hours}
Preferred Study Time: {preferred_time}
Completed Topics: {completed}

Create a complete preparation strategy that includes:
1. Overall study timeline until the exam.
2. Daily study schedule with time slots.
3. Weekly study goals.
4. Revision plan.
5. Mock test schedule.
6. Priority for weak subjects.
7. Daily motivational message.
8. Tips for better concentration.
9. Progress tracking suggestions.
10. What to do if a study day is missed.

Present the output in a clear, organized format using markdown tables where helpful.
"""

# ---------- STEP 11: STUDY PLAN JSON PROMPT ----------
STUDY_PLAN_JSON_PROMPT = """Using the student information below, create a personalized study plan in JSON format.

Student Details:
Exam Name: {exam_name}
Exam Date: {exam_date}
Topics: {subjects}
Strong Subjects: {strong_subjects}
Weak Subjects: {weak_subjects}
Daily Study Hours: {study_hours}
Preferred Study Time: {preferred_time}
Already Completed: {completed}

Instructions:
1. Divide the topics into a day-by-day study plan until the exam date.
2. Give a daily schedule with time slots based on the preferred study time.
3. Allocate more time for weak subjects.
4. Include revision sessions (e.g., weekly or every Sunday).
5. Include mock test sessions.
6. Suggest break timings.
7. Reserve the last 2 days before the exam for revision only, no new topics.

Return ONLY a raw JSON object (do not wrap in markdown tags, do not add any text before or after). The JSON must match this structure exactly:
{{
  "plan_name": "Study Plan for {exam_name}",
  "duration_days": 30, // total days
  "schedule": [
    {{
      "day_number": 1,
      "date": "YYYY-MM-DD", // calculate actual dates starting from today or next day
      "is_revision_day": false,
      "is_mock_day": false,
      "time_slots": [
        {{
          "time": "e.g., 09:00 AM - 11:00 AM",
          "subject": "e.g., Operating Systems",
          "topic": "e.g., Processes & Threads",
          "task_type": "Study", // choose from: Study, Revision, Mock, Break
          "notes": "e.g., Read pages 45-60, practice scheduling algorithms."
        }}
      ]
    }}
  ]
}}
"""

# ---------- STEP 12: MOCK TEST GENERATOR PROMPT ----------
MOCK_TEST_GENERATOR_PROMPT = """Generate a high-quality mock test in JSON format based on the parameters below.

Subject: {subject}
Topic: {topic}
Difficulty: {difficulty}
Number of Questions: {num_questions}

Instructions:
1. Generate a mix of MCQs (multiple choice), Short Answer Questions, and Long Answer Questions.
2. Ensure the questions reflect the specified difficulty.
3. For MCQ questions, provide exactly 4 options.
4. For short and long answers, provide a robust model answer in `correct_answer`.

Return ONLY a raw JSON list of questions (do not wrap in markdown tags, do not add any text before or after). The JSON must match this structure exactly:
[
  {{
    "id": 1,
    "type": "mcq", // choose from: mcq, short, long
    "question": "The question text?",
    "options": ["Option A", "Option B", "Option C", "Option D"], // only include for mcq, otherwise omit or empty list
    "correct_answer": "Option A", // for mcq, the correct option text. For short/long, the model answer key points.
    "explanation": "Detailed explanation of why this answer is correct."
  }}
]
"""

# ---------- STEP 13: MOCK TEST EVALUATOR PROMPT ----------
MOCK_TEST_EVALUATOR_PROMPT = """Evaluate a student's answers for a mock test in JSON format.

Questions and Correct Answers:
{questions_json}

Student Answers:
{student_answers_json}

Instructions:
1. Score each question. For MCQs, check for exact matches. For short and long answers, evaluate the closeness of the student's text to the model answer, awarding a fractional score (0.0 to 1.0) based on accuracy.
2. Calculate overall score, accuracy, and performance by topic.
3. Identify weak areas and provide AI-generated suggestions for improvement.

Return ONLY a raw JSON object (do not wrap in markdown tags, do not add any text before or after). The JSON must match this structure exactly:
{{
  "score": 8.5, // total score out of total questions
  "total_questions": 10,
  "accuracy": 85.0, // percentage
  "topic_performance": [
    {{
      "topic": "Topic Name",
      "score": 3.0,
      "total": 4
    }}
  ],
  "weak_areas": ["e.g. Memory management in OS"],
  "improvements": ["e.g. Review paging & segmentation diagrams, practice more numericals"],
  "question_evaluations": [
    {{
      "id": 1,
      "is_correct": true, // true, false or partially_correct
      "student_answer": "Student's answer text",
      "correct_answer": "Model correct answer text",
      "score_awarded": 1.0, // float between 0.0 and 1.0
      "feedback": "Detailed explanation of grading, what was missing or correct."
    }}
  ]
}}
"""

# ---------- STEP 14: FLASHCARD GENERATOR PROMPT ----------
FLASHCARD_GENERATOR_PROMPT = """Generate a set of educational flashcards in JSON format.

Topic: {topic}
Notes / Text Content: {notes}

Instructions:
1. Create 5-10 detailed flashcards based on the topic and notes.
2. For each flashcard, define a clear question and answer.
3. Include key bullet points, formulas (where applicable), examples, and a fun/useful memory trick (mnemonic) to help remember the concept.

Return ONLY a raw JSON list of flashcards (do not wrap in markdown tags, do not add any text before or after). The JSON must match this structure exactly:
[
  {{
    "question": "What is the primary function of Paging in OS?",
    "answer": "Paging is a memory management scheme that eliminates the need for contiguous physical memory allocation by dividing virtual memory into pages and physical memory into frames.",
    "key_points": [
      "Avoids external fragmentation",
      "Enables sharing of common pages",
      "Uses a Page Table to translate virtual to physical addresses"
    ],
    "formula": "Physical Address = Frame Number * Page Size + Offset", // or null if not applicable
    "example": "If virtual address space is 4GB and page size is 4KB, there are 1M pages.",
    "memory_trick": "Paging: Like paging a friend to find their seat in a scattered theater instead of seating everyone in a row!"
  }}
]
"""

