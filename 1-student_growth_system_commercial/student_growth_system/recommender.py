from __future__ import annotations
import json
from .storage import load_cache, save_cache, text_hash, load_policy, load_students, load_companies
from .heuristic_extract import extract_profile_heuristic
from .scoring import calculate_dimension_scores, calculate_path_scores
from .matcher import match_similar_seniors, match_companies
from .llm_client import SiliconFlowClient
from .prompts import STUDENT_EXTRACT_SYSTEM_PROMPT, ADVICE_SYSTEM_PROMPT
from .utils import sanitize_profile_for_review
from .algorithm_evaluator import run_algorithm_analysis
from .intent_detector import run_intent_analysis


def profile_tags(profile: dict, scores: dict) -> list[str]:
    tags = set(profile.get("tags") or [])
    text = str(profile)
    if scores.get("gpa_score", 0) >= 88:
        tags.add("GPA高")
    elif scores.get("gpa_score", 0) < 82:
        tags.add("GPA一般")
    if scores.get("internship_score", 0) >= 80:
        tags.add("实习强")
    if scores.get("paper_score", 0) >= 70:
        tags.add("论文强")
    if scores.get("competition_score", 0) >= 70:
        tags.add("竞赛强")
    for tag in ["后端", "前端", "算法", "人工智能", "网络安全", "数据", "GIS", "Java", "Python"]:
        if tag.lower() in text.lower():
            tags.add(tag)
    return sorted(tags)


EXTRACTOR_VERSION = "v6_intent"

def extract_student_profile(raw_text: str, use_llm: bool = True) -> dict:
    cache = load_cache()
    key = f"extract:{EXTRACTOR_VERSION}:" + text_hash(raw_text)
    if key in cache:
        return cache[key]
    profile = None
    if use_llm:
        client = SiliconFlowClient()
        if client.available:
            try:
                profile = client.extract_json(STUDENT_EXTRACT_SYSTEM_PROMPT, f"学生材料如下：\n{raw_text}", temperature=0.1, max_tokens=3000)
            except Exception as e:
                profile = extract_profile_heuristic(raw_text)
                profile.setdefault("uncertainty", []).append(f"大模型抽取失败，已使用启发式抽取：{e}")
    if profile is None:
        profile = extract_profile_heuristic(raw_text)
    profile = sanitize_profile_for_review(profile)
    scores = calculate_dimension_scores(profile)
    profile["scores"] = scores
    profile["tags"] = profile_tags(profile, scores)
    cache[key] = profile
    save_cache(cache)
    return profile


def build_context(profile: dict, use_web_jobs: bool = False) -> dict:
    scores = profile.get("scores") or calculate_dimension_scores(profile)
    # Rule-based path scores
    rule_path_scores = calculate_path_scores(profile, scores)

    # Algorithm enhancement: TOPSIS + weighted sum → blended final scores
    try:
        algo_analysis = run_algorithm_analysis(scores, rule_path_scores)
    except Exception as e:
        algo_analysis = {
            "method_used": ["rule_based_scoring"],
            "weighted_scores": {},
            "topsis_scores": {},
            "final_scores": rule_path_scores,
            "strengths": [],
            "weaknesses": [],
            "top_path_reasons": [],
            "risk_factors": [],
            "improvement_suggestions": [],
            "explanation": f"算法增强模块暂时不可用，已使用规则评分：{e}",
        }

    # Intent analysis: detect goal intent and apply bonus
    blended_scores = algo_analysis.get("final_scores") or rule_path_scores
    try:
        intent_analysis = run_intent_analysis(profile, scores, blended_scores)
        # Apply intent bonus on top of blended scores
        final_path_scores = intent_analysis.get("adjusted_scores") or blended_scores
    except Exception as e:
        intent_analysis = {
            "detected_intents": [],
            "applied_bonus": {},
            "adjusted_scores": blended_scores,
            "explanation": f"意向识别模块暂时不可用：{e}",
        }
        final_path_scores = blended_scores

    main_path = max(final_path_scores.items(), key=lambda x: x[1])[0]

    seniors = match_similar_seniors(profile, load_students(), top_k=5, path=main_path)
    companies = match_companies(profile, load_companies(), top_k=5, use_web=use_web_jobs, include_external=True)

    return {
        "current_student": {"profile": profile, "scores": scores},
        "path_scores": final_path_scores,
        "rule_path_scores": rule_path_scores,
        "main_path": main_path,
        "similar_seniors": seniors,
        "recommended_companies": companies,
        "policy_summary": load_policy(),
        "algorithm_analysis": algo_analysis,
        "intent_analysis": intent_analysis,
    }


def generate_llm_advice(context: dict, use_llm: bool = True) -> str:
    if not use_llm:
        return fallback_advice(context)
    client = SiliconFlowClient()
    if not client.available:
        return fallback_advice(context) + "\n\n提示：未配置 SILICONFLOW_API_KEY，当前为本地规则解释。"
    cache = load_cache()
    cache_payload = {
        "path_scores": context.get("path_scores"),
        "main_path": context.get("main_path"),
        "current_student": context.get("current_student"),
        "policy_summary": context.get("policy_summary"),
        "intent_intents": context.get("intent_analysis", ).get("detected_intents"),
    }
    key = "advice_v6i:" + text_hash(json.dumps(cache_payload, ensure_ascii=False, sort_keys=True))
    if key in cache:
        return cache[key]
    llm_context = {
        **context,
        "algorithm_summary": context.get("algorithm_analysis", {}).get("explanation", ""),
        "intent_summary": context.get("intent_analysis", {}).get("explanation", ""),
    }
    try:
        advice = client.chat(
            messages=[
                {"role": "system", "content": ADVICE_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(llm_context, ensure_ascii=False, indent=2)},
            ],
            temperature=0.3,
            max_tokens=2500,
        )
    except Exception as e:
        advice = fallback_advice(context) + f"\n\n提示：大模型建议生成失败，已使用本地解释：{e}"
    cache[key] = advice
    save_cache(cache)
    return advice


def fallback_advice(context: dict) -> str:
    path_scores = context.get("path_scores") or {}
    ranked = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
    main = ranked[0] if ranked else ("暂无", 0)
    alt = ranked[1:3]
    weak = ranked[-2:] if len(ranked) >= 2 else []
    seniors = context.get("similar_seniors") or []
    companies = context.get("recommended_companies") or []
    algo = context.get("algorithm_analysis") or {}
    intent = context.get("intent_analysis") or {}

    lines = [
        f"### 主推荐路径：{main[0]}（适配度 {main[1]:.1f}/100）",
        algo.get("explanation") or "该结论基于六维能力画像（学业基础、科研创新、竞赛实践、工程实践、组织服务、成长规划）的综合评分。",
        "",
        "### 备选路径",
        *(f"- {k}：{v:.1f}/100" for k, v in alt),
        "",
        "### 不优先推荐路径",
        *(f"- {k}：{v:.1f}/100" for k, v in weak),
    ]

    # Intent analysis
    intent_exp = intent.get("explanation") or ""
    if intent_exp:
        lines += ["", "### 目标意向识别", intent_exp]

    # Strengths / weaknesses
    strengths = algo.get("strengths") or []
    weaknesses = algo.get("weaknesses") or []
    if strengths:
        lines += ["", "### 优势维度", "、".join(strengths)]
    if weaknesses:
        lines += ["", "### 短板维度", "、".join(weaknesses)]

    reasons = algo.get("top_path_reasons") or []
    if reasons:
        lines += ["", "### 主推荐路径依据"]
        lines += [f"- {r}" for r in reasons]

    risks = algo.get("risk_factors") or []
    if risks:
        lines += ["", "### 风险提示"]
        lines += [f"- {r}" for r in risks]

    lines += ["", "### 相似学长参考"]
    if seniors:
        lines += [f"- {s.get('case_id') or '匿名案例'}｜相似度 {s.get('similarity')}%｜{s.get('growth_destination_type') or s.get('path_type') or '去向类型已保护'}｜{s.get('summary')}" for s in seniors[:3]]
    else:
        lines.append("- 当前历史学生库较小，暂未找到足够相似案例。")

    lines.append("\n### 校企合作单位优先推荐")
    if companies:
        lines += [f"- {c.get('company_name')}｜{c.get('position','')}｜匹配度 {c.get('match_score')}｜{c.get('salary_treatment','')}｜{c.get('match_reason','')}" for c in companies[:3]]
    else:
        lines.append("- 暂未导入校企合作单位，建议管理员上传合作单位表。")

    suggestions = algo.get("improvement_suggestions") or []
    lines += ["", "### 三个月行动计划"]
    if suggestions:
        lines += [f"{i+1}. {s}" for i, s in enumerate(suggestions)]
    lines += [
        f"{len(suggestions)+1}. 核对系统抽取的绩点、竞赛、论文、实习和学生工作信息，补全缺失字段。",
        f"{len(suggestions)+2}. 与相似学长案例对照，优先提升六维能力画像中差距最大的两个维度。",
        f"{len(suggestions)+3}. 专业方向作为辅助参考，结合目标路径确认技术栈或研究方向的匹配度。",
    ]
    return "\n".join(lines)


def run_recommendation(raw_text: str, use_extract_llm: bool = True, use_advice_llm: bool = True, use_web_jobs: bool = False) -> dict:
    profile = extract_student_profile(raw_text, use_llm=use_extract_llm)
    context = build_context(profile, use_web_jobs=use_web_jobs)
    advice = generate_llm_advice(context, use_llm=use_advice_llm)
    return {
        "profile": profile,
        "context": context,
        "advice": advice,
        "algorithm_analysis": context.get("algorithm_analysis"),
        "intent_analysis": context.get("intent_analysis"),
    }
