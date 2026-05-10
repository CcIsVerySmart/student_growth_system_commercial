from __future__ import annotations
from typing import Any
import re
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from .config import DIMENSIONS
from .job_intelligence import make_company_card, build_external_job_cards
from .scoring import convert_legacy_scores_to_six_dimensions


def vector_from_scores(scores: dict[str, float], dimensions: list[str] | None = None) -> np.ndarray:
    dims = dimensions or DIMENSIONS
    return np.array([float(scores.get(d, 0) or 0) for d in dims], dtype=float)


def weighted_similarity(a: dict[str, float], b: dict[str, float], weights: dict[str, float] | None = None) -> float:
    dims = list((weights or {}).keys()) if weights else DIMENSIONS
    va = vector_from_scores(a, dims)
    vb = vector_from_scores(b, dims)
    if weights:
        w = np.array([weights.get(d, 1.0) for d in dims], dtype=float)
        va = va * w
        vb = vb * w
    if np.linalg.norm(va) == 0 or np.linalg.norm(vb) == 0:
        return 0.0
    return float(cosine_similarity([va], [vb])[0][0])


def jaccard(a: list[Any], b: list[Any]) -> float:
    sa, sb = set(map(str, a or [])), set(map(str, b or []))
    if not sa and not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def path_weights(path: str) -> dict[str, float]:
    """Return per-path dimension weights over the 6-dim capability portrait."""
    if "普通" in path:
        return {
            "academic_foundation": 0.40,
            "research_innovation": 0.20,
            "competition_practice": 0.20,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.10,
        }
    if "特殊专长A" in path:
        return {
            "academic_foundation": 0.15,
            "research_innovation": 0.40,
            "competition_practice": 0.35,
            "engineering_practice": 0.05,
            "organization_service": 0.00,
            "growth_planning": 0.05,
        }
    if "特殊专长B" in path or "本硕博" in path:
        return {
            "academic_foundation": 0.25,
            "research_innovation": 0.40,
            "competition_practice": 0.10,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.15,
        }
    if "工程" in path:
        return {
            "academic_foundation": 0.20,
            "research_innovation": 0.10,
            "competition_practice": 0.15,
            "engineering_practice": 0.30,
            "organization_service": 0.05,
            "growth_planning": 0.20,
        }
    if "支教" in path or "辅导员" in path or "特殊专长C" in path:
        return {
            "academic_foundation": 0.10,
            "research_innovation": 0.05,
            "competition_practice": 0.05,
            "engineering_practice": 0.00,
            "organization_service": 0.50,
            "growth_planning": 0.30,
        }
    if "实习" in path or "就业" in path:
        return {
            "academic_foundation": 0.10,
            "research_innovation": 0.07,
            "competition_practice": 0.08,
            "engineering_practice": 0.55,
            "organization_service": 0.05,
            "growth_planning": 0.15,
        }
    if "考研" in path:
        return {
            "academic_foundation": 0.40,
            "research_innovation": 0.20,
            "competition_practice": 0.10,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.20,
        }
    if "考公" in path:
        return {
            "academic_foundation": 0.30,
            "research_innovation": 0.05,
            "competition_practice": 0.05,
            "engineering_practice": 0.05,
            "organization_service": 0.35,
            "growth_planning": 0.20,
        }
    return {d: 1.0 / 6 for d in ["academic_foundation", "research_innovation", "competition_practice", "engineering_practice", "organization_service", "growth_planning"]}


def _privacy_summary(summary: str, name: str | None = None, student_id: str | None = None) -> str:
    """Hide names/contact identifiers only; keep growth path and destination information."""
    s = str(summary or "")
    for token in [name, student_id]:
        if token:
            s = s.replace(str(token), "某同学")
    s = re.sub(r"1[3-9]\d{9}", "[手机号已隐去]", s)
    s = re.sub(r"\b\d{8,14}\b", "[学号已隐去]", s)
    s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[邮箱已隐去]", s)
    return s[:260]



def build_match_reason(cur_scores: dict, senior_scores: dict, cur_tags: list, senior_tags: list) -> str:
    dims = [
        ("学业基础", "academic_foundation"),
        ("科研创新", "research_innovation"),
        ("竞赛实践", "competition_practice"),
        ("工程实践", "engineering_practice"),
        ("组织服务", "organization_service"),
        ("成长规划", "growth_planning"),
    ]
    close = []
    for label, key in dims:
        try:
            if abs(float(cur_scores.get(key, 0)) - float(senior_scores.get(key, 0))) <= 15:
                close.append(label)
        except Exception:
            pass
    overlap = list(set(map(str, cur_tags or [])) & set(map(str, senior_tags or [])))[:3]
    parts = []
    if close:
        parts.append("画像相近维度：" + "、".join(close[:4]))
    if overlap:
        parts.append("共同标签：" + "、".join(overlap))
    return "；".join(parts) if parts else "综合六维能力画像相似度较高，可参考其成长路径。"

def match_similar_seniors(current_profile: dict, students: list[dict], top_k: int = 5, path: str = "综合", privacy: bool = True) -> list[dict]:
    cur_scores = current_profile.get("scores") or {}
    weights = path_weights(path)
    results = []
    for s in students:
        # Ensure historical student scores are in 6-dim format
        s_scores_raw = s.get("scores") or {}
        s_scores = convert_legacy_scores_to_six_dimensions(s_scores_raw, raw_student=s)
        numeric = weighted_similarity(cur_scores, s_scores, weights)
        tags = jaccard(current_profile.get("tags") or [], s.get("tags") or [])
        major_same = 1.0 if current_profile.get("major") and current_profile.get("major") == s.get("major") else 0.0
        sim = numeric * 0.70 + tags * 0.20 + major_same * 0.10
        destination = _privacy_summary(s.get("destination") or s.get("final_destination") or "", s.get("name"), s.get("student_id"))
        item = {
            "major": s.get("major"),
            "path_type": s.get("path_type"),
            "growth_destination_type": s.get("path_type") or "成长路径",
            "destination": destination or "未标注去向",
            "similarity": round(sim * 100, 2),
            "summary": _privacy_summary(s.get("summary") or "", s.get("name"), s.get("student_id")),
            "scores": s_scores,
            "match_reason": build_match_reason(cur_scores, s_scores, current_profile.get("tags") or [], s.get("tags") or []),
        }
        if not privacy:
            item.update({"student_id": s.get("student_id"), "name": s.get("name"), "destination": s.get("destination")})
        results.append(item)
    results = sorted(results, key=lambda x: x["similarity"], reverse=True)[:top_k]
    if privacy:
        for idx, item in enumerate(results, start=1):
            item["case_id"] = f"匿名案例{idx}"
    return results


def match_companies(current_profile: dict, companies: list[dict], top_k: int = 5, use_web: bool = False, include_external: bool = True) -> list[dict]:
    profile_text = " ".join(map(str, [current_profile.get("major", ""), current_profile.get("skills", []), current_profile.get("internships", []), current_profile.get("projects", []), current_profile.get("target", "")])).lower()
    profile_tags = set(map(str.lower, current_profile.get("tags") or []))
    results = []
    for c in companies:
        text = " ".join(map(str, [c.get("company_name", ""), c.get("positions", []), c.get("required_skills", []), c.get("preferred_major", []), c.get("tags", []), c.get("description", "")])).lower()
        overlap = 0
        for token in profile_tags:
            if token and token in text:
                overlap += 2
        for token in ["java", "python", "c++", "redis", "mysql", "spring", "kafka", "后端", "前端", "算法", "数据", "安全", "测试", "gis", "遥感", "大模型"]:
            if token in profile_text and token in text:
                overlap += 3
        if current_profile.get("major") and str(current_profile.get("major")).lower() in text:
            overlap += 4
        base = 35 if "校企" in text or "合作" in text else 18
        score = min(100, base + overlap * 8)
        c2 = dict(c)
        c2["match_score"] = round(score, 2)
        c2["match_reason"] = f"校企合作单位优先；与学生专业、技能、实习/项目方向的标签匹配度为 {round(score, 1)}。"
        results.append(make_company_card(c2, current_profile, use_web=use_web))
    results = sorted(results, key=lambda x: x.get("match_score", 0), reverse=True)[:top_k]
    if include_external:
        results += build_external_job_cards(current_profile, max_cards=max(0, top_k - len(results)), use_web=use_web)
    return results[:top_k]
