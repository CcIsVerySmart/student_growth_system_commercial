"""intent_detector.py

Detects student goal/intent from free text and computes a small intent_bonus
that nudges path scores toward the student's stated direction.

Design principles:
- intent_bonus is capped at 8 points per path to avoid overriding capability scores.
- Only applied when the student has relevant capability (engineering_practice >= 30
  for employment, academic_foundation >= 60 for postgrad, etc.).
- Fallback policy (考研/考公 suppression) is applied AFTER intent_bonus.
"""
from __future__ import annotations

# ── Intent categories and their keyword sets ──────────────────────────────

INTENT_RULES: list[tuple[str, list[str]]] = [
    ("保研/推免", [
        "保研", "推免", "夏令营", "直博", "推荐免试", "保研名额",
        "申请保研", "希望保研", "想保研",
    ]),
    ("考研/读研", [
        "考研", "读研", "硕士", "研究生", "考研复习", "备考",
        "希望读研", "想考研", "打算考研", "准备考研",
    ]),
    ("就业/实习", [
        "就业", "找工作", "入职", "企业", "互联网", "后端", "算法岗",
        "开发岗", "实习", "暑期实习", "企业实习", "毕业后工作",
        "希望就业", "想就业", "打算就业", "毕业就业",
        "希望毕业后就业", "希望找工作",
    ]),
    ("考公/选调", [
        "考公", "公务员", "事业单位", "选调", "选调生", "国考", "省考",
        "希望考公", "想考公",
    ]),
    ("基层/支教/辅导员", [
        "基层", "支教", "辅导员", "学生工作", "三支一扶",
        "西部计划", "志愿服务", "社会实践",
        "希望做辅导员", "考虑辅导员", "基层方向",
    ]),
]

# ── Path bonus mapping ─────────────────────────────────────────────────────
# Maps intent → {path: bonus_points}
# Bonus is only applied when capability guard is satisfied.

_INTENT_BONUS_MAP: dict[str, dict[str, float]] = {
    "保研/推免": {
        "普通推免": 6.0,
        "特殊专长A类": 4.0,
        "特殊专长B/本硕博": 4.0,
        "考研": 2.0,
    },
    "考研/读研": {
        "考研": 6.0,
        "普通推免": 2.0,
        "特殊专长B/本硕博": 2.0,
    },
    "就业/实习": {
        "实习就业": 8.0,
        "工程专项/专硕": 3.0,
    },
    "考公/选调": {
        "考公": 7.0,
        "支教计划": 2.0,
    },
    "基层/支教/辅导员": {
        "特殊专长C/辅导员计划": 7.0,
        "支教计划": 7.0,
        "考公": 3.0,
    },
}

# Capability guards: intent is only applied when the student meets a minimum
# score on the relevant dimension.
_CAPABILITY_GUARDS: dict[str, tuple[str, float]] = {
    "保研/推免": ("academic_foundation", 60.0),
    "考研/读研": ("academic_foundation", 55.0),
    "就业/实习": ("engineering_practice", 25.0),  # low bar — even 1 project counts
    "考公/选调": ("academic_foundation", 50.0),
    "基层/支教/辅导员": ("organization_service", 20.0),
}


def _build_intent_text(profile: dict) -> str:
    """Aggregate all text fields relevant to intent detection."""
    parts = [
        str(profile.get("target") or ""),
        str(profile.get("self_description") or ""),
        str(profile.get("path_type") or ""),
        str(profile.get("final_destination") or ""),
        str(profile.get("destination") or ""),
        str(profile.get("意向") or ""),
        str(profile.get("发展目标") or ""),
        str(profile.get("备注") or ""),
        str(profile.get("internships") or ""),
        str(profile.get("student_work") or ""),
        str(profile.get("competitions") or ""),
        str(profile.get("research_experiences") or ""),
        str(profile.get("projects") or ""),
    ]
    return " ".join(p for p in parts if p and p not in ("None", "[]", "{}"))


def detect_intents(profile: dict) -> list[str]:
    """Return a list of detected intent categories for the student."""
    text = _build_intent_text(profile)
    detected = []
    for intent, keywords in INTENT_RULES:
        if any(kw in text for kw in keywords):
            detected.append(intent)
    return detected


def compute_intent_bonus(
    detected_intents: list[str],
    six_dim_scores: dict[str, float],
) -> dict[str, float]:
    """Compute per-path intent bonus points.

    Returns a dict mapping path name → bonus (0–8).
    Only applies bonus when the capability guard is satisfied.
    """
    bonus: dict[str, float] = {}
    for intent in detected_intents:
        guard_dim, guard_min = _CAPABILITY_GUARDS.get(intent, ("academic_foundation", 0.0))
        guard_val = float(six_dim_scores.get(guard_dim) or 0)
        if guard_val < guard_min:
            continue  # capability guard not met — skip this intent
        for path, pts in _INTENT_BONUS_MAP.get(intent, {}).items():
            bonus[path] = min(8.0, bonus.get(path, 0.0) + pts)
    return bonus


def apply_intent_bonus(
    path_scores: dict[str, float],
    intent_bonus: dict[str, float],
) -> dict[str, float]:
    """Apply intent bonus to path scores, capping each at 100."""
    result = dict(path_scores)
    for path, pts in intent_bonus.items():
        if path in result:
            result[path] = min(100.0, round(result[path] + pts, 2))
    return result


def run_intent_analysis(
    profile: dict,
    six_dim_scores: dict[str, float],
    path_scores: dict[str, float],
) -> dict:
    """Full intent analysis pipeline.

    Returns:
        intent_analysis dict with detected_intents, applied_bonus, adjusted_scores,
        and a human-readable explanation.
    """
    detected = detect_intents(profile)
    bonus = compute_intent_bonus(detected, six_dim_scores)
    adjusted = apply_intent_bonus(path_scores, bonus)

    # Build explanation
    if not detected:
        explanation = "未从学生材料中检测到明确的目标意向，路径评分以六维能力画像为主要依据。"
    else:
        intent_str = "、".join(detected)
        if bonus:
            bonus_str = "；".join(f"{p} +{v:.0f}分" for p, v in bonus.items())
            explanation = (
                f"系统识别到学生具有以下目标意向：{intent_str}。"
                f"在满足相应能力门槛的前提下，对以下路径施加轻微意向修正：{bonus_str}。"
                f"意向修正最多 8 分，不替代六维能力画像和规则评分。"
            )
        else:
            explanation = (
                f"系统识别到学生具有以下目标意向：{intent_str}，"
                f"但相关能力维度尚未达到意向修正门槛，路径评分以六维能力画像为主要依据。"
            )

    return {
        "detected_intents": detected,
        "applied_bonus": bonus,
        "adjusted_scores": adjusted,
        "explanation": explanation,
    }
