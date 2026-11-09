"""AstroGuard AI - a self-contained, offline-first NASA Space Apps MVP.

Python 3.10+. Install: pip install "streamlit>=1.66,<2" "pandas>=2.2,<3" "plotly>=6,<7"
Run: streamlit run app.py

SQLite is created beside this file as astroguard.db; an existing v1 database is
kept and upgraded transactionally. Override its location with ASTROGUARD_DB.
New profiles are empty. Demo data and the simulated ground receiver are optional.
Assessment uses explainable rules, not a remote LLM or a validated medical model.
"""

from __future__ import annotations

import copy
import html
import json
import math
import os
import random
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit import config as streamlit_config


APP_NAME = "AstroGuard AI"
APP_DIRECTORY = Path(__file__).resolve().parent
LEGACY_DB_PATH = APP_DIRECTORY / "astroguard_data" / "astroguard.sqlite3"
DB_PATH = Path(os.environ["ASTROGUARD_DB"]) if os.environ.get("ASTROGUARD_DB") else (LEGACY_DB_PATH if LEGACY_DB_PATH.exists() else APP_DIRECTORY / "astroguard.db")
SEVERITIES = ("Monitor", "Treat onboard", "Contact ground", "Emergency evacuation")
SEVERITY_COLORS = ("#38bdf8", "#34d399", "#f59e0b", "#fb7185")
METRICS = {
    "hr": {"label": "Heart rate", "unit": "bpm", "precision": 0, "tolerance": 10.0, "symbol": "♡", "limits": (20, 240)},
    "bp": {"label": "Blood pressure", "unit": "mmHg", "symbol": "↗"},
    "temp": {"label": "Temperature", "unit": "°C", "precision": 1, "tolerance": 0.6, "symbol": "°", "limits": (32, 43)},
    "spo2": {"label": "SpO₂", "unit": "%", "precision": 0, "tolerance": 2.0, "symbol": "◉", "limits": (50, 100)},
    "sleep": {"label": "Sleep", "unit": "h", "precision": 1, "tolerance": 1.5, "symbol": "☾", "limits": (0, 24)},
}
RED_FLAGS = ("Chest pain / pressure", "Trouble breathing", "Loss of consciousness", "Severe bleeding", "New weakness / confusion", "Seizure")
RED_FLAG_PATTERNS = {
    RED_FLAGS[0]: r"\bchest\s+(?:pain|pressure|tightness)\b|\bpain\s+in\s+(?:my\s+|the\s+)?chest\b|бол[ьи]\s+в\s+груд[ьи]|давлени[ея]\s+в\s+груд[ьи]|сдавлива\w*\s+груд\w*",
    RED_FLAGS[1]: r"\b(?:shortness\s+of\s+breath|trouble\s+breathing|difficulty\s+breathing|can(?:not|'t)\s+breathe|choking)\b|одышк\w*|удушь\w*|задыха\w*|(?:трудно|тяжело|не\s+могу)\s+дышать",
    RED_FLAGS[2]: r"\b(?:unconscious|unresponsive|lost\s+consciousness|loss\s+of\s+consciousness|passed\s+out)\b|потер[яию]\s+сознания|без\s+сознания|обморок\w*",
    RED_FLAGS[3]: r"\b(?:severe|heavy|uncontrolled)\s+bleeding\b|(?:сильн\w*|массивн\w*|неостанавливающ\w*)\s+кровотечени\w*",
    RED_FLAGS[4]: r"\b(?:one[- ]sided\s+weakness|sudden\s+confusion|face\s+droop|slurred\s+speech)\b|перекос\w*\s+лица|внезапн\w*\s+(?:спутанност\w*|слабост\w*)|нарушени\w*\s+речи",
    RED_FLAGS[5]: r"\b(?:seizure|convulsion)s?\b|судорог\w*",
}
RED_FLAGS += ("Sudden severe headache", "Severe abdominal pain", "Facial / tongue swelling")
RED_FLAG_PATTERNS.update({
    RED_FLAGS[6]: r"\b(?:thunderclap\s+headache|sudden\s+severe\s+headache)\b|внезапн\w*\s+сильн\w*\s+головн\w*\s+бол\w*",
    RED_FLAGS[7]: r"\bsevere\s+(?:abdominal|stomach|belly)\s+pain\b|сильн\w*\s+бол\w*\s+в\s+живот\w*",
    RED_FLAGS[8]: r"\b(?:tongue|facial)\s+swelling\b|от[её]к\w*\s+(?:языка|лица)",
})
NEGATION_PREFIX = re.compile(r"(?:\bno\b|\bwithout\b|\bdenies\b|\bdeny\b|\bnot\s+having\b|\bdo\s+not\s+have\b|\bdon't\s+have\b|\bнет\b|\bбез\b|\bотрица\w*\b|\bне\s+было\b)(?:\s+[\w'-]+){0,3}\s*$", re.I)
SOURCES = [
    {"title": "NHS: chest pain - emergency warning signs", "url": "https://www.nhs.uk/symptoms/chest-pain/"},
    {"title": "NHS: shortness of breath - emergency warning signs", "url": "https://www.nhs.uk/symptoms/shortness-of-breath/"},
    {"title": "NHS: headaches", "url": "https://www.nhs.uk/conditions/headaches/"},
    {"title": "NHS: dehydration", "url": "https://www.nhs.uk/conditions/dehydration/"},
    {"title": "NHS: stomach ache", "url": "https://www.nhs.uk/symptoms/stomach-ache/"},
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_time(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


VALUE_KEYS = ("hr", "sys", "dia", "temp", "spo2", "sleep")
VALUE_LABELS = {"hr": "Heart rate", "sys": "Systolic pressure", "dia": "Diastolic pressure", "temp": "Temperature", "spo2": "SpO₂", "sleep": "Sleep"}
VALUE_LIMITS = {"hr": (20.0, 240.0), "sys": (60.0, 240.0), "dia": (30.0, 160.0), "temp": (32.0, 43.0), "spo2": (50.0, 100.0), "sleep": (0.0, 24.0)}
BLOOD_TYPES = ["", "A Rh+", "A Rh-", "B Rh+", "B Rh-", "AB Rh+", "AB Rh-", "O Rh+", "O Rh-", "Unknown"]


def empty_values() -> dict:
    return dict.fromkeys(VALUE_KEYS)


def known(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def display_number(value: Any, precision: int = 0, suffix: str = "") -> str:
    return f"{value:.{precision}f}{suffix}" if known(value) else "—"


def metric_value(vitals: dict, metric: str) -> str:
    if metric == "bp":
        return f"{display_number(vitals.get('sys'))} / {display_number(vitals.get('dia'))}"
    info = METRICS[metric]
    return display_number(vitals.get(metric), info["precision"], " " + info["unit"])


def baseline_range(baseline: dict, metric: str) -> tuple[float, float] | None:
    value = baseline.get(metric)
    if not known(value):
        return None
    tolerance = METRICS[metric]["tolerance"]
    lower, upper = METRICS[metric]["limits"]
    return max(lower, value - tolerance), min(upper, value + tolerance)


def comparable(vitals: dict, baseline: dict, metric: str) -> bool:
    keys = ("sys", "dia") if metric == "bp" else (metric,)
    return any(known(vitals.get(key)) and known(baseline.get(key)) for key in keys)


def deviations(vitals: dict, baseline: dict) -> list[str]:
    result = []
    for metric in METRICS:
        if metric == "bp":
            abnormal = any(known(vitals.get(key)) and known(baseline.get(key)) and abs(vitals[key] - baseline[key]) > tolerance for key, tolerance in (("sys", 15), ("dia", 10)))
        else:
            limits = baseline_range(baseline, metric)
            abnormal = bool(limits and known(vitals.get(metric)) and not limits[0] <= vitals[metric] <= limits[1])
        if abnormal:
            result.append(metric)
    return result


def validate_vitals(vitals: dict, *, baseline: bool = False) -> None:
    # NULL means unknown, never zero or an implicitly assumed population baseline.
    for key, (low, high) in VALUE_LIMITS.items():
        value = vitals.get(key)
        if value is not None and (not known(value) or not low <= value <= high):
            raise ValueError(f"{VALUE_LABELS[key]}: leave blank or enter a value between {low:g} and {high:g}.")
    if known(vitals.get("sys")) and known(vitals.get("dia")) and vitals["sys"] <= vitals["dia"]:
        raise ValueError("Systolic pressure must be higher than diastolic pressure.")


def empty_draft() -> dict:
    return {"description": "", "location": "", "duration": None, "unit": "Hours", "pain": None,
            "quality": "", "course": "", "onset": "", "progression": "", "trigger": "", "red_flags": []}


def normalize_profile(profile: dict) -> dict:
    result = {"id": "", "name": "", "role": "", "age": None, "blood_type": "", "allergies": "", "medications": "", "conditions": "", "mission": "", "mission_start": None, "is_demo": False, "updated_at": iso_time(), **profile}
    result["baseline"] = {**empty_values(), **(profile.get("baseline") or {})}
    return result


def mission_day(profile: dict) -> int | None:
    if not profile.get("mission_start"):
        return None
    return max(1, (utc_now().date() - date.fromisoformat(profile["mission_start"])).days + 1)


def positive_matches(text: str, pattern: str) -> list[str]:
    evidence = []
    for clause in re.split(r"[.!?;\n]|\b(?:but|however|но|однако)\b", text.casefold()):
        for match in re.finditer(pattern, clause, re.I):
            prefix = clause[max(0, match.start() - 55):match.start()]
            suffix = clause[match.end():match.end() + 30]
            if not NEGATION_PREFIX.search(prefix) and not re.match(r"\s*(?:is\s+absent|absent|нет\b|отсутств\w*)", suffix):
                if match.group() not in evidence:
                    evidence.append(match.group())
    return evidence


def detect_red_flags(text: str) -> list[str]:
    return [flag for flag, pattern in RED_FLAG_PATTERNS.items() if positive_matches(text, pattern)]


def symptom_present(text: str, pattern: str) -> bool:
    return bool(positive_matches(text, pattern))


SYMPTOM_PATTERNS = {
    "headache": ("Headache", r"\bheadache\w*\b|головн\w*\s+бол\w*|болит\s+голова"),
    "dizziness": ("Dizziness", r"\b(?:dizz\w*|vertigo|lightheaded\w*)\b|головокруж\w*|кружится\s+голова"),
    "nausea": ("Nausea", r"\b(?:nausea\w*|queasy|motion\s+sickness)\b|тошн\w*|укачива\w*"),
    "vomiting": ("Vomiting", r"\b(?:vomit\w*|throwing\s+up)\b|рвот\w*|рв[её]т"),
    "diarrhea": ("Diarrhea", r"\bdiarrh\w*\b|диаре\w*|понос\w*"),
    "abdominal": ("Abdominal discomfort", r"\b(?:stomach\s+(?:ache|pain)|abdominal\s+pain|belly\s+pain|cramps?)\b|бол\w*\s+(?:в\s+живот\w*|живота)|болит\s+живот|спазм\w*"),
    "fatigue": ("Fatigue", r"\b(?:fatigue|tired\w*|exhaust\w*)\b|устал\w*|утомл[её]н\w*|упадок\s+сил"),
    "sleep_issue": ("Sleep difficulty", r"\b(?:insomnia|poor\s+sleep|cannot\s+sleep|can't\s+sleep|sleep\s+depriv\w*)\b|недосып\w*|бессон\w*|плохо\s+сплю|не\s+могу\s+уснуть"),
    "cough": ("Cough", r"\bcough\w*\b|кашл\w*|кашель"),
    "throat": ("Sore throat", r"\bsore\s+throat\b|бол\w*\s+в\s+горле|болит\s+горло|перш\w*"),
    "fever": ("Fever / chills", r"\b(?:fever|chills?)\b|лихорад\w*|озноб\w*|жар\b"),
    "muscle": ("Muscle / back discomfort", r"\b(?:muscle\s+(?:pain|ache|strain)|back\s+pain|strain|sore\s+muscles)\b|мышечн\w*\s+бол\w*|болят\s+мышцы|болит\s+спина|бол\w*\s+в\s+спине|растяжени\w*|ломит\s+мышцы"),
    "urinary": ("Urinary symptoms", r"\b(?:painful\s+urination|burning\s+(?:urination|when\s+urinating)|frequent\s+urination)\b|бол\w*\s+при\s+мочеиспускании|жжени\w*\s+при\s+мочеиспускании|част\w*\s+мочеиспускани\w*"),
    "skin": ("Skin symptoms", r"\b(?:rash|itch\w*|hives)\b|сыпь|зуд\w*|крапивниц\w*"),
    "eye": ("Eye / vision symptoms", r"\b(?:eye\s+pain|blurred\s+vision|double\s+vision|eye\s+strain)\b|бол\w*\s+в\s+глаз\w*|болят\s+глаза|затуман\w*\s+зрени\w*|двоит\w*"),
    "thirst": ("Thirst / low fluid intake", r"\b(?:thirst\w*|dry\s+mouth|dark\s+urine|dehydrat\w*)\b|жажд\w*|сухост\w*\s+во\s+рту|т[её]мн\w*\s+моч\w*|обезвож\w*"),
    "anxiety": ("Stress / anxiety", r"\b(?:anxious|anxiety|panic\w*|stress\w*)\b|тревог\w*|паник\w*|стресс\w*"),
    "palpitations": ("Palpitations", r"\b(?:palpitation\w*|racing\s+heart)\b|сердцебиени\w*|сердце\s+колот\w*"),
    "light_sensitive": ("Light sensitivity", r"\b(?:photophobia|light\s+sensitivity|sensitive\s+to\s+light)\b|светобояз\w*|больно\s+смотреть\s+на\s+свет"),
    "exercise": ("Recent exertion", r"\b(?:after\s+(?:exercise|workout)|lifting|post[- ]exercise)\b|после\s+трениров\w*|после\s+нагруз\w*|подъ[её]м\w*\s+тяжест\w*"),
}


def assess(profile: dict, vitals: dict, symptoms: dict, *, timestamp: str | None = None, sleep_average: float | None = None) -> dict:
    """Reproducible evidence-based rule composition; unknown values stay unknown."""
    profile = normalize_profile(profile)
    vitals = {**empty_values(), **vitals}
    validate_vitals(vitals)
    baseline = profile["baseline"]
    validate_vitals(baseline, baseline=True)
    text, location = str(symptoms.get("description") or "").strip(), str(symptoms.get("location") or "").strip()
    pain, duration = symptoms.get("pain"), symptoms.get("duration_hours")
    if pain is not None and (not known(pain) or not 0 <= pain <= 10):
        raise ValueError("Pain must be 0-10 or left blank.")
    if duration is not None and (not known(duration) or duration < 0):
        raise ValueError("Duration must be non-negative or left blank.")
    feature_evidence = {key: positive_matches(text, pattern) for key, (_, pattern) in SYMPTOM_PATTERNS.items()}
    if known(pain) and pain > 0:
        for key, pattern in (("headache", r"\bhead\b|голов\w*|лоб\w*"), ("abdominal", r"\b(?:stomach|abdomen|belly)\b|живот\w*"), ("muscle", r"\b(?:muscle|back)\b|мышц\w*|спин\w*"), ("eye", r"\beyes?\b|глаз\w*")):
            if re.search(pattern, location, re.I):
                feature_evidence[key].append("Pain location: " + location)
    if symptoms.get("trigger") == "After exercise":
        feature_evidence["exercise"].append("Selected trigger: after exercise")
    features = {key for key, evidence in feature_evidence.items() if evidence}
    quality, course = symptoms.get("quality") or "", symptoms.get("course") or ""
    sudden = symptoms.get("onset") == "Sudden" or symptom_present(text, r"\bsudden\w*\b|внезапн\w*|резко\s+начал\w*")
    worsening = symptoms.get("progression") == "Worsening" or symptom_present(text, r"\b(?:worsening|getting\s+worse)\b|нараста\w*|ухудша\w*")
    changed = deviations(vitals, baseline)
    red_flags = list(dict.fromkeys([flag for flag in symptoms.get("red_flags", []) if flag in RED_FLAGS] + detect_red_flags(text + ". " + location)))
    if known(pain) and pain > 0 and re.search(r"\b(?:chest|thorax)\b|груд\w*", location, re.I):
        if RED_FLAGS[0] not in red_flags:
            red_flags.append(RED_FLAGS[0])
    emergency, urgent = [], []
    if red_flags:
        emergency.append("Reported red flags: " + ", ".join(red_flags))
    h, s, d, t, o = (vitals[key] for key in ("hr", "sys", "dia", "temp", "spo2"))
    if known(o) and o <= 90:
        emergency.append(f"Measured SpO₂ {o:g}% is at or below the emergency observation limit")
    if known(h) and (h < 40 or h >= 150):
        emergency.append(f"Marked heart-rate abnormality: {h:g} bpm")
    if (known(s) and (s < 80 or s >= 180)) or (known(d) and d >= 120):
        emergency.append("Marked blood-pressure abnormality: " + metric_value(vitals, "bp"))
    if known(t) and (t < 35 or t >= 40):
        emergency.append(f"Marked temperature abnormality: {t:g} °C")
    if "headache" in features and sudden and known(pain) and pain >= 7:
        emergency.append("Sudden severe headache")
    if "abdominal" in features and known(pain) and pain >= 7:
        emergency.append("Severe abdominal pain needs emergency assessment")
    if known(o) and 90 < o < 95:
        urgent.append(f"SpO₂ below 95% ({o:g}%)")
    if known(h) and (120 <= h < 150 or 40 <= h < 50):
        urgent.append(f"Resting heart rate requires review ({h:g} bpm)")
    if (known(s) and (80 <= s < 90 or 160 <= s < 180)) or (known(d) and 100 <= d < 120):
        urgent.append("Blood pressure requires clinician review")
    if known(t) and 38.5 <= t < 40:
        urgent.append(f"Measured temperature {t:g} °C requires medical review")
    if known(pain) and pain >= 7:
        urgent.append(f"Severe reported pain ({pain:g}/10)")
    if known(duration) and duration >= 24 and text and symptoms.get("kind") != "routine":
        urgent.append(f"Symptoms persisting for {duration:g} hours")
    if worsening and (not known(pain) or pain >= 4):
        urgent.append("Symptoms are worsening")
    if len(changed) >= 3:
        urgent.append("At least three personal-baseline deviations: " + ", ".join(METRICS[key]["label"] for key in changed))
    if "vomiting" in features and "thirst" in features:
        urgent.append("Vomiting together with signs of fluid loss")
    if "urinary" in features and ("fever" in features or (known(t) and t >= 38)):
        urgent.append("Urinary complaints together with fever")
    if "eye" in features and (sudden or (known(pain) and pain >= 5)):
        urgent.append("New painful or sudden vision symptoms")
    captured_at = vitals.get("timestamp")
    report_time = parse_time(timestamp) if timestamp else utc_now()
    stale = bool(captured_at and (report_time - parse_time(captured_at)).total_seconds() > 6 * 3600)
    if stale:
        urgent.append("Latest telemetry is older than 6 hours; obtain fresh measurements")
    if emergency:
        level, reasons = 3, emergency + urgent
    elif urgent:
        level, reasons = 2, urgent
    elif (known(pain) and pain >= 3) or len(changed) >= 2 or (known(t) and t >= 38) or features.intersection({"vomiting", "diarrhea"}):
        level, reasons = 1, []
        if known(pain) and pain >= 3:
            reasons.append(f"Reported pain {pain:g}/10")
        if changed:
            reasons.append("Baseline deviations: " + ", ".join(METRICS[key]["label"] for key in changed))
        if features.intersection({"vomiting", "diarrhea"}):
            reasons.append("Gastrointestinal fluid-loss symptoms were reported")
        if known(t) and t >= 38:
            reasons.append(f"Measured temperature {t:g} °C")
    else:
        level, reasons = 0, ["No escalation rule triggered in the available data; unknown measurements were not assumed normal"]

    # Compose ranked hypotheses from matched phrases and measured corroboration.
    candidates = []
    def cause(name: str, score: float, evidence: list[str]) -> None:
        if score > 0 and evidence:
            candidates.append({"name": name, "score": round(score, 2), "reason": "; ".join(dict.fromkeys(evidence))})

    sleep_value = sleep_average if known(sleep_average) else vitals.get("sleep")
    sleep_short = known(sleep_value) and ((known(baseline.get("sleep")) and sleep_value < baseline["sleep"] - 1.5) or sleep_value < 6)
    if features.intersection({"fatigue", "sleep_issue"}) or sleep_short:
        evidence = [SYMPTOM_PATTERNS[key][0] + " reported" for key in ("fatigue", "sleep_issue") if key in features]
        if sleep_short:
            evidence.append(f"Recorded sleep {sleep_value:.1f} h" + (f" vs. personal baseline {baseline['sleep']:.1f} h" if known(baseline.get("sleep")) else "; personal sleep baseline not set"))
        cause("Sleep deficit / circadian strain", 1.5 * len(evidence) + (1 if "sleep_issue" in features else 0), evidence)
    if "headache" in features:
        migraine_pattern = bool(features.intersection({"nausea", "light_sensitive"})) or quality == "Throbbing"
        cause("Migraine-like headache pattern" if migraine_pattern else "Tension-type or activity-related headache pattern", 2 + int(migraine_pattern), ["Headache reported", *( ["Associated nausea or light sensitivity"] if features.intersection({"nausea", "light_sensitive"}) else []), *( [f"Pain character: {quality}"] if quality else [])])
    if features.intersection({"dizziness", "nausea"}):
        cause("Vestibular / motion-related discomfort", 1.5 * len(features.intersection({"dizziness", "nausea"})) + int(symptoms.get("trigger") == "Head movement"), [SYMPTOM_PATTERNS[key][0] + " reported" for key in ("dizziness", "nausea") if key in features] + (["Symptoms related to head movement"] if symptoms.get("trigger") == "Head movement" else []))
    if "thirst" in features or (features.intersection({"dizziness", "fatigue"}) and features.intersection({"vomiting", "diarrhea"})):
        cause("Fluid loss / insufficient fluid intake", 2 * int("thirst" in features) + len(features.intersection({"vomiting", "diarrhea", "dizziness"})), [SYMPTOM_PATTERNS[key][0] + " reported" for key in ("thirst", "vomiting", "diarrhea", "dizziness") if key in features])
    if features.intersection({"cough", "throat", "fever"}) or (known(t) and t >= 38):
        cause("Respiratory infection / inflammatory process" if features.intersection({"cough", "throat"}) else "Febrile illness / inflammatory process", len(features.intersection({"cough", "throat", "fever"})) + (2 if known(t) and t >= 38 else 0), [SYMPTOM_PATTERNS[key][0] + " reported" for key in ("cough", "throat", "fever") if key in features] + ([f"Measured temperature {t:g} °C"] if known(t) and t >= 38 else []))
    if features.intersection({"abdominal", "vomiting", "diarrhea"}):
        cause("Gastrointestinal irritation / gastroenteritis pattern", len(features.intersection({"abdominal", "vomiting", "diarrhea"})) + int("diarrhea" in features), [SYMPTOM_PATTERNS[key][0] + " reported" for key in ("abdominal", "vomiting", "diarrhea") if key in features])
    if "muscle" in features:
        cause("Musculoskeletal strain / overuse", 2 + 2 * int("exercise" in features), ["Muscle or back pain reported"] + (["Recent exertion reported"] if "exercise" in features else []) + ([f"Pain described as {quality.lower()}"] if quality else []))
    if "urinary" in features:
        cause("Urinary tract irritation / infection pattern", 3 + int("fever" in features), ["Pain, burning or frequency associated with urination"])
    if "skin" in features:
        cause("Contact irritation / allergic skin response", 2.5, ["Rash or itching reported", "New exposures and medications need review"])
    if "eye" in features:
        cause("Ocular strain or another eye condition", 2.5, ["Eye discomfort or vision change reported; examination is required"])
    if "anxiety" in features:
        cause("Stress-related physiological response", 2 + int("palpitations" in features), ["Anxiety or stress explicitly reported"] + (["Palpitations reported; medical causes still require assessment"] if "palpitations" in features else []))
    if known(o) and o < 95:
        cause("Reduced oxygenation / sensor-fit problem", 4, [f"Recorded SpO₂ {o:g}%", "Repeat sensor check and clinical assessment are needed"])
    if "palpitations" in features or (known(h) and (h >= 120 or h < 50)):
        cause("Heart-rate disturbance or exertional response", 2 + int(known(h) and (h >= 120 or h < 50)), (["Palpitations reported"] if "palpitations" in features else []) + ([f"Measured heart rate {h:g} bpm"] if known(h) else []))
    if not candidates:
        cause("Cause remains unresolved from the supplied description", 1, ["No specific symptom combination matched the local rules", "Further history and examination are needed"])
    candidates.sort(key=lambda item: (-item["score"], item["name"]))
    top_score = candidates[0]["score"]
    causes = [{**item, "likelihood": "more likely" if item["score"] >= max(1, top_score - 0.75) else "less likely"} for item in candidates[:4]]
    causes.append({"name": "Other causes requiring clinical examination", "likelihood": "less likely", "score": None, "reason": "The rule matches do not establish or exclude a diagnosis."})

    recommendations = []
    def recommend(message: str) -> None:
        if message not in recommendations:
            recommendations.append(message)
    if level == 3:
        recommend("Activate the onboard emergency protocol now. Alert another crew member and the commander; request urgent medical support.")
        recommend("Have trained crew assess responsiveness and normal breathing and follow the approved emergency checklist and available AED instructions.")
        recommend("Attempt the emergency ground channel. Continue onboard care while offline; a queued report is not a distress call.")
        recommend("Prepare for the flight surgeon and commander's evacuation decision; this app cannot authorize evacuation.")
    elif level == 2:
        recommend("Contact the flight surgeon / ground medical team promptly and share this report, including: " + reasons[0] + ".")
    elif level == 1:
        recommend("Pause the task that aggravates the symptoms and inform the crew medical officer before using an onboard care protocol.")
    else:
        recommend("Record changes in the reported symptoms and their effect on daily activities; seek crew medical review if they persist or worsen.")
    if level < 3:
        if "headache" in features:
            recommend("Rest away from bright light and demanding visual tasks; note headache location, onset and any new visual or neurological symptoms." if "light_sensitive" in features or quality == "Throbbing" else "Pause demanding tasks, rest in a quiet setting and record the headache's location, triggers and course.")
        if "dizziness" in features:
            recommend("Avoid rapid position changes and unsupported movement; ask another crew member to assist while you feel dizzy.")
        if "nausea" in features and symptoms.get("trigger") == "Head movement":
            recommend("Reduce provoking head movements and record whether nausea improves when motion stops.")
        if features.intersection({"nausea", "vomiting", "diarrhea", "thirst"}):
            recommend("If fully alert and able to swallow, follow your approved hydration plan; with nausea use small sips and report difficulty retaining fluids. Record vomiting, stool changes and urine output.")
        if "abdominal" in features:
            recommend("Record the exact abdominal location and any link with meals or bowel changes. Escalate immediately for sudden severe pain, blood, collapse or a rigid painful abdomen.")
        if features.intersection({"cough", "throat", "fever"}):
            recommend("Measure temperature again, record cough or throat changes and follow onboard infection-control procedures while arranging crew medical review.")
        if "muscle" in features:
            recommend("Stop movements that reproduce the muscle or back pain; document recent exercise, trauma, weakness and limits to normal movement.")
        if "urinary" in features:
            recommend("Report urinary burning, frequency and urine changes to the crew medical officer; include any fever or flank pain in the ground summary.")
        if "skin" in features:
            recommend("Record the rash distribution and recent medicines, foods or contact exposures. Facial or tongue swelling or breathing difficulty requires Emergency.")
        if "eye" in features:
            recommend("Pause visually demanding work and arrange an eye assessment; sudden loss of vision or associated neurological signs require emergency escalation.")
        if features.intersection({"fatigue", "sleep_issue"}) or sleep_short:
            recommend((f"Review the recorded {sleep_value:.1f} h sleep against your " + (f"{baseline['sleep']:.1f} h personal target" if known(baseline.get('sleep')) else "planned mission rest period") + "; protect the next rest period and review workload.") if known(sleep_value) else "Keep a sleep and workload diary and protect the next planned rest period; enter measured sleep when available.")
        if "anxiety" in features:
            recommend("Pause demanding operations, seek support from another crew member and review stress triggers; do not attribute chest pain or breathlessness to anxiety without medical assessment.")
        if known(h) and ("hr" in changed or h >= 100 or h < 50):
            recommend(f"Recheck the recorded {h:g} bpm heart rate after quiet rest and note recent exertion, stimulant intake and palpitations.")
        if "bp" in changed:
            recommend("Repeat blood pressure with the approved cuff and positioning, and record both systolic and diastolic readings for review.")
        if known(o) and o < 95:
            recommend(f"Promptly verify the SpO₂ reading ({o:g}%) with a correctly fitted sensor and have crew check cabin oxygen conditions; do not delay medical contact.")
        if "temp" in changed and not features.intersection({"cough", "throat", "fever"}):
            recommend("Repeat temperature using the approved measurement method and record the change from your own baseline.")
        if "headache" in features and "dizziness" in features:
            recommend("Have crew verify ventilation and cabin environmental readings, including CO₂, against approved mission limits.")
        if worsening:
            recommend("Because the symptoms are worsening, stop the current task and provide the crew medical officer with a timed record of changes.")
        interval = "15 minutes while arranging medical review" if level == 2 else "30 minutes" if level == 1 else "2 hours, or sooner if symptoms change"
        recommend("Repeat the symptom and available vital-sign check in " + interval + ".")
    if profile.get("allergies"):
        recommend("Before any protocol-directed treatment, review the recorded allergies: " + profile["allergies"] + ".")
    if profile.get("medications"):
        recommend("Ask the medical officer to review current medicines and possible interactions: " + profile["medications"] + ".")
    if not any(known(vitals.get(key)) for key in VALUE_KEYS):
        recommend("Obtain and enter current vital signs when possible; this assessment currently uses symptoms only.")

    findings, gaps = [], []
    for metric, info in METRICS.items():
        keys = ("sys", "dia") if metric == "bp" else (metric,)
        available = any(known(vitals.get(key)) for key in keys)
        if not available:
            finding = info["label"] + ": no current measurement supplied"
            gaps.append("Current " + info["label"])
        elif not comparable(vitals, baseline, metric):
            finding = info["label"] + ": " + metric_value(vitals, metric) + "; personal baseline not set"
        else:
            delta = " / ".join(display_number(vitals[key] - baseline[key], 0) if known(vitals.get(key)) and known(baseline.get(key)) else "—" for key in keys) if metric == "bp" else f"{vitals[metric] - baseline[metric]:+.{info['precision']}f} {info['unit']}"
            finding = f"{info['label']}: {metric_value(vitals, metric)} vs. baseline {metric_value(baseline, metric)} (Δ {delta})"
        if not all(known(baseline.get(key)) for key in keys):
            gaps.append("Baseline " + info["label"])
        findings.append({"metric": metric, "text": finding, "deviation": metric in changed})
    if pain is None:
        gaps.append("Pain intensity")
    if duration is None:
        gaps.append("Symptom duration")
    recognized = [{"id": key, "label": SYMPTOM_PATTERNS[key][0], "evidence": feature_evidence[key]} for key in SYMPTOM_PATTERNS if key in features]
    return {"id": str(uuid.uuid4()), "crew_id": profile["id"], "created_at": timestamp or iso_time(),
            "engine": "AstroGuard evidence-composed local rules v2.0", "kind": symptoms.get("kind", "assessment"),
            "severity": SEVERITIES[level], "severity_index": level, "reasons": reasons, "symptoms": copy.deepcopy(symptoms),
            "red_flags": red_flags, "vitals": copy.deepcopy(vitals), "profile": copy.deepcopy(profile),
            "sleep_average_3d": sleep_average, "findings": findings, "recommendations": recommendations,
            "possible_causes": causes, "recognized_symptoms": recognized, "data_gaps": gaps,
            "coverage": {"measured": sum(known(vitals.get(key)) for key in VALUE_KEYS), "baseline": sum(known(baseline.get(key)) for key in VALUE_KEYS), "total": len(VALUE_KEYS)},
            "telemetry_stale": stale, "sources": copy.deepcopy(SOURCES),
            "disclaimer": "Educational decision-support prototype, not a diagnosis or validated clinical triage. Qualitative causes are reproducible rule matches, not probabilities. Missing data is not assumed normal. Ground communication is simulated locally."}


class Store:
    """SQLite is authoritative; session state is only a cache of visible widgets."""

    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.path), timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 20000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Retain the original file, including its WAL, in a SQLite-native backup.
        if self.path.exists():
            with self.connection() as source:
                tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "profiles" in tables and source.execute("PRAGMA user_version").fetchone()[0] < 2:
                    backup_path = self.path.with_name(self.path.stem + ".v1-backup" + self.path.suffix)
                    if not backup_path.exists():
                        target = sqlite3.connect(str(backup_path))
                        try:
                            source.backup(target)
                        finally:
                            target.close()
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            statements = [
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS telemetry (id INTEGER PRIMARY KEY AUTOINCREMENT, crew_id TEXT NOT NULL REFERENCES profiles(id), timestamp TEXT NOT NULL, hr REAL, sys REAL, dia REAL, temp REAL, spo2 REAL, sleep REAL, source TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY,crew_id TEXT NOT NULL REFERENCES profiles(id),created_at TEXT NOT NULL,severity TEXT NOT NULL,saved INTEGER NOT NULL DEFAULT 0,payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS transmissions (id TEXT PRIMARY KEY,report_id TEXT NOT NULL UNIQUE REFERENCES reports(id),queued_at TEXT NOT NULL,delivered_at TEXT,status TEXT NOT NULL DEFAULT 'queued',payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS ground_inbox (id TEXT PRIMARY KEY,transmission_id TEXT NOT NULL UNIQUE REFERENCES transmissions(id),received_at TEXT NOT NULL,acknowledgement TEXT NOT NULL,payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS wellbeing (crew_id TEXT NOT NULL REFERENCES profiles(id),day TEXT NOT NULL,stress INTEGER,mood TEXT,activity INTEGER,PRIMARY KEY(crew_id,day))",
                "CREATE TABLE IF NOT EXISTS symptom_drafts (crew_id TEXT PRIMARY KEY REFERENCES profiles(id),updated_at TEXT NOT NULL,payload TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS activity_log (id INTEGER PRIMARY KEY AUTOINCREMENT,crew_id TEXT REFERENCES profiles(id),timestamp TEXT NOT NULL,action TEXT NOT NULL,entity_id TEXT,details TEXT NOT NULL)",
            ]
            for statement in statements:
                connection.execute(statement)
            # v1 required every metric. Rebuild only the affected tables, preserving IDs.
            if any(row["notnull"] for row in connection.execute("PRAGMA table_info(telemetry)") if row["name"] in VALUE_KEYS):
                connection.execute("CREATE TABLE telemetry_v2 (id INTEGER PRIMARY KEY AUTOINCREMENT,crew_id TEXT NOT NULL REFERENCES profiles(id),timestamp TEXT NOT NULL,hr REAL,sys REAL,dia REAL,temp REAL,spo2 REAL,sleep REAL,source TEXT NOT NULL)")
                connection.execute("INSERT INTO telemetry_v2 SELECT * FROM telemetry")
                connection.execute("DROP TABLE telemetry")
                connection.execute("ALTER TABLE telemetry_v2 RENAME TO telemetry")
            if any(row["notnull"] for row in connection.execute("PRAGMA table_info(wellbeing)") if row["name"] in ("stress", "mood", "activity")):
                connection.execute("CREATE TABLE wellbeing_v2 (crew_id TEXT NOT NULL REFERENCES profiles(id),day TEXT NOT NULL,stress INTEGER,mood TEXT,activity INTEGER,PRIMARY KEY(crew_id,day))")
                connection.execute("INSERT INTO wellbeing_v2 SELECT * FROM wellbeing")
                connection.execute("DROP TABLE wellbeing")
                connection.execute("ALTER TABLE wellbeing_v2 RENAME TO wellbeing")
            for statement in (
                "CREATE INDEX IF NOT EXISTS telemetry_crew_time ON telemetry(crew_id,timestamp)",
                "CREATE INDEX IF NOT EXISTS reports_crew_time ON reports(crew_id,created_at)",
                "CREATE INDEX IF NOT EXISTS activity_crew_time ON activity_log(crew_id,timestamp)",
            ):
                connection.execute(statement)
            connection.execute("INSERT OR IGNORE INTO settings VALUES ('offline','true')")
            connection.execute("INSERT INTO settings VALUES ('schema_version','2') ON CONFLICT(key) DO UPDATE SET value='2'")
            connection.execute("PRAGMA user_version = 2")

    @staticmethod
    def _audit(connection: sqlite3.Connection, crew_id: str | None, action: str, entity_id: str | None = None, details: dict | None = None) -> None:
        connection.execute("INSERT INTO activity_log (crew_id,timestamp,action,entity_id,details) VALUES (?,?,?,?,?)", (crew_id, iso_time(), action, entity_id, json_text(details or {})))

    def audit(self, crew_id: str | None, action: str, entity_id: str | None = None, details: dict | None = None) -> None:
        with self.connection() as connection:
            self._audit(connection, crew_id, action, entity_id, details)

    def activity(self, crew_id: str) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM activity_log WHERE crew_id=? ORDER BY id DESC", (crew_id,)).fetchall()
        return [{**dict(row), "details": json.loads(row["details"])} for row in rows]

    def setting(self, key: str, default: Any = None) -> Any:
        with self.connection() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        # A callback from another session can still refer to a deleted profile or report.
        owner = None
        if key == "selected_crew" and value is not None:
            owner = ("profiles", value)
        elif key.startswith("active_emergency_"):
            owner = ("reports", value) if value is not None else ("profiles", key.removeprefix("active_emergency_"))
        elif key.startswith("incident_closed_"):
            owner = ("reports", key.removeprefix("incident_closed_"))
        with self.connection() as connection:
            if owner is not None:
                table, record_id = owner
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (record_id,)).fetchone() is None:
                    return
            connection.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json_text(value)))

    def profiles(self) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT payload FROM profiles ORDER BY rowid").fetchall()
        return [normalize_profile(json.loads(row[0])) for row in rows]

    def profile(self, crew_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM profiles WHERE id=?", (crew_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown crew profile.")
        return normalize_profile(json.loads(row[0]))

    @staticmethod
    def _validate_profile(profile: dict) -> None:
        if not str(profile.get("name") or "").strip():
            raise ValueError("Enter a crew member name to create or save the profile.")
        validate_vitals(profile.get("baseline") or {}, baseline=True)
        age = profile.get("age")
        if age is not None and (not known(age) or not 16 <= age <= 100):
            raise ValueError("Age must be 16-100 or left blank.")
        if profile.get("mission_start"):
            date.fromisoformat(profile["mission_start"])

    def create_profile(self, fields: dict) -> dict:
        profile = normalize_profile({**fields, "id": "crew_" + uuid.uuid4().hex[:12], "is_demo": False, "updated_at": iso_time()})
        profile["name"] = profile["name"].strip()
        self._validate_profile(profile)
        with self.connection() as connection:
            connection.execute("INSERT INTO profiles VALUES (?,?)", (profile["id"], json_text(profile)))
            connection.execute("INSERT INTO symptom_drafts VALUES (?,?,?)", (profile["id"], iso_time(), json_text(empty_draft())))
            self._audit(connection, profile["id"], "profile_created", profile["id"], {"baseline_fields": [key for key in VALUE_KEYS if known(profile["baseline"].get(key))]})
        return profile

    def update_profile(self, profile: dict) -> None:
        profile = normalize_profile(copy.deepcopy(profile))
        self._validate_profile(profile)
        profile["updated_at"] = iso_time()
        with self.connection() as connection:
            old = connection.execute("SELECT payload FROM profiles WHERE id=?", (profile["id"],)).fetchone()
            if not old:
                raise ValueError("Unknown crew profile.")
            previous = json.loads(old[0])
            connection.execute("UPDATE profiles SET payload=? WHERE id=?", (json_text(profile), profile["id"]))
            self._audit(connection, profile["id"], "profile_updated", profile["id"], {"changed_fields": [key for key in profile if previous.get(key) != profile[key] and key != "updated_at"]})

    def delete_profile(self, crew_id: str) -> None:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM profiles WHERE id=?", (crew_id,)).fetchone() is None:
                raise ValueError("This profile has already been deleted.")
            if connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] <= 1:
                raise ValueError("The last profile cannot be deleted.")

            connection.execute(
                """DELETE FROM settings
                   WHERE key = ?
                      OR (key = 'selected_crew' AND value = ?)
                      OR key IN (SELECT 'incident_closed_' || id FROM reports WHERE crew_id = ?)""",
                ("active_emergency_" + crew_id, json_text(crew_id), crew_id),
            )
            connection.execute(
                """DELETE FROM ground_inbox WHERE transmission_id IN (
                       SELECT t.id FROM transmissions t JOIN reports r ON r.id = t.report_id
                       WHERE r.crew_id = ?
                   )""",
                (crew_id,),
            )
            connection.execute(
                "DELETE FROM transmissions WHERE report_id IN (SELECT id FROM reports WHERE crew_id = ?)",
                (crew_id,),
            )
            # Delete children before their parents, including on existing databases.
            for table in ("activity_log", "symptom_drafts", "wellbeing", "telemetry", "reports"):
                connection.execute(f"DELETE FROM {table} WHERE crew_id = ?", (crew_id,))
            connection.execute("DELETE FROM profiles WHERE id = ?", (crew_id,))

    def clear_baseline(self, crew_id: str) -> None:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM profiles WHERE id=?", (crew_id,)).fetchone()
            if not row:
                raise ValueError("Unknown crew profile.")
            profile = normalize_profile(json.loads(row[0]))
            profile.update(baseline=empty_values(), updated_at=iso_time())
            connection.execute("UPDATE profiles SET payload=? WHERE id=?", (json_text(profile), crew_id))
            self._audit(connection, crew_id, "baseline_cleared", crew_id)

    def draft(self, crew_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM symptom_drafts WHERE crew_id=?", (crew_id,)).fetchone()
        return {**empty_draft(), **(json.loads(row["payload"]) if row else {}), "updated_at": row["updated_at"] if row else None}

    def save_draft(self, crew_id: str, values: dict, *, cleared: bool = False, explicit: bool = False) -> None:
        draft = {key: copy.deepcopy(values.get(key, default)) for key, default in empty_draft().items()}
        for field in ("duration", "pain"):
            value = draft[field]
            if value is not None and (not known(value) or value < 0 or (field == "pain" and value > 10)):
                raise ValueError(f"Invalid {field}; enter a valid number or leave it blank.")
        with self.connection() as connection:
            old = connection.execute("SELECT payload FROM symptom_drafts WHERE crew_id=?", (crew_id,)).fetchone()
            if old and json.loads(old[0]) == draft and not (cleared or explicit):
                return
            connection.execute("INSERT INTO symptom_drafts VALUES (?,?,?) ON CONFLICT(crew_id) DO UPDATE SET updated_at=excluded.updated_at,payload=excluded.payload", (crew_id, iso_time(), json_text(draft)))
            self._audit(connection, crew_id, "symptoms_cleared" if cleared else "symptom_draft_saved", crew_id, {"characters": len(draft["description"]), "explicit_save": explicit})

    def clear_draft(self, crew_id: str) -> None:
        self.save_draft(crew_id, empty_draft(), cleared=True)

    @staticmethod
    def _insert_sample(connection: sqlite3.Connection, crew_id: str, sample: dict) -> None:
        connection.execute("INSERT INTO telemetry (crew_id,timestamp,hr,sys,dia,temp,spo2,sleep,source) VALUES (?,?,?,?,?,?,?,?,?)", (crew_id, sample["timestamp"], *(sample.get(key) for key in VALUE_KEYS), sample.get("source") or "Manual measurement"))

    def telemetry(self, crew_id: str) -> pd.DataFrame:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM telemetry WHERE crew_id=? ORDER BY timestamp,id", (crew_id,)).fetchall()
        frame = pd.DataFrame([dict(row) for row in rows], columns=["id", "crew_id", "timestamp", *VALUE_KEYS, "source"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        for key in VALUE_KEYS:
            frame[key] = pd.to_numeric(frame[key], errors="coerce")
        return frame

    def latest_vitals(self, crew_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM telemetry WHERE crew_id=? ORDER BY timestamp DESC,id DESC LIMIT 1", (crew_id,)).fetchone()
        return dict(row) if row else {**empty_values(), "timestamp": None, "source": ""}

    def add_sample(self, crew_id: str, vitals: dict, source: str = "Manual measurement") -> dict:
        validate_vitals(vitals)
        if not any(known(vitals.get(key)) for key in VALUE_KEYS):
            raise ValueError("Enter at least one measured value. Blank fields remain unknown.")
        sample = {**empty_values(), **vitals, "timestamp": iso_time(), "source": source}
        with self.connection() as connection:
            self._insert_sample(connection, crew_id, sample)
            self._audit(connection, crew_id, "telemetry_saved", str(connection.execute("SELECT last_insert_rowid()").fetchone()[0]), {"source": source, "fields": [key for key in VALUE_KEYS if known(sample[key])]})
        return sample

    @staticmethod
    def _insert_report(connection: sqlite3.Connection, report: dict, saved: bool = False) -> None:
        connection.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)", (report["id"], report["crew_id"], report["created_at"], report["severity"], int(saved), json_text(report)))

    def add_report(self, report: dict, saved: bool = False) -> None:
        with self.connection() as connection:
            self._insert_report(connection, report, saved)
            self._audit(connection, report["crew_id"], "assessment_created", report["id"], {"severity": report["severity"], "saved_to_health_log": saved, "engine": report["engine"]})

    def report(self, report_id: str) -> dict | None:
        with self.connection() as connection:
            row = connection.execute("SELECT payload FROM reports WHERE id=?", (report_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_report(self, report_id: str) -> None:
        with self.connection() as connection:
            row = connection.execute("SELECT crew_id FROM reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                raise ValueError("Unknown report.")
            connection.execute("UPDATE reports SET saved=1 WHERE id=?", (report_id,))
            self._audit(connection, row[0], "report_saved_to_health_log", report_id)

    def reports(self, crew_id: str, *, saved_only: bool = True) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT r.*,t.status AS sync_status FROM reports r LEFT JOIN transmissions t ON t.report_id=r.id WHERE r.crew_id=? AND (?=0 OR r.saved=1) ORDER BY r.created_at DESC,r.rowid DESC", (crew_id, int(saved_only))).fetchall()
        return [{**json.loads(row["payload"]), "saved": bool(row["saved"]), "sync_status": row["sync_status"] or "Local only"} for row in rows]

    def enqueue(self, report_id: str) -> str:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT crew_id,payload FROM reports WHERE id=?", (report_id,)).fetchone()
            if row is None:
                raise ValueError("Save an assessment before sending it.")
            existing = connection.execute("SELECT status FROM transmissions WHERE report_id=?", (report_id,)).fetchone()
            if existing:
                return existing[0]
            connection.execute("UPDATE reports SET saved=1 WHERE id=?", (report_id,))
            connection.execute("INSERT INTO transmissions (id,report_id,queued_at,payload) VALUES (?,?,?,?)", (str(uuid.uuid4()), report_id, iso_time(), row["payload"]))
            self._audit(connection, row["crew_id"], "ground_summary_queued", report_id)
        return "queued"

    def sync_queue(self) -> int:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT value FROM settings WHERE key='offline'").fetchone()
            if row and json.loads(row[0]):
                return 0
            queued = connection.execute("SELECT t.*,r.crew_id FROM transmissions t JOIN reports r ON r.id=t.report_id WHERE t.status='queued' ORDER BY t.queued_at").fetchall()
            for transmission in queued:
                received_at = iso_time()
                acknowledgement = "LOCAL MCC SIMULATOR: report received and archived. No real transmission or clinical review has occurred."
                connection.execute("INSERT OR IGNORE INTO ground_inbox VALUES (?,?,?,?,?)", (str(uuid.uuid4()), transmission["id"], received_at, acknowledgement, transmission["payload"]))
                connection.execute("UPDATE transmissions SET status='delivered_demo',delivered_at=? WHERE id=?", (received_at, transmission["id"]))
                self._audit(connection, transmission["crew_id"], "ground_summary_delivered_to_simulator", transmission["report_id"])
        return len(queued)

    def transmissions(self, crew_id: str | None = None) -> list[dict]:
        with self.connection() as connection:
            rows = connection.execute("SELECT t.*,r.crew_id,g.acknowledgement FROM transmissions t JOIN reports r ON r.id=t.report_id LEFT JOIN ground_inbox g ON g.transmission_id=t.id WHERE (? IS NULL OR r.crew_id=?) ORDER BY t.queued_at DESC", (crew_id, crew_id)).fetchall()
        return [dict(row) for row in rows]

    def wellbeing(self, crew_id: str) -> dict:
        with self.connection() as connection:
            row = connection.execute("SELECT * FROM wellbeing WHERE crew_id=? ORDER BY day DESC LIMIT 1", (crew_id,)).fetchone()
        return dict(row) if row else {"day": None, "stress": None, "mood": "", "activity": None}

    def save_wellbeing(self, crew_id: str, stress: int | None, mood: str, activity: int | None) -> None:
        if stress is not None and not 0 <= stress <= 10 or mood not in ("", "Good", "Neutral", "Low") or activity is not None and not 0 <= activity <= 360:
            raise ValueError("Invalid wellbeing observation.")
        if stress is None and not mood and activity is None:
            raise ValueError("Enter at least one wellbeing observation.")
        with self.connection() as connection:
            connection.execute("INSERT INTO wellbeing VALUES (?,?,?,?,?) ON CONFLICT(crew_id,day) DO UPDATE SET stress=excluded.stress,mood=excluded.mood,activity=excluded.activity", (crew_id, utc_now().date().isoformat(), stress, mood, activity))
            self._audit(connection, crew_id, "wellbeing_saved", utc_now().date().isoformat())

    def load_demo(self) -> int:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            before = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
            self._seed(connection)
            count = connection.execute("SELECT COUNT(*) FROM profiles").fetchone()[0] - before
            if count:
                self._audit(connection, None, "optional_demo_loaded", details={"profiles_added": count})
        return count

    def _seed(self, connection: sqlite3.Connection) -> None:
        now = utc_now().replace(microsecond=0)
        start_date = (now.date() - timedelta(days=141)).isoformat()
        people = [
            ("elena", "Elena Vance", "Commander / Flight specialist", 38, "A Rh+", "Penicillin (moderate)", 70, 8.0),
            ("marcus", "Marcus Chen", "Flight engineer", 35, "O Rh+", "None reported", 65, 7.5),
            ("aisha", "Aisha Rahman", "Crew medical officer", 40, "B Rh+", "None reported", 72, 8.0),
        ]
        for index, (crew_id, name, role, age, blood, allergies, hr, sleep) in enumerate(people):
            if connection.execute("SELECT 1 FROM profiles WHERE id=?", (crew_id,)).fetchone():
                continue
            profile = {"id": crew_id, "name": name, "role": role, "age": age, "blood_type": blood,
                       "allergies": allergies, "medications": "None scheduled", "conditions": "None reported",
                       "mission": "ARES • Deep-space analog", "mission_start": start_date,
                       "baseline": {"hr": float(hr), "sys": 120.0, "dia": 80.0, "temp": 36.6, "spo2": 99.0, "sleep": sleep},
                       "updated_at": iso_time(now), "is_demo": True}
            connection.execute("INSERT INTO profiles VALUES (?, ?)", (crew_id, json_text(profile)))
            rng = random.Random(142 + index)
            samples = []
            for hour in range(193):
                time = now - timedelta(hours=192 - hour)
                drift = max(0.0, (hour - 120) / 72) if index == 0 else 0.0
                values = {"hr": round(hr + 14 * drift + rng.uniform(-3, 3)),
                          "sys": round(120 + 12 * drift + rng.uniform(-4, 4)),
                          "dia": round(80 + 8 * drift + rng.uniform(-3, 3)),
                          "temp": round(36.6 + 0.5 * drift + rng.uniform(-0.12, 0.12), 1),
                          "spo2": round(min(100, 99 - drift + rng.uniform(-0.4, 0.4))),
                          "sleep": round(max(4, sleep - 2.8 * drift + 0.2 * math.sin(time.day)), 1),
                          "timestamp": iso_time(time), "source": "Demo wearable"}
                if hour == 192 and index == 0:
                    values.update(hr=84.0, sys=132.0, dia=88.0, temp=37.1, spo2=98.0, sleep=5.2)
                samples.append(values)
                self._insert_sample(connection, crew_id, values)
            for offset in range(7):
                day = (now.date() - timedelta(days=offset)).isoformat()
                connection.execute("INSERT INTO wellbeing VALUES (?, ?, ?, ?, ?)", (crew_id, day, 6 if index == 0 else 3, "Neutral" if index == 0 else "Good", 75 if index == 0 else 120))
            for hours, description, pain, kind in [(48, "Routine morning telemetry check", 0, "routine"), (24, "Mild muscle discomfort after exercise", 3, "assessment")]:
                old_vitals = samples[192 - hours]
                symptoms = {"description": description, "location": "General", "duration_hours": 1.0,
                            "pain": pain, "quality": "Dull" if pain else "No pain", "course": "Comes and goes",
                            "red_flags": [], "kind": kind}
                report = assess(profile, old_vitals, symptoms, timestamp=old_vitals["timestamp"], sleep_average=old_vitals["sleep"])
                self._insert_report(connection, report, saved=True)


def sleep_average_3d(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    end = frame["timestamp"].max().date()
    recent = frame[frame["timestamp"].dt.date >= end - timedelta(days=2)]
    daily = recent.assign(day=recent["timestamp"].dt.date).groupby("day")["sleep"].last().dropna()
    return float(daily.mean()) if len(daily) else None


def make_chart(frame: pd.DataFrame, baseline: dict, metric: str, period: str, projection: bool = False) -> go.Figure:
    figure = go.Figure()
    if not frame.empty:
        end = frame["timestamp"].max().to_pydatetime()
        data = frame[frame["timestamp"] >= end - timedelta(hours={"24h": 24, "3d": 72, "7d": 168}[period])]
        series = [("sys", "Systolic", "#2dd4bf", 15), ("dia", "Diastolic", "#60a5fa", 10)] if metric == "bp" else [(metric, METRICS[metric]["label"], "#2dd4bf", METRICS[metric]["tolerance"])]
        for key, label, color, tolerance in series:
            values = data.dropna(subset=[key])
            if values.empty:
                continue
            reference = baseline.get(key)
            if known(reference):
                limits = (reference - tolerance, reference + tolerance) if metric == "bp" else baseline_range(baseline, metric)
                figure.add_hrect(y0=limits[0], y1=limits[1], fillcolor=color, opacity=0.055, line_width=0)
                figure.add_hline(y=reference, line_dash="dot", line_color=color, opacity=0.5)
            figure.add_trace(go.Scatter(x=values["timestamp"], y=values[key], name=label, mode="lines+markers", marker={"size": 3}, line={"color": color, "width": 2.6}, hovertemplate="%{x|%d %b %H:%M UTC}<br>%{y:.1f}<extra>" + label + "</extra>"))
            figure.add_trace(go.Scatter(x=[values["timestamp"].iloc[-1]], y=[values[key].iloc[-1]], name="Latest " + label, mode="markers", marker={"color": "#f59e0b", "size": 9, "line": {"color": "#0c121e", "width": 2}}, showlegend=False))
            if projection:
                tail = values[values["timestamp"] >= end - timedelta(hours=24)]
                x = (tail["timestamp"] - end).dt.total_seconds() / 3600
                y = tail[key].astype(float)
                denominator = float(((x - x.mean()) ** 2).sum())
                if len(tail) >= 3 and denominator > 0:
                    slope = float(((x - x.mean()) * (y - y.mean())).sum() / denominator)
                    low_limit, high_limit = VALUE_LIMITS[key]
                    forecast = max(low_limit, min(high_limit, float(y.iloc[-1]) + slope * 6))
                    last_time = tail["timestamp"].iloc[-1].to_pydatetime()
                    figure.add_trace(go.Scatter(x=[last_time, last_time + timedelta(hours=6)], y=[float(y.iloc[-1]), forecast], mode="lines", name=label + " · 6h extrapolation", line={"color": color, "dash": "dash", "width": 2}))
    if not figure.data:
        figure.add_annotation(text="No measurements for this metric yet.<br>Use Enter current measurements to add a reading.", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font={"color": "#8294ac", "size": 14})
    figure.update_layout(height=320, margin={"l": 12, "r": 18, "t": 12, "b": 12}, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font={"family": "Segoe UI, Arial, sans-serif", "color": "#94a3b8", "size": 12}, hovermode="x unified", legend={"orientation": "h", "y": 1.14, "x": 0}, xaxis={"gridcolor": "#1c2a3f", "title": None, "zeroline": False}, yaxis={"gridcolor": "#1c2a3f", "title": METRICS[metric]["unit"], "zeroline": False}, hoverlabel={"bgcolor": "#152236", "font_color": "#e2e8f0"})
    return figure


def report_markdown(report: dict) -> str:
    symptom = report["symptoms"]
    lines = [f"# {APP_NAME} | Crew health summary", "", report["disclaimer"], "",
             f"Report: {report['id']}", f"Recorded: {report['created_at']} (UTC)",
             f"Crew: {report['profile']['name']} | {report['profile'].get('role') or '—'}",
             f"Severity: {report['severity']}", f"Engine: {report['engine']}", "",
             "## Symptoms", symptom.get("description") or "—", f"Location: {symptom.get('location') or '—'}",
             f"Duration: {display_number(symptom.get('duration_hours'), 1, ' h')} | Pain: {display_number(symptom.get('pain'), 0, '/10')}",
             f"Quality: {symptom.get('quality') or '—'} | Course: {symptom.get('course') or '—'}",
             f"Onset: {symptom.get('onset') or '—'} | Progression: {symptom.get('progression') or '—'} | Trigger: {symptom.get('trigger') or '—'}",
             "", "## Assessment rationale"]
    lines.extend("- " + reason for reason in report["reasons"])
    lines += ["", "## Data findings"] + ["- " + finding["text"] for finding in report["findings"]]
    lines += ["", "## Relevant medical profile", f"Allergies: {report['profile'].get('allergies') or 'Not supplied'}", f"Medications: {report['profile'].get('medications') or 'Not supplied'}", f"Conditions: {report['profile'].get('conditions') or 'Not supplied'}"]
    if report.get("recognized_symptoms"):
        lines += ["", "## Recognized symptom evidence"] + ["- " + item["label"] + ": " + ", ".join(item["evidence"]) for item in report["recognized_symptoms"]]
    if report.get("data_gaps"):
        lines += ["", "## Missing data"] + ["- " + item for item in report["data_gaps"]]
    lines += ["", "## Recommendations"] + [f"{index}. {item}" for index, item in enumerate(report["recommendations"], 1)]
    lines += ["", "## Possible causes (qualitative, not a diagnosis)"] + [f"- {cause['name']} ({cause['likelihood']}): {cause['reason']}" for cause in report["possible_causes"]]
    lines += ["", "## General symptom references"] + [source["title"] + ": " + source["url"] for source in report["sources"]]
    return "\n".join(lines)


CSS = """
<style>
:root {color-scheme: dark; --teal:#2dd4bf; --muted:#94a3b8;}
.stApp {background:#0c121e;color:#e2e8f0;font-family:'Segoe UI',Arial,sans-serif;}
header[data-testid="stHeader"] {background:transparent;}
[data-testid="stMainBlockContainer"] {max-width:1530px;padding:2.6rem 2.3rem 2rem;}
[data-testid="stSidebar"] {background:#090e17;border-right:1px solid #1c2a3f;min-width:245px;max-width:275px;}
[data-testid="stSidebarContent"] {padding-top:0.8rem;}
[data-testid="stSidebarUserContent"] {padding:1.1rem 1.2rem 1rem!important;}
[data-testid="stSidebarHeader"] {height:24px!important;min-height:24px!important;margin-bottom:0!important;}
[data-testid="stSidebarCollapseButton"] span {color:#94a3b8!important;}
h1,h2,h3,h4,p,label,[data-testid="stMarkdownContainer"] {color:#e2e8f0;}
h1 {font-size:1.85rem!important;letter-spacing:-0.7px;font-weight:720!important;padding-top:0!important;}
h2 {font-size:1.3rem!important;} h3 {font-size:1.1rem!important;}
[data-testid="stCaptionContainer"] p {color:#8294ac;font-size:.78rem;line-height:1.55;}
[data-testid="stWidgetLabel"] p {font-size:.85rem;color:#a8b8cc;}
[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stNumberInput"] input {background:#111a28;color:#f1f5f9;caret-color:#2dd4bf;}
[data-baseweb="input"],[data-baseweb="base-input"],[data-baseweb="textarea"],[data-baseweb="select"]>div {background:#111a28!important;border-color:#283d5a!important;color:#e2e8f0!important;}
[data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] {background:#152236!important;color:#e2e8f0!important;}
[data-baseweb="popover"] li {color:#e2e8f0!important;}
input[role="combobox"],input[type="text"],input[type="number"],textarea {background:#111a28!important;color:#e2e8f0!important;}
div[role="group"]:has(>input[role="combobox"]) {background:#111a28!important;border:1px solid #283d5a!important;border-radius:10px;}
button[aria-label="Open"] {background:#111a28!important;color:#94a3b8!important;}
[role="listbox"],[role="option"] {background:#152236!important;color:#e2e8f0!important;}
[role="option"][data-focused],[role="option"][aria-selected="true"] {background:#16383c!important;color:#5eead4!important;}
button[data-variant="segmented_control"] {background:#0c121e!important;border-color:#283d5a!important;color:#94a3b8!important;}
button[data-variant="segmented_control"] p {color:inherit!important;}
button[data-variant="segmented_control"][aria-checked="true"] {background:#2dd4bf15!important;border-color:#2dd4bf77!important;color:#5eead4!important;}
input[type="checkbox"] {accent-color:#2dd4bf;}
details {border-color:#1c2a3f!important;}
button[kind="secondary"],button[kind="tertiary"] {background:#111a28;color:#aebfd3;border:1px solid #283d5a;border-radius:24px;font-size:.86rem;}
button[kind="secondary"]:hover,button[kind="tertiary"]:hover {border-color:#2dd4bf;color:#5eead4;background:#132c33;}
button[kind="primary"] {background:#2dd4bf!important;color:#042f2e!important;border:1px solid #2dd4bf!important;border-radius:24px;font-weight:650;}
button[kind="primary"] p {color:#042f2e!important;}
button[kind="secondary"] p,button[kind="tertiary"] p {color:inherit;}
[data-testid="stSidebar"] .stButton button {text-align:left;justify-content:flex-start;padding:.35rem .9rem;min-height:35px;}
[data-testid="stSidebar"] .stButton button[kind="tertiary"] {border-color:transparent;background:transparent;}
[data-testid="stSidebar"] .stButton button[kind="primary"] {background:rgba(45,212,191,.12)!important;color:#2dd4bf!important;border-color:transparent!important;}
[data-testid="stSidebar"] .stButton button[kind="primary"] p {color:#2dd4bf!important;}
.st-key-emergency_shortcut button {background:#fb7185!important;color:#450a0a!important;border-color:#fb7185!important;box-shadow:0 4px 16px #fb71851c;}
.st-key-emergency_shortcut button p {color:#450a0a!important;font-weight:700;}
[data-testid="stVerticalBlockBorderWrapper"] {border-color:#1c2a3f!important;border-radius:16px;}
.st-key-trend_panel,.st-key-ground_panel,.st-key-data_used,.st-key-recommendations,.st-key-causes,.st-key-findings,.st-key-profile_card,.st-key-baseline_form,.st-key-symptom_form {background:#111a28;border:1px solid #1c2a3f;border-radius:16px;padding:20px;}
.st-key-recommendations {border-color:#2dd4bf66;min-height:310px;}
[data-testid="stForm"] {border-color:#1c2a3f;background:#111a28;border-radius:16px;}
[data-testid="stExpander"] {background:#111a28;border-color:#1c2a3f;border-radius:12px;}
.brand {display:flex;align-items:center;gap:10px;margin:4px 0 17px;font-weight:750;font-size:19px;letter-spacing:-.6px;}
.brand-mark {width:31px;height:31px;display:flex;align-items:center;justify-content:center;border-radius:9px;background:linear-gradient(135deg,#2dd4bf,#0284c7);color:#042f2e;font-size:22px;}
.eyebrow {font-size:10px;font-weight:700;letter-spacing:1.7px;color:#64748b;text-transform:uppercase;margin-bottom:12px;}
.mission-card {padding:16px;border:1px solid #1c2a3f;background:#0c121e;border-radius:14px;margin:12px 0 16px;font-size:12px;color:#94a3b8;line-height:1.8;}
.mission-card strong {color:#dbeafe;}
.statusbar {display:flex;align-items:center;justify-content:space-between;gap:15px;flex-wrap:wrap;border-bottom:1px solid #1c2a3f;padding:0 0 16px;margin-bottom:24px;font-size:12px;color:#94a3b8;}
.statusbar strong {color:#e2e8f0;font-weight:600;}
.status-right {display:flex;gap:22px;align-items:center;flex-wrap:wrap;}
.dot {display:inline-block;height:6px;width:6px;border-radius:50%;margin:0 6px 1px 0;}
.small-label {font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:#8294ac;font-weight:650;margin-bottom:10px;}
.deviation-banner {padding:17px 21px;background:#f59e0b09;border:1px solid #f59e0b66;border-radius:14px;margin:4px 0 5px;}
.deviation-banner .small-label {color:#f59e0b;margin-bottom:5px;}
.deviation-banner strong {font-size:15px;font-weight:600;}
.metrics-grid {display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:14px;margin:15px 0 22px;}
.metric-card {padding:17px 18px;border:1px solid #1c2a3f;background:#111a28;border-radius:14px;min-height:125px;}
.metric-card.selected {border-color:#2dd4bf99;background:#2dd4bf08;}
.metric-title {display:flex;align-items:center;justify-content:space-between;color:#94a3b8;font-size:12px;}
.metric-symbol {color:#536c83;font-size:18px;}
.metric-value {font-size:26px;letter-spacing:-.9px;color:#f1f5f9;font-weight:700;margin:10px 0 5px;white-space:nowrap;}
.metric-value small {font-size:12px;font-weight:400;letter-spacing:0;color:#94a3b8;}
.metric-baseline {font-size:11px;color:#7b91ab;}
.metric-status {margin-top:8px;font-size:10px;}
.data-row {display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #1c2a3f;font-size:12px;color:#94a3b8;}
.data-row strong {color:#e2e8f0;text-align:right;font-weight:500;}
.chat-prompt {background:#111a28;border:1px solid #1c2a3f;border-radius:4px 16px 16px;padding:17px 20px;font-size:14px;line-height:1.6;margin:10px 0 16px;}
.severity-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:8px 0 22px;}
.severity-card {background:#111a28;border:1px solid #1c2a3f;color:#94a3b8;padding:18px 15px;border-radius:12px;font-size:12px;min-height:62px;display:flex;align-items:center;}
.recommendation {display:flex;gap:16px;padding:13px 0;line-height:1.65;font-size:14px;border-bottom:1px solid #1c2a3f;}
.recommendation span {color:#2dd4bf;font-family:monospace;font-size:12px;padding-top:3px;}
.cause {padding:12px 0;border-bottom:1px solid #1c2a3f;font-size:13px;line-height:1.6;}
.cause small {color:#8294ac;font-size:11px;display:block;margin-top:4px;}
.cause-badge {font-size:10px;color:#5eead4;float:right;padding-left:6px;}
.profile-avatar {width:68px;height:68px;border-radius:50%;background:#2dd4bf0f;border:1px solid #2dd4bf88;display:flex;align-items:center;justify-content:center;color:#2dd4bf;font-size:22px;margin:5px 0 18px;}
.footer-note {font-size:10px;color:#536c83;border-top:1px solid #1c2a3f;padding-top:18px;margin-top:26px;line-height:1.7;}
.step {color:#2dd4bf;font-size:11px;letter-spacing:.7px;}
@media(max-width:1100px) {.metrics-grid {gap:8px}.metric-card {padding:14px 11px}.metric-value {font-size:22px}}
@media(max-width:760px) {.metrics-grid {grid-template-columns:repeat(2,minmax(0,1fr))}.severity-grid {grid-template-columns:repeat(2,minmax(0,1fr))}[data-testid="stMainBlockContainer"] {padding:2.5rem 1rem 1rem}.statusbar {font-size:11px}}
</style>
"""


def markup(content: str) -> None:
    st.markdown(content, unsafe_allow_html=True)


def configure_native_theme() -> None:
    """Bootstrap the native theme without requiring a second config file.

    Streamlit 1.66+ sends theme configuration on each script restart. The config
    module is an internal API: keep this narrow compatibility adapter here so that
    native canvas tables, calendars, alerts and sliders share the single-file theme.
    A one-time rerun sends the changed theme before any application widgets render.
    """
    options = {"theme.base": "dark", "theme.primaryColor": "#2dd4bf", "theme.backgroundColor": "#0c121e",
               "theme.secondaryBackgroundColor": "#111a28", "theme.textColor": "#e2e8f0",
               "theme.sidebar.backgroundColor": "#090e17"}
    changed = False
    for key, value in options.items():
        if streamlit_config.get_option(key) != value:
            streamlit_config.set_option(key, value)
            changed = True
    if changed:
        st.rerun()


def navigate(page: str) -> None:
    st.session_state["page"] = page


def notify(message: str) -> None:
    st.session_state["notice"] = message


def set_offline(store: Store) -> None:
    offline = bool(st.session_state["offline_toggle"])
    store.set_setting("offline", offline)
    store.audit(None, "offline_mode_changed", details={"offline": offline})
    delivered = store.sync_queue() if not offline else 0
    notify("Offline mode enabled. Analysis and storage remain local." if offline else f"Demo ground link restored. {delivered} queued report(s) delivered to the local receiver.")


def trigger_emergency(store: Store, crew_id: str, reason: str = "Manual emergency activation") -> None:
    active = store.setting("active_emergency_" + crew_id)
    if not active or not store.report(active):
        profile = store.profile(crew_id)
        vitals = store.latest_vitals(crew_id)
        symptoms = {"description": reason, "location": "Emergency / crew-reported", "duration_hours": None, "pain": None, "quality": "Unspecified", "course": "Unspecified", "red_flags": [], "kind": "emergency"}
        report = assess(profile, vitals, symptoms, sleep_average=sleep_average_3d(store.telemetry(crew_id)))
        report.update(severity=SEVERITIES[3], severity_index=3, kind="emergency")
        report["reasons"] = [reason, "Priority 1 was explicitly activated by the crew."]
        report["recommendations"] = ["Alert another crew member and the commander immediately; follow the approved onboard emergency checklist.", "Have a trained crew member assess responsiveness and normal breathing, and follow the approved emergency protocol and available AED instructions.", "Attempt emergency voice / ground channels. Continue onboard care even if this application's report remains queued.", "Prepare for a medical evacuation decision by the flight surgeon and commander; this prototype cannot initiate evacuation."]
        report["possible_causes"] = [{"name": "Undetermined emergency condition", "likelihood": "more likely", "reason": "Manual activation requires immediate assessment by trained crew."}, {"name": "False alarm or measurement artifact", "likelihood": "less likely", "reason": "A trained crew member must verify the situation without delaying emergency assistance."}]
        store.add_report(report, saved=True)
        active = report["id"]
        store.set_setting("active_emergency_" + crew_id, active)
        store.audit(crew_id, "emergency_activated", active)
    store.enqueue(active)
    store.sync_queue()
    st.session_state["page"] = "Emergency"


def send_report(store: Store, report: dict) -> None:
    previous = store.enqueue(report["id"])
    delivered = store.sync_queue()
    if store.setting("offline", True):
        notify("Summary saved to the persistent offline queue. It will sync to the local simulator when Offline mode is switched off.")
    elif delivered:
        notify("Summary delivered to the LOCAL ground simulator. No data was sent to an external server.")
    elif previous == "delivered_demo":
        notify("This report is already in the local ground simulator; a duplicate was not created.")
    else:
        notify("Summary is queued locally.")


def request_new_profile() -> None:
    st.session_state["creating_profile"] = True
    navigate("Profile")


def select_crew(store: Store) -> None:
    store.set_setting("selected_crew", st.session_state["crew_picker"])
    st.session_state["creating_profile"] = False


def sidebar(store: Store, profiles: list[dict]) -> dict | None:
    with st.sidebar:
        markup('<div class="brand"><span class="brand-mark">✦</span>AstroGuard <span style="color:#2dd4bf">AI</span></div><div class="eyebrow">Crew medical console</div>')
        ids = [profile["id"] for profile in profiles]
        profile = None
        pending = st.session_state.pop("pending_crew_selection", None)
        if pending in ids:
            st.session_state["crew_picker"] = pending
        if ids:
            if st.session_state.get("crew_picker") not in ids:
                preferred = store.setting("selected_crew")
                personal = [person["id"] for person in profiles if not person["is_demo"]]
                st.session_state["crew_picker"] = preferred if preferred in ids else (personal or ids)[0]
            names = {person["id"]: person["name"] + (" · demo" if person["is_demo"] else "") for person in profiles}
            crew_id = st.selectbox("Crew member", ids, key="crew_picker", format_func=lambda value: names[value], on_change=select_crew, args=(store,))
            profile = store.profile(crew_id)
        else:
            st.caption("Create your own crew profile to begin.")
        st.button("+ New profile", key="new_profile", width="stretch", on_click=request_new_profile)
        for page in ("Dashboard", "Symptom Check", "Health Log", "Profile"):
            st.button(page, key="nav_" + page.replace(" ", "_"), disabled=not ids, type="primary" if st.session_state["page"] == page else "tertiary", width="stretch", on_click=navigate, args=(page,))
        if profile and profile.get("mission"):
            day = mission_day(profile)
            markup(f'<div class="mission-card"><div class="small-label">Current mission</div><strong>{escape(profile["mission"])}</strong>' + (f'<br>Mission day {day:03d}' if day else '') + '</div>')
        if "offline_toggle" not in st.session_state:
            st.session_state["offline_toggle"] = store.setting("offline", True)
        st.toggle("Offline mode", key="offline_toggle", on_change=set_offline, args=(store,))
        queued = sum(item["status"] == "queued" for item in store.transmissions())
        st.caption(f"SQLite · {store.path.name}\n\n{queued} report(s) queued · local ground simulator")
        st.button("Emergency", key="emergency_shortcut", disabled=profile is None, width="stretch", shortcut="Ctrl+E", on_click=trigger_emergency, args=(store, profile["id"] if profile else ""))
        st.caption("NASA Space Apps · Prototype v2.0")
    return profile


def topbar(store: Store, profile: dict) -> None:
    offline = store.setting("offline", True)
    color = "#f59e0b" if offline else "#34d399"
    mode = "Offline mode" if offline else "Online demo"
    link = "Unavailable · queued locally" if offline else "Local simulator connected"
    day = mission_day(profile)
    mission = f" &nbsp;·&nbsp; Mission day {day}" if day else ""
    markup(f'<div class="statusbar"><span><strong>{escape(profile["name"])}</strong>{mission}</span><div class="status-right"><span><i class="dot" style="background:{color}"></i>{mode}</span><span><i class="dot" style="background:{color}"></i>Ground link: {link}</span></div></div>')


def vital_inputs(values: dict, *, prefix: str) -> dict:
    labels = {"hr": "Heart rate (bpm)", "sys": "Systolic (mmHg)", "dia": "Diastolic (mmHg)", "temp": "Temperature (°C)", "spo2": "SpO₂ (%)", "sleep": "Sleep (h / night)"}
    columns, entered = st.columns(3), {}
    for index, (key, (low, high)) in enumerate(VALUE_LIMITS.items()):
        value = float(values[key]) if known(values.get(key)) else None
        entered[key] = columns[index % 3].number_input(labels[key], min_value=low, max_value=high, value=value, step=0.1 if key in ("temp", "sleep") else 1.0, format="%.1f" if key in ("temp", "sleep") else "%.0f", key=prefix + "_" + key, placeholder="Not entered", help="Leave blank if unknown. This field is never filled with a demo value.")
    return entered


def create_profile_view(store: Store) -> None:
    st.title("Create your crew profile")
    st.caption("Create your profile with a name and optional personal baselines. Enter current measurements on the Dashboard.")
    with st.form("create_profile_form"):
        a, b = st.columns(2)
        name = a.text_input("Full name", key="create_name", max_chars=100)
        role = b.text_input("Mission role (optional)", key="create_role", max_chars=100)
        age = a.number_input("Age (optional)", min_value=16, max_value=100, value=None, key="create_age")
        blood = b.selectbox("Blood type (optional)", BLOOD_TYPES, format_func=lambda value: value or "Not provided", key="create_blood")
        allergies = st.text_input("Allergies (optional)", key="create_allergies", max_chars=500)
        markup('<div class="small-label">Personal biometric baselines · optional</div>')
        baseline = vital_inputs(empty_values(), prefix="create_baseline")
        if st.form_submit_button("Create profile", key="create_profile_submit", type="primary"):
            try:
                profile = store.create_profile({"name": name.strip(), "role": role.strip(), "age": age, "blood_type": blood, "allergies": allergies.strip(), "baseline": baseline})
            except ValueError as error:
                st.error(str(error))
            else:
                store.set_setting("selected_crew", profile["id"])
                st.session_state["pending_crew_selection"] = profile["id"]
                st.session_state["creating_profile"] = False
                navigate("Dashboard")
                notify("Your profile was created in SQLite. No demo measurements were added.")
                st.rerun()
    with st.expander("Optional demo data"):
        st.caption("Demo profiles and sensor histories are loaded only when you request them. They do not replace your own profiles.")
        if st.button("Load demo mission", key="load_demo"):
            count = store.load_demo()
            st.session_state["creating_profile"] = False
            navigate("Dashboard")
            notify(f"Loaded {count} optional demo profile(s). Existing data was preserved.")
            st.rerun()
    if store.profiles() and st.button("Back to current profile", key="cancel_new_profile"):
        st.session_state["creating_profile"] = False
        navigate("Profile")
        st.rerun()


def metric_cards(vitals: dict, baseline: dict, selected: str) -> None:
    changed, cards = deviations(vitals, baseline), []
    for metric, info in METRICS.items():
        keys = ("sys", "dia") if metric == "bp" else (metric,)
        has_value = any(known(vitals.get(key)) for key in keys)
        if not has_value:
            status, color = "No measurement", "#64748b"
        elif not comparable(vitals, baseline, metric):
            status, color = "Baseline not set", "#8294ac"
        elif metric in changed:
            status, color = "Outside baseline", "#f59e0b"
        else:
            partial = not all(known(vitals.get(key)) and known(baseline.get(key)) for key in keys)
            status, color = ("Partial comparison", "#8294ac") if partial else ("Within baseline", "#34d399")
        raw = metric_value(vitals, metric)
        if not has_value:
            value = "—"
        elif metric == "bp":
            value = escape(raw) + " <small>mmHg</small>"
        else:
            number, unit = raw.split(" ", 1)
            value = escape(number) + " <small>" + escape(unit) + "</small>"
        cards.append(f'<div class="metric-card {"selected" if metric == selected else ""}"><div class="metric-title">{escape(info["label"])}<span class="metric-symbol">{info["symbol"]}</span></div><div class="metric-value">{value}</div><div class="metric-baseline">Baseline: {escape(metric_value(baseline, metric))}</div><div class="metric-status" style="color:{color}"><i class="dot" style="background:{color}"></i>{status}</div></div>')
    markup('<div class="metrics-grid">' + "".join(cards) + "</div>")


def data_used(profile: dict, vitals: dict, sleep_average: float | None) -> None:
    with st.container(key="data_used"):
        markup('<div class="small-label">Data used in this analysis</div>')
        rows = [(info["label"], metric_value(vitals, metric)) for metric, info in METRICS.items()]
        rows += [("Sleep · recent nights", display_number(sleep_average, 1, " h avg")), ("Medications", profile.get("medications") or "—"), ("Allergies", profile.get("allergies") or "—")]
        for label, value in rows:
            markup(f'<div class="data-row"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>')
        if vitals.get("timestamp"):
            st.caption(f"Sample: {parse_time(vitals['timestamp']):%d %b %Y · %H:%M UTC}\n\n{vitals.get('source') or 'Recorded measurement'}")
        else:
            st.caption("No measurements entered. Symptom-only analysis is available; missing values are not assumed normal.")


def dashboard(store: Store, profile: dict) -> None:
    crew_id, baseline = profile["id"], profile["baseline"]
    title, action = st.columns([3, 1])
    with title:
        st.title("Health overview")
        st.caption("Your latest recorded measurements and personal baselines.")
    with action:
        st.button("Check symptoms", type="primary", width="stretch", shortcut="Ctrl+K", on_click=navigate, args=("Symptom Check",))
    readings_panel = st.container()
    with st.expander("Enter current measurements", expanded=True):
        with st.form("manual_telemetry_" + crew_id, clear_on_submit=False):
            st.caption("Review all fields before saving a new measurement. Leave unknown values blank.")
            entered = vital_inputs(empty_values(), prefix="manual_" + crew_id)
            if st.form_submit_button("Save measured vitals", key="save_measured_vitals", type="primary"):
                try:
                    store.add_sample(crew_id, entered)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success("Measurements saved to SQLite.")

    vitals, frame = store.latest_vitals(crew_id), store.telemetry(crew_id)
    with readings_panel:
        changed = deviations(vitals, baseline)
        compared = sum(comparable(vitals, baseline, metric) for metric in METRICS)
        if changed:
            summary = f"{len(changed)} deviations detected: " + ", ".join(METRICS[key]["label"] for key in changed)
        elif compared:
            summary = f"No deviations in {compared} available metric comparison(s)"
        else:
            summary = "Enter your baseline and current readings to compare your health metrics"
        markup(f'<div class="deviation-banner"><div class="small-label">Deviations from personal baseline</div><strong>{escape(summary)}</strong></div>')
        with st.expander("Review deviations"):
            for metric in changed:
                st.write(f"**{METRICS[metric]['label']}:** {metric_value(vitals, metric)} · baseline {metric_value(baseline, metric)}")
            st.caption(f"{compared}/5 metrics can be compared. Missing baselines or measurements are shown as —. Reference widths: HR ±10 bpm, BP ±15/10 mmHg, temperature ±0.6 °C, SpO₂ ±2 points, sleep ±1.5 h. Absolute escalation rules remain separate.")
        metric_cards(vitals, baseline, st.session_state.get("trend_metric", "hr"))
        screening = assess(profile, vitals, {"description": "", "pain": None, "duration_hours": None, "red_flags": [], "kind": "routine"})
        if screening["severity_index"] == 3:
            st.error("Critical telemetry detected. Alert the crew medical officer and activate the onboard emergency protocol now.")
            st.button("Open emergency protocol", key="critical_telemetry_emergency", type="primary", on_click=trigger_emergency, args=(store, crew_id, "Critical telemetry detected on Dashboard"))
        if screening["telemetry_stale"]:
            st.warning("The last recorded measurement is older than 6 hours. Enter fresh measurements before relying on it.")
    with st.container(key="trend_panel"):
        markup('<div class="small-label">Trends vs. personal baseline</div>')
        controls, periods = st.columns([4, 1.5])
        metric = controls.segmented_control("Metric", list(METRICS), key="trend_metric", default="hr", required=True, format_func=lambda key: METRICS[key]["label"], label_visibility="collapsed")
        period = periods.segmented_control("Time window", ["24h", "3d", "7d"], key="trend_period", default="3d", required=True, label_visibility="collapsed")
        projection = st.checkbox("Show 6h trend projection", key="trend_projection", help="Requires at least 3 readings in the latest 24 hours. Illustrative linear extrapolation, not a validated clinical forecast.")
        st.plotly_chart(make_chart(frame, baseline, metric, period, projection), width="stretch", theme=None, config={"displaylogo": False, "scrollZoom": False}, key="vitals_plot")
        st.caption("Only recorded measurements are plotted. A baseline band appears only when you have entered that personal reference value.")
    wellness, sleep_avg = store.wellbeing(crew_id), sleep_average_3d(frame)
    columns = st.columns(3)
    cards = [("Sleep · recent nights", display_number(sleep_avg, 1, " h"), "Personal target: " + metric_value(baseline, "sleep")), ("Stress · self-report", display_number(wellness["stress"], 0, "/10"), "Mood: " + (wellness["mood"] or "—")), ("Activity", display_number(wellness["activity"], 0, " min"), "Recorded date: " + (wellness["day"] or "—"))]
    for column, (label, value, caption) in zip(columns, cards):
        with column:
            with st.container(border=True):
                markup(f'<div class="small-label">{escape(label)}</div><div style="font-size:23px;font-weight:650;color:#e2e8f0">{escape(value)}</div>')
                st.caption(caption)
    with st.expander("Daily wellbeing & activity check-in"):
        with st.form("wellbeing_form_" + crew_id):
            a, b, c = st.columns(3)
            stress = a.number_input("Stress level", 0, 10, wellness["stress"], key="wellbeing_stress_" + crew_id)
            mood = b.selectbox("Mood", ["", "Good", "Neutral", "Low"], index=["", "Good", "Neutral", "Low"].index(wellness["mood"] or ""), format_func=lambda value: value or "Not entered")
            activity = c.number_input("Exercise today (min)", 0, 360, wellness["activity"], step=5)
            if st.form_submit_button("Save check-in", key="save_wellbeing", type="primary"):
                try:
                    store.save_wellbeing(crew_id, stress, mood, activity)
                except ValueError as error:
                    st.error(str(error))
                else:
                    notify("Wellbeing check-in saved in SQLite.")
                    st.rerun()
    with st.expander("Crew overview"):
        rows = []
        for person in store.profiles():
            reference = person["baseline"]
            sample = store.latest_vitals(person["id"])
            rows.append({
                "Crew member": person["name"], "Role": person["role"] or "—",
                "Heart rate": metric_value(sample, "hr"), "SpO₂": metric_value(sample, "spo2"),
                "Sleep": metric_value(sample, "sleep"),
                "Source": sample["source"] or "No measurement",
                "Baseline comparisons": sum(comparable(sample, reference, metric) for metric in METRICS),
                "Deviations": len(deviations(sample, reference)),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    reports = store.reports(crew_id, saved_only=False)
    ground_panel(store, crew_id, reports[0] if reports else None)


def persist_symptom_field(store: Store, crew_id: str, field: str) -> None:
    draft = store.draft(crew_id)
    draft[field] = st.session_state["symptom_" + field + "_" + crew_id]
    store.save_draft(crew_id, draft)


def clear_symptoms(store: Store, crew_id: str) -> None:
    store.clear_draft(crew_id)
    for field, value in empty_draft().items():
        st.session_state["symptom_" + field + "_" + crew_id] = value
    st.session_state["show_result_" + crew_id] = False
    st.session_state.pop("assessment_" + crew_id, None)
    notify("Symptoms cleared in SQLite. All inputs are blank; existing reports remain in the health log.")


def clear_baseline_inputs(store: Store, crew_id: str) -> None:
    store.clear_baseline(crew_id)
    for key in VALUE_KEYS:
        st.session_state["baseline_" + crew_id + "_" + key] = None
    notify("All personal baseline values were cleared in SQLite. No demo values were substituted.")


def dictate(store: Store, crew_id: str) -> None:
    draft = {**empty_draft(), "description": "Тупая головная боль в области лба около четырёх часов, лёгкое головокружение при повороте головы. Последние ночи плохо сплю.", "location": "Лоб / голова", "duration": 4.0, "pain": 4, "quality": "Dull", "course": "Constant", "onset": "Gradual", "trigger": "Head movement"}
    store.save_draft(crew_id, draft, explicit=True)
    for field, value in draft.items():
        st.session_state["symptom_" + field + "_" + crew_id] = value
    notify("An editable dictation example was inserted and saved locally. No microphone service was used.")


def symptom_check(store: Store, profile: dict) -> None:
    crew_id = profile["id"]
    selected = st.session_state.get("assessment_" + crew_id)
    if selected and st.session_state.get("show_result_" + crew_id, False):
        report = store.report(selected)
        if report and report["crew_id"] == crew_id:
            assessment_view(store, report)
            return
    st.title("Symptom check")
    st.caption("Your symptom draft is saved to SQLite as each field is committed, including when working offline.")
    markup('<div style="border:1px solid #fb718544;background:#fb718506;border-radius:12px;padding:13px 18px;font-size:12px;line-height:1.6">Chest pain, trouble breathing, loss of consciousness or severe bleeding: press <strong style="color:#fb7185">Emergency · Ctrl+E</strong> immediately.</div>')
    left, right = st.columns([2.15, 1], gap="large")
    vitals, sleep_avg = store.latest_vitals(crew_id), sleep_average_3d(store.telemetry(crew_id))
    with right:
        data_used(profile, vitals, sleep_avg)
        st.caption("You can analyze symptoms without a complete baseline. Missing values remain unknown and are listed in the result.")
    with left:
        markup('<div class="chat-prompt">Describe what you feel: <strong>what, where, and since when.</strong><br>Add pain intensity and context if known. Nothing is prefilled from another account.</div>')
        buttons = st.columns(2)
        buttons[0].button("Dictate · simulation", key="dictate", on_click=dictate, args=(store, crew_id), width="stretch")
        buttons[1].button("Clear symptoms", key="clear_symptoms", on_click=clear_symptoms, args=(store, crew_id), width="stretch")
        draft = store.draft(crew_id)
        for field, value in empty_draft().items():
            st.session_state.setdefault("symptom_" + field + "_" + crew_id, draft.get(field, value))
        def arguments(field: str) -> dict:
            return {"key": "symptom_" + field + "_" + crew_id, "on_change": persist_symptom_field, "args": (store, crew_id, field)}
        with st.container(key="symptom_form"):
            st.text_area("What do you feel? / Опишите жалобы", height=115, max_chars=4000, placeholder="Enter your own symptoms…", **arguments("description"))
            st.text_input("Where? / Локализация", max_chars=160, **arguments("location"))
            a, b, c = st.columns([1, 1, 1.4])
            a.number_input("How long?", min_value=0.0, max_value=10000.0, value=None, step=0.5, **arguments("duration"))
            b.selectbox("Time unit", ["Minutes", "Hours", "Days"], **arguments("unit"))
            c.number_input("Pain intensity (0-10)", min_value=0, max_value=10, value=None, step=1, **arguments("pain"))
            a, b = st.columns(2)
            a.selectbox("Pain character", ["", "No pain", "Dull", "Throbbing", "Sharp", "Pressure", "Burning", "Other"], format_func=lambda value: value or "Not entered", **arguments("quality"))
            b.selectbox("Symptom course", ["", "Constant", "Comes and goes", "Not sure"], format_func=lambda value: value or "Not entered", **arguments("course"))
            a, b = st.columns(2)
            a.selectbox("Onset", ["", "Gradual", "Sudden", "Not sure"], format_func=lambda value: value or "Not entered", **arguments("onset"))
            b.selectbox("Progression", ["", "Improving", "Unchanged", "Worsening"], format_func=lambda value: value or "Not entered", **arguments("progression"))
            st.selectbox("Related activity / trigger", ["", "After exercise", "Head movement", "After standing", "After meals", "No clear trigger"], format_func=lambda value: value or "Not entered", **arguments("trigger"))
            st.multiselect("Emergency signs present now", RED_FLAGS, help="Select every applicable sign and activate Emergency immediately if present.", **arguments("red_flags"))
            current = {field: st.session_state["symptom_" + field + "_" + crew_id] for field in empty_draft()}
            store.save_draft(crew_id, current)
            detected = list(dict.fromkeys(current["red_flags"] + detect_red_flags(current["description"] + ". " + current["location"])))
            if detected:
                st.error("Emergency signs detected: " + ", ".join(detected) + ". Activate Emergency now.")
                st.button("Activate emergency now", type="primary", key="symptom_emergency", on_click=trigger_emergency, args=(store, crew_id, "Reported symptoms: " + ", ".join(detected)))
            a, b = st.columns([1, 1.7])
            if a.button("Save symptom draft", key="save_symptom_draft", width="stretch"):
                store.save_draft(crew_id, current, explicit=True)
                st.success("Draft saved in the SQLite file.")
            if b.button("Run AI assessment →", type="primary", key="run_assessment", width="stretch"):
                if len(current["description"].strip()) < 5 and not detected:
                    st.error("Describe your symptoms in at least 5 characters, or select a present emergency sign.")
                else:
                    store.save_draft(crew_id, current, explicit=True)
                    hours = current["duration"] * {"Minutes": 1 / 60, "Hours": 1, "Days": 24}[current["unit"]] if current["duration"] is not None else None
                    symptoms = {**current, "description": current["description"].strip(), "location": current["location"].strip(), "duration_hours": hours}
                    report = assess(profile, vitals, symptoms, sleep_average=sleep_avg)
                    store.add_report(report)
                    st.session_state["assessment_" + crew_id] = report["id"]
                    st.session_state["show_result_" + crew_id] = True
                    st.rerun()
        saved_at = store.draft(crew_id).get("updated_at")
        if saved_at:
            st.caption(f"SQLite draft · saved {parse_time(saved_at):%d %b %Y %H:%M:%S UTC}")
        st.caption("Local evidence-composed rules · no external API. Recognized phrases, data gaps and reasons are visible in the result.")


@st.dialog("Delete profile?")
def confirm_profile_deletion(store: Store, profile: dict) -> None:
    crew_id = profile["id"]
    st.text(profile["name"])
    st.warning("This permanently deletes the profile, its measurements, symptom drafts, reports and logs from the local database.")
    cancel, confirm = st.columns(2)
    if cancel.button("Cancel", key="cancel_profile_deletion", width="stretch"):
        st.rerun()
    if confirm.button("Confirm deletion", key="confirm_profile_deletion", type="primary", width="stretch"):
        try:
            store.delete_profile(crew_id)
        except ValueError as error:
            st.error(str(error))
        except sqlite3.Error:
            st.error("The profile could not be deleted. Try again.")
        else:
            st.session_state.pop("assessment_" + crew_id, None)
            st.session_state.pop("show_result_" + crew_id, None)
            notify("Profile and its related records were deleted from SQLite.")
            st.rerun()


def profile_view(store: Store, profile: dict) -> None:
    st.title("Astronaut medical profile")
    st.caption("Edit your personal details and baselines. Enter current measurements on the Dashboard.")
    a, b = st.columns([1, 2.1], gap="large")
    crew_id = profile["id"]
    with a:
        with st.container(key="profile_card"):
            initials = "".join(part[0] for part in profile["name"].split()[:2])
            markup(f'<div class="profile-avatar">{escape(initials)}</div>')
            st.subheader(profile["name"])
            if profile["role"]:
                st.caption(profile["role"])
            rows = [("Age", display_number(profile["age"], 0, " years")), ("Blood type", profile["blood_type"] or "—"), ("Allergies", profile["allergies"] or "—")]
            for label, value in rows:
                markup(f'<div class="data-row"><span>{escape(label)}</span><strong>{escape(value)}</strong></div>')
            st.caption(("Optional demo profile" if profile["is_demo"] else "Personal profile") + f" · updated {parse_time(profile['updated_at']):%d %b %Y %H:%M UTC}")
        st.button("Clear all baseline values", key="clear_baseline", on_click=clear_baseline_inputs, args=(store, crew_id), width="stretch")
        st.caption("Clearing the baseline updates SQLite immediately. Existing reports retain their original snapshots.")
        st.button("Create another profile", key="create_another_profile", on_click=request_new_profile, width="stretch")
        last_profile = len(store.profiles()) <= 1
        if st.button("Delete profile", key="delete_profile", disabled=last_profile, width="stretch"):
            confirm_profile_deletion(store, profile)
        if last_profile:
            st.caption("The last profile cannot be deleted.")
    with b:
        with st.form("profile_form_" + crew_id):
            c, d = st.columns(2)
            name = c.text_input("Full name", profile["name"], max_chars=100, key="profile_name_" + crew_id)
            role = d.text_input("Mission role", profile["role"], max_chars=100, key="profile_role_" + crew_id)
            age = c.number_input("Age", min_value=16, max_value=100, value=int(profile["age"]) if known(profile["age"]) else None, key="profile_age_" + crew_id)
            blood = d.selectbox("Blood type", BLOOD_TYPES, index=BLOOD_TYPES.index(profile["blood_type"]) if profile["blood_type"] in BLOOD_TYPES else 0, format_func=lambda value: value or "Not provided")
            allergies = st.text_input("Allergies", profile["allergies"], max_chars=500, key="profile_allergies_" + crew_id)
            st.subheader("Personal Medical Baseline (Reference Values)")
            st.caption("Эти значения являются персональной базовой нормой астронавта, с которой ИИ сравнивает текущие симптомы и замеры.")
            baseline = vital_inputs(profile["baseline"], prefix="baseline_" + crew_id)
            if st.form_submit_button("Update profile & baseline", key="save_profile", type="primary"):
                updated = {**profile, "name": name.strip(), "role": role.strip(), "age": age, "blood_type": blood, "allergies": allergies.strip(), "baseline": baseline}
                try:
                    store.update_profile(updated)
                except ValueError as error:
                    st.error(str(error))
                else:
                    notify("Profile, optional baselines and the action log were committed to SQLite.")
                    st.rerun()


def health_log(store: Store, profile: dict) -> None:
    st.title("Health log")
    st.caption("Saved reports, persistent symptom drafts and the SQLite activity trail.")
    report_tab, action_tab = st.tabs(["Health reports", "Activity log"])
    crew_id = profile["id"]
    with report_tab:
        reports = store.reports(crew_id)
        unsaved = [report for report in store.reports(crew_id, saved_only=False) if not report["saved"]]
        if unsaved:
            with st.expander(f"Recover assessment results · {len(unsaved)}"):
                draft_names = {item["id"]: f"{parse_time(item['created_at']):%d %b %H:%M UTC} · {item['severity']} · {item['symptoms'].get('description', '')[:55]}" for item in unsaved}
                selected_draft = st.selectbox("Recover result", list(draft_names), format_func=lambda value, labels=draft_names: labels[value], key="recover_draft")
                if st.button("Open recovered result", key="open_recovered"):
                    st.session_state["assessment_" + crew_id] = selected_draft
                    st.session_state["show_result_" + crew_id] = True
                    navigate("Symptom Check")
                    st.rerun()
        a, b, c = st.columns([2.2, 1.5, 1.5])
        search = a.text_input("Search symptoms", key="log_search", placeholder="Search your records…")
        severity = b.selectbox("Severity", ["All"] + list(SEVERITIES), key="log_severity")
        earliest = min((parse_time(report["created_at"]).date() for report in reports), default=utc_now().date())
        dates = c.date_input("UTC date range", value=(earliest, utc_now().date()), key="log_dates")
        dates = dates if isinstance(dates, (tuple, list)) else (dates, dates)
        filtered = [report for report in reports if len(dates) == 2 and dates[0] <= parse_time(report["created_at"]).date() <= dates[1] and (severity == "All" or report["severity"] == severity) and search.casefold() in report["symptoms"].get("description", "").casefold()]
        if filtered:
            rows = [{"Recorded (UTC)": parse_time(report["created_at"]).strftime("%d %b %Y %H:%M"), "Event / symptoms": report["symptoms"].get("description", ""), "Severity": report["severity"], "Heart rate": metric_value(report["vitals"], "hr"), "Blood pressure": metric_value(report["vitals"], "bp"), "Ground sync": "Delivered · simulator" if report["sync_status"] == "delivered_demo" else report["sync_status"]} for report in filtered]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", row_height=56)
            saved_names = {item["id"]: f"{parse_time(item['created_at']):%d %b %H:%M} · {item['severity']} · {item['symptoms'].get('description', '')[:55]}" for item in filtered}
            selected_id = st.selectbox("Select a saved report", list(saved_names), format_func=lambda value, labels=saved_names: labels[value], key="log_selected")
            selected = next(report for report in filtered if report["id"] == selected_id)
            buttons = st.columns(3)
            if buttons[0].button("Open assessment", key="open_saved", width="stretch"):
                st.session_state["assessment_" + crew_id] = selected_id
                st.session_state["show_result_" + crew_id] = True
                navigate("Symptom Check")
                st.rerun()
            buttons[1].download_button("Download selected .md", report_markdown(selected), file_name=f"astroguard_{selected_id[:8]}.md", mime="text/markdown", width="stretch")
            buttons[2].button("Send selected to ground", key="send_saved", width="stretch", on_click=send_report, args=(store, selected))
        else:
            st.info("No saved reports match these filters. Assess your symptoms and choose Save to health log.")
        archive = {"application": APP_NAME, "schema_version": 2, "exported_at": iso_time(), "profile": profile, "symptom_draft": store.draft(crew_id), "reports": store.reports(crew_id, saved_only=False), "telemetry": json.loads(store.telemetry(crew_id).to_json(orient="records", date_format="iso")), "activity_log": store.activity(crew_id)}
        st.download_button("Export full medical archive (.json)", json_text(archive), file_name=f"astroguard_{crew_id}_archive.json", mime="application/json", key="export_archive")
        st.caption(f"{len(filtered)} displayed · {len(reports)} saved. The archive also includes persistent drafts, measurements and the action log.")
    with action_tab:
        activity = store.activity(crew_id)
        if activity:
            rows = [{"Recorded (UTC)": parse_time(item["timestamp"]).strftime("%d %b %Y %H:%M:%S"), "Action": item["action"], "Record": item["entity_id"] or "—", "Details": json.dumps(item["details"], ensure_ascii=False)} for item in activity]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        else:
            st.info("Actions performed with this version will appear here. Existing medical reports are preserved.")
        st.caption("Data source: local SQLite file")
        st.code(str(store.path.resolve()), language=None)


def scroll_on_view_change(crew_id: str) -> None:
    """Open a new screen at its heading, while preserving scroll on ordinary edits."""
    result = st.session_state.get("assessment_" + crew_id) if st.session_state.get("show_result_" + crew_id) else None
    signature = (crew_id, st.session_state["page"], result if st.session_state["page"] == "Symptom Check" else None)
    if st.session_state.get("previous_view") != signature:
        st.session_state["previous_view"] = signature
        # Static trusted script only. User data never enters executable HTML.
        st.html("""<script>
            requestAnimationFrame(() => {
                document.querySelector('[data-testid="stMain"]')?.scrollTo(0, 0);
                window.scrollTo(0, 0);
            });
        </script>""", unsafe_allow_javascript=True)


def ground_panel(store: Store, crew_id: str, report: dict | None = None) -> None:
    with st.container(key="ground_panel"):
        left, right = st.columns([3, 1])
        with left:
            markup('<div class="small-label">Ground communication</div>')
            st.markdown("**Mission Control · local receiver**")
            st.caption("Offline reports persist in SQLite. Restoring the demo link delivers the queue once, with a local acknowledgement.")
        with right:
            transmissions = store.transmissions(crew_id)
            queued = sum(item["status"] == "queued" for item in transmissions)
            markup(f'<div class="small-label">Pending reports</div><div style="font-size:29px;color:#f59e0b;font-weight:650">{queued:02d}</div>')
        if report:
            st.button("Send summary to ground", key="ground_send", on_click=send_report, args=(store, report), type="primary")
        if transmissions:
            rows = [{"Report": item["report_id"][:8], "Queued (UTC)": parse_time(item["queued_at"]).strftime("%d %b %H:%M"), "Status": "Queued offline" if item["status"] == "queued" else "Delivered · simulator", "Received (UTC)": parse_time(item["delivered_at"]).strftime("%d %b %H:%M") if item["delivered_at"] else "—"} for item in transmissions[:8]]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            acknowledgement = next((item["acknowledgement"] for item in transmissions if item["acknowledgement"]), None)
            if acknowledgement:
                st.caption(acknowledgement)
        else:
            st.caption("No reports transmitted for this crew member yet. Complete a symptom check to create a summary.")


def assessment_view(store: Store, report: dict) -> None:
    crew_id = report["crew_id"]
    left, right = st.columns([3, 1])
    with left:
        st.title("Assessment result")
        st.caption("Decision support only. Not a diagnosis. Local rules · qualitative causes.")
    with right:
        if st.button("Edit symptoms", key="edit_symptoms", width="stretch"):
            st.session_state["show_result_" + crew_id] = False
            st.rerun()
    markup('<div class="small-label">Severity</div>')
    cards = []
    for index, (label, color) in enumerate(zip(SEVERITIES, SEVERITY_COLORS)):
        style = f"border-color:{color};background:{color}0c;color:{color};font-weight:650" if index == report["severity_index"] else ""
        cards.append(f'<div class="severity-card" style="{style}"><i class="dot" style="background:{color};flex-shrink:0"></i>{label}</div>')
    markup('<div class="severity-grid">' + "".join(cards) + "</div>")
    if report["severity_index"] == 3:
        st.error("Activate onboard emergency procedures now. This application cannot issue a distress call or command evacuation.")
        st.button("Open emergency protocol", key="assessment_emergency", type="primary", on_click=trigger_emergency, args=(store, crew_id, "Assessment red flags / critical telemetry"))
    st.caption("Assessment rationale: " + " · ".join(report["reasons"]))
    coverage = report.get("coverage")
    if coverage:
        st.caption(f"Data coverage: {coverage['measured']}/{coverage['total']} measured values · {coverage['baseline']}/{coverage['total']} personal baseline values. Missing values were not assumed normal.")
    if report.get("recognized_symptoms"):
        st.caption("Recognized symptoms: " + " · ".join(item["label"] for item in report["recognized_symptoms"]))
    if report.get("data_gaps"):
        with st.expander("Missing data & recognized evidence"):
            st.write("Missing: " + ", ".join(report["data_gaps"]))
            for item in report.get("recognized_symptoms", []):
                st.text(item["label"] + ": " + ", ".join(item["evidence"]))
    a, b = st.columns([2.1, 1], gap="large")
    with a:
        with st.container(key="recommendations"):
            markup('<div class="small-label" style="color:#2dd4bf">Recommendations</div>')
            for index, recommendation in enumerate(report["recommendations"], 1):
                markup(f'<div class="recommendation"><span>{index:02d}</span><div>{escape(recommendation)}</div></div>')
        with st.expander("Symptoms & medical context"):
            st.text(report["symptoms"].get("description") or "—")
            st.caption(f"Location: {report['symptoms'].get('location') or '—'} · Duration: {display_number(report['symptoms'].get('duration_hours'), 1, ' h')} · Pain: {display_number(report['symptoms'].get('pain'), 0, '/10')}")
            st.write("**Allergies:** " + (report["profile"].get("allergies") or "Not supplied"))
            st.write("**Medications:** " + (report["profile"].get("medications") or "Not supplied"))
    with b:
        with st.container(key="causes"):
            markup('<div class="small-label">Possible causes</div>')
            for cause in report["possible_causes"]:
                markup(f'<div class="cause"><span class="cause-badge">{escape(cause["likelihood"])}</span>{escape(cause["name"])}<small>{escape(cause["reason"])}</small></div>')
        with st.container(key="findings"):
            markup('<div class="small-label">Data findings</div>')
            for finding in sorted(report["findings"], key=lambda item: not item["deviation"]):
                color = "#f59e0b" if finding["deviation"] else "#94a3b8"
                markup(f'<div style="font-size:12px;line-height:1.7;padding:7px 0;color:{color}">{escape(finding["text"])}</div>')
            if report.get("sleep_average_3d") is not None:
                st.caption(f"Sleep, last 3 nights: {report['sleep_average_3d']:.1f} h avg")
    actions = st.columns([1.4, 1.2, 1, 1])
    with actions[0]:
        st.button("Send summary to ground", key="assessment_send", type="primary", width="stretch", on_click=send_report, args=(store, report))
    with actions[1]:
        if st.button("Save to health log", key="save_assessment", width="stretch"):
            store.save_report(report["id"])
            st.success("Saved to the local health log.")
    with actions[2]:
        st.download_button("Report .md", report_markdown(report), file_name=f"astroguard_{report['id'][:8]}.md", mime="text/markdown", width="stretch")
    with actions[3]:
        st.download_button("Report .json", json_text(report), file_name=f"astroguard_{report['id'][:8]}.json", mime="application/json", width="stretch")
    st.caption(f"Assessment {report['id'][:8]} · {parse_time(report['created_at']):%d %b %Y %H:%M UTC}. Reports preserve the baseline and measurements captured at assessment time.")
    with st.expander("How this assessment works & source references"):
        st.write("Red flags and absolute sensor limits take priority over personal baseline deviations. Pain ≥7/10, symptoms ≥24 h, stale telemetry, or three baseline deviations request ground review. Moderate pain or multiple deviations request onboard care. Other cases remain under observation. These engineering rules are illustrative and have not been clinically validated.")
        st.write("The engine composes recommendations and ranked cause hypotheses from recognized RU/EN symptom groups, measured corroboration, pain, duration, onset, progression and triggers. Results are reproducible, not randomized. Empty fields never borrow demo values. Negation and suffixes are handled by local language rules; this is not unrestricted clinical language understanding.")
        st.write("The following references describe general emergency warning signs. They do not validate the demo's sensor thresholds or spaceflight protocols.")
        for source in SOURCES:
            st.markdown(f"[{source['title']}]({source['url']})")
    st.button("Start a blank symptom check", key="start_blank_check", on_click=clear_symptoms, args=(store, crew_id))
    with st.expander("Ground communication status"):
        ground_panel(store, crew_id)


def emergency_view(store: Store, profile: dict) -> None:
    st.title("Emergency protocol")
    st.caption("Priority 1 · onboard assistance first · crew-operated demo")
    active_id = store.setting("active_emergency_" + profile["id"])
    report = store.report(active_id) if active_id else None
    if not report:
        st.warning("No active incident for this crew member.")
        st.button("Activate priority 1", key="activate_emergency", type="primary", on_click=trigger_emergency, args=(store, profile["id"]))
        return
    st.error("EMERGENCY MODE ACTIVE · " + profile["name"])
    st.caption(f"Incident {report['id'][:8]} · activated {parse_time(report['created_at']):%d %b %Y %H:%M UTC}. Activation is recorded locally; no hardware, intercom or real distress channel is connected.")
    a, b = st.columns([2, 1], gap="large")
    with a:
        with st.container(key="recommendations"):
            markup('<div class="small-label" style="color:#fb7185">Immediate onboard actions</div>')
            for index, recommendation in enumerate(report["recommendations"], 1):
                markup(f'<div class="recommendation"><span style="color:#fb7185">{index:02d}</span><div>{escape(recommendation)}</div></div>')
        st.caption("Use the mission's approved medical procedures. This educational interface does not replace trained crew or the flight surgeon.")
        if st.button("Close incident after crew review", key="close_incident"):
            store.set_setting("active_emergency_" + profile["id"], None)
            store.set_setting("incident_closed_" + report["id"], iso_time())
            store.audit(profile["id"], "emergency_closed", report["id"])
            notify("Incident closed locally. The emergency report and its transmission history remain in the health log.")
            navigate("Health Log")
            st.rerun()
    with b:
        data_used(report["profile"], report["vitals"], report.get("sleep_average_3d"))
        st.download_button("Download emergency brief", report_markdown(report), file_name=f"emergency_{report['id'][:8]}.md", mime="text/markdown", width="stretch")
    ground_panel(store, profile["id"], report)


def main() -> None:
    configure_native_theme()
    st.set_page_config(page_title="AstroGuard AI · Crew Health", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
    st.html(CSS)
    st.session_state.setdefault("page", "Dashboard")
    store = Store()
    try:
        store.initialize()
        store.sync_queue()
        profile = sidebar(store, store.profiles())
        notice = st.session_state.pop("notice", None)
        if notice:
            st.info(notice)
        if profile is None or st.session_state.get("creating_profile", False):
            create_profile_view(store)
        else:
            scroll_on_view_change(profile["id"])
            topbar(store, profile)
            page = st.session_state["page"]
            views = {"Dashboard": dashboard, "Symptom Check": symptom_check, "Health Log": health_log, "Profile": profile_view, "Emergency": emergency_view}
            views.get(page, dashboard)(store, profile)
        markup('<div class="footer-note">ASTROGUARD AI &nbsp; / &nbsp; NASA SPACE APPS CHALLENGE MVP<br>Your own profiles · persistent SQLite drafts and reports · explainable local assessment · simulated ground receiver. Educational decision support only.</div>')
    except (sqlite3.Error, OSError) as error:
        st.error("Local storage is unavailable. Check that the SQLite file and its directory are writable and the database is not locked.")
        st.code(str(error), language=None)
        st.caption("Set ASTROGUARD_DB to a writable local SQLite file and restart Streamlit.")


if __name__ == "__main__":
    main()
