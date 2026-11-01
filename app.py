from datetime import datetime, timedelta
from typing import List, Optional
import random

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Smart Timetable Manager API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local development. Restrict this in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUGGESTIONS = [
    {"name": "Data Structures", "code": "CS501", "faculty": "Prof. Sharma",
     "hours_per_week": 4, "subject_type": "theory"},
    {"name": "Database Management", "code": "CS502", "faculty": "Prof. Patil",
     "hours_per_week": 3, "subject_type": "theory"},
    {"name": "Operating Systems", "code": "CS503", "faculty": "Prof. Deshmukh",
     "hours_per_week": 3, "subject_type": "theory"},
    {"name": "Computer Networks", "code": "CS504", "faculty": "Prof. Kulkarni",
     "hours_per_week": 3, "subject_type": "theory"},
    {"name": "Python Programming Lab", "code": "CS505L", "faculty": "Prof. Joshi",
     "hours_per_week": 2, "subject_type": "lab"},
    {"name": "Software Engineering", "code": "CS506", "faculty": "Prof. Mehta",
     "hours_per_week": 3, "subject_type": "theory"},
]

class Subject(BaseModel):
    name: str
    code: str
    faculty: str
    hours_per_week: int = Field(gt=0)
    subject_type: str = "theory"

class Section(BaseModel):
    section: str
    subjects: List[Subject]

class TimetableRequest(BaseModel):
    institution_name: str
    department: str
    academic_year: str
    days: List[str]
    periods_per_day: int = Field(gt=0, le=12)
    period_duration: int = Field(gt=0)
    start_time: str
    break_after_period: Optional[int] = 0
    break_duration: Optional[int] = 0
    lunch_after_period: Optional[int] = 0
    lunch_duration: Optional[int] = 0
    sections: List[Section]

def add_minutes(clock: str, minutes: int) -> str:
    t = datetime.strptime(clock, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")

def build_day_slots(req, assignments, day, section_name):
    slots = []
    elapsed = 0
    for period in range(1, req.periods_per_day + 1):
        start = add_minutes(req.start_time, elapsed)
        end = add_minutes(req.start_time, elapsed + req.period_duration)
        item = assignments.get((day, period))
        if item:
            slots.append({
                "period": period,
                "is_break": False,
                "is_lunch": False,
                "subject_name": item["name"],
                "subject_code": item["code"],
                "faculty": item["faculty"],
                "subject_type": item["subject_type"],
                "time_slot": f"{start} - {end}",
            })
        else:
            slots.append({
                "period": period,
                "is_break": False,
                "is_lunch": False,
                "subject_name": "Free",
                "subject_code": "",
                "faculty": "—",
                "subject_type": "free",
                "time_slot": f"{start} - {end}",
            })
        elapsed += req.period_duration

        if period == req.break_after_period and req.break_duration:
            bstart = add_minutes(req.start_time, elapsed)
            elapsed += req.break_duration
            bend = add_minutes(req.start_time, elapsed)
            slots.append({
                "period": period, "is_break": True, "is_lunch": False,
                "break_label": "Short Break", "time_slot": f"{bstart} - {bend}",
            })
        if period == req.lunch_after_period and req.lunch_duration:
            bstart = add_minutes(req.start_time, elapsed)
            elapsed += req.lunch_duration
            bend = add_minutes(req.start_time, elapsed)
            slots.append({
                "period": period, "is_break": False, "is_lunch": True,
                "break_label": "Lunch", "time_slot": f"{bstart} - {bend}",
            })
    return {"day": day, "slots": slots}

@app.get("/")
def home():
    return {"message": "Smart Timetable Manager API is running"}

@app.get("/subject-suggestions")
def subject_suggestions():
    return SUGGESTIONS

@app.post("/generate-department-timetable")
def generate_department_timetable(req: TimetableRequest):
    if not req.days:
        raise HTTPException(status_code=400, detail="Select at least one working day.")
    if not req.sections:
        raise HTTPException(status_code=400, detail="Add at least one section.")
    if not req.start_time:
        raise HTTPException(status_code=400, detail="Enter a valid start time.")

    capacity = len(req.days) * req.periods_per_day
    # One global occupancy map prevents the same faculty member being assigned
    # to two sections in the same day and period.
    faculty_busy = set()
    result_sections = []

    # Randomized attempts help spread classes across the week.
    for sec in req.sections:
        total = sum(s.hours_per_week for s in sec.subjects)
        if total > capacity:
            raise HTTPException(
                status_code=400,
                detail=f"{sec.section}: {total} weekly hours exceed the {capacity} available teaching slots."
            )

        assignments = {}
        tasks = []
        for subject in sec.subjects:
            if subject.subject_type == "lab":
                # Place lab hours as consecutive pairs where possible.
                pairs = subject.hours_per_week // 2
                for _ in range(pairs):
                    tasks.append((subject, 2))
                if subject.hours_per_week % 2:
                    tasks.append((subject, 1))
            else:
                for _ in range(subject.hours_per_week):
                    tasks.append((subject, 1))

        # Place labs first, then other subjects; shuffle day preference.
        tasks.sort(key=lambda x: 0 if x[1] == 2 else 1)
        random.shuffle(tasks)

        for subject, length in tasks:
            candidates = []
            for day in req.days:
                for start_period in range(1, req.periods_per_day - length + 2):
                    positions = [(day, p) for p in range(start_period, start_period + length)]
                    if any(pos in assignments for pos in positions):
                        continue
                    if any((subject.faculty.lower(), d, p) in faculty_busy for d, p in positions):
                        continue
                    candidates.append(positions)

            if not candidates:
                raise HTTPException(
                    status_code=409,
                    detail=f"Could not place all classes for {sec.section}. There may be faculty clashes or insufficient consecutive slots. Try different faculty assignments or adjust weekly hours."
                )

            positions = random.choice(candidates)
            for day, period in positions:
                assignments[(day, period)] = {
                    "name": subject.name,
                    "code": subject.code,
                    "faculty": subject.faculty,
                    "subject_type": subject.subject_type,
                }
                faculty_busy.add((subject.faculty.lower(), day, period))

        schedule = [build_day_slots(req, assignments, day, sec.section) for day in req.days]
        summary = {s.name: s.hours_per_week for s in sec.subjects}
        result_sections.append({
            "section": sec.section,
            "schedule": schedule,
            "summary": summary,
        })

    return {
        "institution_name": req.institution_name,
        "department": req.department,
        "academic_year": req.academic_year,
        "sections": result_sections,
    }
