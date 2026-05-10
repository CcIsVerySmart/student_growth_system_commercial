"""algorithm_evaluator.py

Multi-method algorithm enhancement module for the student growth path system.

Methods implemented:
1. normalize_scores        — min-max normalisation of 6-dim scores to [0, 1]
2. weighted_sum_score      — weighted linear combination → [0, 100]
3. topsis_rank             — simplified TOPSIS multi-criteria ranking
4. generate_explainable_reasons — strengths / weaknesses / suggestions
5. build_path_weight_matrix — centralised 9-path × 6-dim weight table
"""
from __future__ import annotations

import math
from typing import Any

# ── canonical dimension order ──────────────────────────────────────────────
SIX_DIMS = [
    "academic_foundation",
    "research_innovation",
    "competition_practice",
    "engineering_practice",
    "organization_service",
    "growth_planning",
]

DIM_LABELS_CN = {
    "academic_foundation": "学业基础",
    "research_innovation": "科研创新",
    "competition_practice": "竞赛实践",
    "engineering_practice": "工程实践",
    "organization_service": "组织服务",
    "growth_planning": "成长规划",
}

# Thresholds for strength / weakness classification
STRENGTH_THRESHOLD = 65.0
WEAKNESS_THRESHOLD = 35.0


# ── helpers ────────────────────────────────────────────────────────────────

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v or default)
    except Exception:
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _get_six_dim_vector(profile_scores: dict) -> list[float]:
    """Extract the 6-dim vector, falling back to 0 for missing dims."""
    return [_safe_float(profile_scores.get(d)) for d in SIX_DIMS]


# ── 1. Normalise ───────────────────────────────────────────────────────────

def normalize_scores(profile_scores: dict) -> dict[str, float]:
    """Min-max normalise 6-dim scores to [0, 1].

    Since all scores are already in [0, 100], this is a simple /100 division.
    Returns a dict with the same keys, values in [0, 1].
    """
    return {d: round(_safe_float(profile_scores.get(d)) / 100.0, 4) for d in SIX_DIMS}


# ── 2. Weighted sum ────────────────────────────────────────────────────────

def weighted_sum_score(profile_scores: dict, weights: dict[str, float]) -> float:
    """Compute a weighted linear combination of 6-dim scores.

    Args:
        profile_scores: dict with 6-dim keys, values in [0, 100].
        weights: dict mapping dim keys to non-negative weights (need not sum to 1).

    Returns:
        Weighted score in [0, 100].
    """
    total_w = sum(_safe_float(weights.get(d)) for d in SIX_DIMS)
    if total_w <= 0:
        return 0.0
    score = sum(
        _safe_float(profile_scores.get(d)) * _safe_float(weights.get(d))
        for d in SIX_DIMS
    )
    return round(_clamp(score / total_w), 2)


# ── 3. TOPSIS ──────────────────────────────────────────────────────────────

def topsis_rank(
    profile_scores: dict,
    path_weight_matrix: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Simplified TOPSIS multi-criteria ranking.

    Treats each path as an "alternative" and the student's 6-dim scores as
    the "criteria values".  The ideal best is the path whose weight vector
    most closely aligns with the student's strong dimensions; the ideal worst
    is the opposite.

    Steps:
    1. Build a decision matrix: rows = paths, cols = 6 dims.
       Each cell = student_score[dim] * path_weight[dim].
    2. Normalise each column by its Euclidean norm.
    3. Compute weighted normalised matrix (weights already embedded in step 1,
       so this step just re-normalises).
    4. Identify ideal best (max per col) and ideal worst (min per col).
    5. Compute Euclidean distance to ideal best (D+) and worst (D-).
    6. Closeness coefficient C = D- / (D+ + D-), scaled to [0, 100].

    Returns:
        Dict mapping path name → TOPSIS closeness score in [0, 100].
    """
    paths = list(path_weight_matrix.keys())
    if not paths:
        return {}

    student_vec = _get_six_dim_vector(profile_scores)

    # Step 1: decision matrix (paths × dims)
    matrix: list[list[float]] = []
    for path in paths:
        w = path_weight_matrix[path]
        row = [student_vec[i] * _safe_float(w.get(SIX_DIMS[i])) for i in range(len(SIX_DIMS))]
        matrix.append(row)

    # Step 2: column-wise Euclidean normalisation
    col_norms = []
    for j in range(len(SIX_DIMS)):
        norm = math.sqrt(sum(matrix[i][j] ** 2 for i in range(len(paths))))
        col_norms.append(norm if norm > 0 else 1.0)

    norm_matrix = [
        [matrix[i][j] / col_norms[j] for j in range(len(SIX_DIMS))]
        for i in range(len(paths))
    ]

    # Steps 3-4: ideal best and worst
    ideal_best = [max(norm_matrix[i][j] for i in range(len(paths))) for j in range(len(SIX_DIMS))]
    ideal_worst = [min(norm_matrix[i][j] for i in range(len(paths))) for j in range(len(SIX_DIMS))]

    # Step 5: distances
    results: dict[str, float] = {}
    for idx, path in enumerate(paths):
        row = norm_matrix[idx]
        d_plus = math.sqrt(sum((row[j] - ideal_best[j]) ** 2 for j in range(len(SIX_DIMS))))
        d_minus = math.sqrt(sum((row[j] - ideal_worst[j]) ** 2 for j in range(len(SIX_DIMS))))
        denom = d_plus + d_minus
        closeness = (d_minus / denom * 100) if denom > 1e-9 else 50.0
        results[path] = round(_clamp(closeness), 2)

    return results


# ── 4. Explainable reasons ─────────────────────────────────────────────────

def generate_explainable_reasons(
    profile_scores: dict,
    path_scores: dict[str, float],
    top_path: str,
) -> dict:
    """Generate human-readable explainability analysis.

    Returns a dict with:
        strengths, weaknesses, top_path_reasons,
        risk_factors, improvement_suggestions, explanation
    """
    strengths: list[str] = []
    weaknesses: list[str] = []

    for dim in SIX_DIMS:
        val = _safe_float(profile_scores.get(dim))
        label = DIM_LABELS_CN[dim]
        if val >= STRENGTH_THRESHOLD:
            strengths.append(label)
        elif val <= WEAKNESS_THRESHOLD:
            weaknesses.append(label)

    # Top-path reasons based on which dims are strong and align with the path
    top_path_reasons: list[str] = []
    _path_reason_map = {
        "普通推免": ["学业基础", "科研创新", "竞赛实践"],
        "特殊专长A类": ["科研创新", "竞赛实践"],
        "特殊专长B/本硕博": ["学业基础", "科研创新", "成长规划"],
        "特殊专长C/辅导员计划": ["组织服务", "成长规划"],
        "支教计划": ["组织服务", "成长规划"],
        "工程专项/专硕": ["工程实践", "学业基础", "成长规划"],
        "实习就业": ["工程实践"],
        "考研": ["学业基础", "成长规划"],
        "考公": ["学业基础", "组织服务", "成长规划"],
    }
    key_dims = _path_reason_map.get(top_path, [])
    for dim_label in key_dims:
        if dim_label in strengths:
            top_path_reasons.append(f"{dim_label}能力较强，与{top_path}路径的核心要求匹配")
    if not top_path_reasons:
        top_path_reasons.append(f"综合六维能力画像评估，{top_path}路径的综合适配度最高")

    # Risk factors
    risk_factors: list[str] = []
    if "学业基础" in weaknesses:
        risk_factors.append("学业基础偏弱，保研类路径竞争压力较大，建议优先提升绩点")
    if "科研创新" in weaknesses and top_path in ["普通推免", "特殊专长A类", "特殊专长B/本硕博"]:
        risk_factors.append("科研创新积累不足，建议尽早联系导师或参与科研项目")
    if "工程实践" in weaknesses and top_path in ["工程专项/专硕", "实习就业"]:
        risk_factors.append("工程实践经验较少，建议积极寻找实习机会或参与项目开发")
    if "组织服务" in weaknesses and top_path in ["特殊专长C/辅导员计划", "支教计划"]:
        risk_factors.append("学生工作和志愿服务经历不足，建议积极参与学生组织或志愿活动")
    if not risk_factors:
        risk_factors.append("当前画像未发现明显风险因素，建议持续保持各维度均衡发展")

    # Improvement suggestions
    improvement_suggestions: list[str] = []
    for dim in weaknesses[:2]:
        if dim == "学业基础":
            improvement_suggestions.append("提升绩点：合理规划课程，重视期末考试，争取奖学金")
        elif dim == "科研创新":
            improvement_suggestions.append("加强科研：联系导师参与课题，尝试撰写或参与论文，申报大创项目")
        elif dim == "竞赛实践":
            improvement_suggestions.append("参加竞赛：选择与专业方向匹配的学科竞赛，组队备赛")
        elif dim == "工程实践":
            improvement_suggestions.append("积累实习：主动投递实习岗位，完善项目经历和技术栈")
        elif dim == "组织服务":
            improvement_suggestions.append("拓展学生工作：参与班委、学生会或志愿服务，积累组织管理经验")
        elif dim == "成长规划":
            improvement_suggestions.append("明确目标：尽早确定发展方向，制定阶段性计划并付诸行动")
    if not improvement_suggestions:
        improvement_suggestions.append("各维度发展较为均衡，建议围绕主推荐路径进一步深化核心优势")

    # Summary explanation
    ranked = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
    top3 = "、".join(f"{k}（{v:.0f}分）" for k, v in ranked[:3])
    explanation = (
        f"系统综合采用规则评分、多指标综合评价（TOPSIS）、历史案例相似度匹配和可解释性分析，"
        f"对学生六维能力画像进行综合评估。"
        f"不同发展路径采用差异化权重设置，以避免使用单一标准评价所有学生。"
        f"当前综合评估结果：{top3}。"
        f"主推荐路径为【{top_path}】，"
        + ("优势维度：" + "、".join(strengths) + "。" if strengths else "各维度发展较为均衡。")
    )

    return {
        "strengths": strengths,
        "weaknesses": weaknesses,
        "top_path_reasons": top_path_reasons,
        "risk_factors": risk_factors,
        "improvement_suggestions": improvement_suggestions,
        "explanation": explanation,
    }


# ── 5. Path weight matrix ──────────────────────────────────────────────────

def build_path_weight_matrix() -> dict[str, dict[str, float]]:
    """Return the 9-path × 6-dim weight matrix.

    Weights are non-negative and sum to 1.0 per path.
    These mirror the weights used in matcher.path_weights() for consistency.
    """
    return {
        "普通推免": {
            "academic_foundation": 0.40,
            "research_innovation": 0.20,
            "competition_practice": 0.20,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.10,
        },
        "特殊专长A类": {
            "academic_foundation": 0.15,
            "research_innovation": 0.40,
            "competition_practice": 0.35,
            "engineering_practice": 0.05,
            "organization_service": 0.00,
            "growth_planning": 0.05,
        },
        "特殊专长B/本硕博": {
            "academic_foundation": 0.25,
            "research_innovation": 0.40,
            "competition_practice": 0.10,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.15,
        },
        "特殊专长C/辅导员计划": {
            "academic_foundation": 0.10,
            "research_innovation": 0.05,
            "competition_practice": 0.05,
            "engineering_practice": 0.00,
            "organization_service": 0.50,
            "growth_planning": 0.30,
        },
        "支教计划": {
            "academic_foundation": 0.10,
            "research_innovation": 0.05,
            "competition_practice": 0.05,
            "engineering_practice": 0.00,
            "organization_service": 0.50,
            "growth_planning": 0.30,
        },
        "工程专项/专硕": {
            "academic_foundation": 0.20,
            "research_innovation": 0.10,
            "competition_practice": 0.15,
            "engineering_practice": 0.30,
            "organization_service": 0.05,
            "growth_planning": 0.20,
        },
        "实习就业": {
            "academic_foundation": 0.10,
            "research_innovation": 0.07,
            "competition_practice": 0.08,
            "engineering_practice": 0.55,
            "organization_service": 0.05,
            "growth_planning": 0.15,
        },
        "考研": {
            "academic_foundation": 0.40,
            "research_innovation": 0.20,
            "competition_practice": 0.10,
            "engineering_practice": 0.05,
            "organization_service": 0.05,
            "growth_planning": 0.20,
        },
        "考公": {
            "academic_foundation": 0.30,
            "research_innovation": 0.05,
            "competition_practice": 0.05,
            "engineering_practice": 0.05,
            "organization_service": 0.35,
            "growth_planning": 0.20,
        },
    }


# ── 6. Full algorithm analysis ─────────────────────────────────────────────

def run_algorithm_analysis(
    profile_scores: dict,
    rule_path_scores: dict[str, float],
) -> dict:
    """Run the full algorithm enhancement pipeline.

    Args:
        profile_scores: output of calculate_dimension_scores() — contains both
                        6-dim keys and raw sub-scores.
        rule_path_scores: output of calculate_path_scores() — rule-based scores.

    Returns:
        algorithm_analysis dict with:
            method_used, weighted_scores, topsis_scores, final_scores,
            strengths, weaknesses, risk_factors, improvement_suggestions,
            explanation
    """
    weight_matrix = build_path_weight_matrix()

    # Weighted sum scores (one per path)
    weighted_scores: dict[str, float] = {}
    for path, weights in weight_matrix.items():
        weighted_scores[path] = weighted_sum_score(profile_scores, weights)

    # TOPSIS scores
    try:
        topsis_scores = topsis_rank(profile_scores, weight_matrix)
    except Exception:
        topsis_scores = {p: 50.0 for p in weight_matrix}

    # Blend: final = 0.75 * rule + 0.25 * algorithm (average of weighted_sum and topsis)
    final_scores: dict[str, float] = {}
    for path in weight_matrix:
        rule = _safe_float(rule_path_scores.get(path))
        algo = (_safe_float(weighted_scores.get(path)) + _safe_float(topsis_scores.get(path))) / 2.0
        final = round(_clamp(0.75 * rule + 0.25 * algo), 2)
        final_scores[path] = final

    top_path = max(final_scores.items(), key=lambda x: x[1])[0] if final_scores else "暂无"

    explainability = generate_explainable_reasons(profile_scores, final_scores, top_path)

    return {
        "method_used": [
            "rule_based_scoring",
            "weighted_sum",
            "topsis",
            "case_similarity",
            "explainable_analysis",
        ],
        "weighted_scores": weighted_scores,
        "topsis_scores": topsis_scores,
        "final_scores": final_scores,
        "strengths": explainability["strengths"],
        "weaknesses": explainability["weaknesses"],
        "top_path_reasons": explainability["top_path_reasons"],
        "risk_factors": explainability["risk_factors"],
        "improvement_suggestions": explainability["improvement_suggestions"],
        "explanation": explainability["explanation"],
    }
