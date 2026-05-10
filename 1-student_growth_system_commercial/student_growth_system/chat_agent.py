"""chat_agent.py

AI counselor Q&A module. Answers student questions using their profile context.
Falls back to rule-based responses when no API key is configured.
"""
from __future__ import annotations

import json
from .llm_client import SiliconFlowClient
from .prompts import COUNSELOR_CHAT_SYSTEM_PROMPT
from .config import DIMENSION_LABELS


def _build_student_context_block(context: dict | None) -> str:
    """Serialize the student context into a compact string for the system prompt."""
    if not context:
        return ""

    parts: list[str] = []

    student = context.get("current_student") or {}
    profile = student.get("profile") or {}
    scores = student.get("scores") or {}

    if profile.get("major"):
        parts.append(f"专业：{profile['major']}")
    if profile.get("gpa"):
        parts.append(f"绩点：{profile['gpa']}")

    # Six-dim scores
    dim_lines = []
    for key, label in DIMENSION_LABELS.items():
        val = scores.get(key)
        if val is not None:
            dim_lines.append(f"{label}={float(val):.1f}")
    if dim_lines:
        parts.append("六维能力画像：" + "，".join(dim_lines))

    # Path scores
    path_scores = context.get("path_scores") or {}
    if path_scores:
        ranked = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
        top3 = "、".join(f"{k}（{v:.1f}分）" for k, v in ranked[:3])
        parts.append(f"路径评分 Top3：{top3}")
        parts.append(f"主推荐路径：{context.get('main_path', ranked[0][0])}")

    # Intent analysis
    intent = context.get("intent_analysis") or {}
    if intent.get("detected_intents"):
        parts.append("识别到的目标意向：" + "、".join(intent["detected_intents"]))
    if intent.get("explanation"):
        parts.append(f"意向说明：{intent['explanation']}")

    # Algorithm analysis highlights
    algo = context.get("algorithm_analysis") or {}
    if algo.get("strengths"):
        parts.append("优势维度：" + "、".join(algo["strengths"]))
    if algo.get("weaknesses"):
        parts.append("短板维度：" + "、".join(algo["weaknesses"]))
    if algo.get("risk_factors"):
        parts.append("风险提示：" + "；".join(algo["risk_factors"][:2]))

    # Similar seniors (anonymised)
    seniors = context.get("similar_seniors") or []
    if seniors:
        senior_lines = []
        for s in seniors[:3]:
            case_id = s.get("case_id") or "匿名案例"
            path = s.get("path_type") or s.get("growth_destination_type") or "成长路径"
            sim = s.get("similarity", "")
            summary = s.get("summary") or ""
            senior_lines.append(f"{case_id}（相似度{sim}%）：{path}，{summary[:60]}")
        parts.append("相似学长案例：\n" + "\n".join(senior_lines))

    # Companies
    companies = context.get("recommended_companies") or []
    if companies:
        co_lines = [
            f"{c.get('company_name', '')}（{c.get('position', '')}，匹配度{c.get('match_score', '')}）"
            for c in companies[:3]
        ]
        parts.append("推荐单位：" + "；".join(co_lines))

    # Policy summary
    policy = context.get("policy_summary") or {}
    if policy:
        policy_text = json.dumps(policy, ensure_ascii=False)[:400]
        parts.append(f"政策摘要（节选）：{policy_text}")

    return "\n".join(parts)


def _fallback_answer(question: str, context: dict | None) -> str:
    """Rule-based fallback when no LLM is available."""
    if not context:
        return (
            "当前未加载学生画像，无法给出个性化建议。"
            '请先在"学生端｜路径评估"页面完成画像抽取，再来这里提问。'
        )

    path_scores = context.get("path_scores") or {}
    main_path = context.get("main_path") or (
        max(path_scores.items(), key=lambda x: x[1])[0] if path_scores else "暂无"
    )
    algo = context.get("algorithm_analysis") or {}
    strengths = algo.get("strengths") or []
    weaknesses = algo.get("weaknesses") or []
    intent = context.get("intent_analysis") or {}
    detected = intent.get("detected_intents") or []

    lines = [
        f"根据你的六维能力画像，当前主推荐路径为【{main_path}】。",
    ]
    if strengths:
        lines.append(f"你的优势维度是：{'、'.join(strengths)}。")
    if weaknesses:
        lines.append(f"需要重点提升的维度是：{'、'.join(weaknesses)}。")
    if detected:
        lines.append(f"系统识别到你的目标意向：{'、'.join(detected)}，已在路径评分中做了轻微修正。")
    lines.append("如需更详细的个性化建议，请配置 SILICONFLOW_API_KEY 后重试。")
    return "\n".join(lines)


def answer_student_question(
    question: str,
    history: list[dict],
    context: dict | None = None,
) -> str:
    """Answer a student question using LLM with injected context.

    Args:
        question: The student's current question.
        history: Prior turns as [{"role": "user"|"assistant", "content": "..."}].
        context: The build_context() output for the current student (may be None).

    Returns:
        The assistant's reply as a string.
    """
    client = SiliconFlowClient()
    if not client.available:
        return _fallback_answer(question, context) + "\n\n提示：未配置 SILICONFLOW_API_KEY，当前为本地规则回答。"

    context_block = _build_student_context_block(context)
    system_content = COUNSELOR_CHAT_SYSTEM_PROMPT
    if context_block:
        system_content += f"\n\n【当前学生画像摘要】\n{context_block}"

    messages = [{"role": "system", "content": system_content}]
    # Include recent history (last 10 turns to stay within token budget)
    for turn in history[-10:]:
        if turn.get("role") in ("user", "assistant") and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": question})

    try:
        reply = client.chat(messages=messages, temperature=0.4, max_tokens=600)
    except Exception as e:
        reply = _fallback_answer(question, context) + f"\n\n提示：大模型调用失败，已使用本地规则回答：{e}"

    return reply
