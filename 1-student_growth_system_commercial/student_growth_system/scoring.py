from __future__ import annotations
import re
from typing import Any
from .ccf_venues import guess_ccf_rank


def clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    try:
        return max(lo, min(hi, float(x)))
    except Exception:
        return lo


def gpa_to_score(gpa: Any) -> float:
    try:
        g = float(gpa)
    except Exception:
        return 0
    if g <= 0:
        return 0
    if g <= 5.0:
        return clamp(60 + (g - 1) * 10)
    if g <= 100:
        return clamp(g)
    return 0


def text_blob(profile: dict) -> str:
    return str(profile).lower()


def award_score(text: str) -> float:
    t = text.lower()
    if any(x in t for x in ["特等奖", "一等奖", "一等", "冠军", "gold"]):
        return 100
    if any(x in t for x in ["二等奖", "二等", "银奖", "silver"]):
        return 85
    if any(x in t for x in ["三等奖", "三等", "铜奖", "bronze"]):
        return 70
    if any(x in t for x in ["优秀奖", "优胜", "入围", "finalist"]):
        return 45
    return 35 if text.strip() else 0


def competition_level_factor(text: str) -> float:
    t = text.lower()
    if "ccf a" in t or "a类" in t or "a 类" in t:
        return 1.0
    if "ccf b" in t or "b类" in t or "b 类" in t:
        return 0.85
    if "ccf c" in t or "c类" in t or "c 类" in t:
        return 0.7
    if any(x in t for x in ["国家", "全国", "国际", "world", "national"]):
        return 0.9
    if any(x in t for x in ["省", "湖北", "赛区", "区域"]):
        return 0.65
    if any(x in t for x in ["校", "院级"]):
        return 0.35
    return 0.55


def contribution_factor(rank: Any) -> float:
    try:
        r = int(float(rank))
    except Exception:
        return 0.8
    if r <= 1:
        return 1.0
    if r <= 3:
        return 0.7
    if r <= 5:
        return 0.5
    return 0.3


def score_one_competition(c: Any) -> float:
    if isinstance(c, dict):
        text = " ".join(str(c.get(k, "")) for k in ["name", "level", "award", "scope"])
        rank = c.get("team_rank") or c.get("rank") or c.get("排名")
    else:
        text = str(c)
        rank = None
    return clamp(award_score(text) * competition_level_factor(text) * contribution_factor(rank))


def score_competitions(competitions: list[Any], mode: str = "weighted_top3") -> float:
    scores = sorted([score_one_competition(c) for c in competitions if c], reverse=True)
    if not scores:
        return 0
    if mode == "max_only":
        return scores[0]
    weights = [0.6, 0.3, 0.1]
    return clamp(sum(s * w for s, w in zip(scores[:3], weights)))


def paper_base_score(p: Any) -> float:
    if isinstance(p, dict):
        venue = str(p.get("venue") or p.get("期刊会议") or "")
        ccf_rank = (p.get("ccf_rank") or guess_ccf_rank(venue) or "").upper()
        sci_zone = str(p.get("sci_zone") or "").upper()
        indexed = " ".join(p.get("indexed_by") or []) if isinstance(p.get("indexed_by"), list) else str(p.get("indexed_by") or "")
        title = str(p.get("title") or "")
        status = str(p.get("status") or "")
        text = f"{venue} {ccf_rank} {sci_zone} {indexed} {title} {status}"
    else:
        text = str(p)
        ccf_rank = guess_ccf_rank(text) or ""
        sci_zone = ""
    t = text.upper()
    if "WORKSHOP" in t:
        return 35
    if ccf_rank == "A" or "CCF-A" in t or "CCF A" in t:
        return 100
    if "Q1" in sci_zone or "一区" in text or "SCI一区" in text:
        return 95
    if ccf_rank == "B" or "CCF-B" in t or "CCF B" in t:
        return 85
    if "Q2" in sci_zone or "二区" in text or "SCI二区" in text:
        return 80
    if ccf_rank == "C" or "CCF-C" in t or "CCF C" in t:
        return 70
    if "SCI" in t and ("Q3" in t or "三区" in text):
        return 65
    if "EI" in t or "SSCI" in t or "SCI" in t:
        return 60
    if "核心" in text or "学报" in text:
        return 50
    if "ARXIV" in t or "预印本" in text:
        return 30
    return 25 if text.strip() else 0


def paper_author_factor(p: Any) -> float:
    if not isinstance(p, dict):
        t = str(p)
        if "一作" in t or "第一作者" in t:
            return 1.0
        if "二作" in t or "第二作者" in t:
            return 0.6
        return 0.8
    if p.get("is_co_first"):
        return 0.9
    rank = p.get("author_rank") or p.get("作者排名")
    try:
        r = int(float(rank))
    except Exception:
        t = str(p)
        if "第一作者" in t or "一作" in t:
            return 1.0
        return 0.75
    if r == 1:
        return 1.0
    if r == 2:
        return 0.6
    if r == 3:
        return 0.4
    return 0.2


def paper_status_factor(p: Any) -> float:
    t = str(p).lower()
    if any(x in t for x in ["under review", "submitted", "在投", "投稿"]):
        return 0.4
    if any(x in t for x in ["arxiv", "预印本"]):
        return 0.35
    if any(x in t for x in ["accepted", "录用", "接收", "发表", "published"]):
        return 1.0
    return 0.85


def score_papers(papers: list[Any]) -> float:
    scores = sorted([clamp(paper_base_score(p) * paper_author_factor(p) * paper_status_factor(p)) for p in papers if p], reverse=True)
    if not scores:
        return 0
    weights = [0.7, 0.2, 0.1]
    return clamp(sum(s * w for s, w in zip(scores[:3], weights)))


def score_internship(profile: dict) -> float:
    items = profile.get("internships") or []
    text = str(items) + " " + str(profile.get("projects") or "") + " " + str(profile.get("skills") or "")
    if not text.strip() or text.strip() in ["[]", "none"]:
        return 0
    score = 20
    if any(x in text for x in ["腾讯", "阿里", "字节", "美团", "百度", "华为", "京东", "网易", "小米", "滴滴", "大厂", "头部"]):
        score += 45
    elif any(x in text for x in ["公司", "企业", "实习", "研究院", "实验室", "校企"]):
        score += 30
    if any(x in text.lower() for x in ["java", "python", "go", "c++", "redis", "mysql", "spring", "kafka", "linux", "docker", "kubernetes", "算法", "后端", "前端", "数据", "安全", "测试"]):
        score += 25
    m = re.search(r"(\d+(?:\.\d+)?)\s*(个月|月)", text)
    if m:
        months = float(m.group(1))
        score += min(10, months * 2)
    return clamp(score)


def score_student_work(profile: dict) -> float:
    text = str(profile.get("student_work") or "") + " " + str(profile.get("honors") or "") + " " + str(profile.get("volunteer_hours") or "")
    score = 0
    if any(x in text for x in ["主席", "负责人", "书记", "部长", "班长", "团支书", "学生会", "党支部", "团委"]):
        score += 55
    elif any(x in text for x in ["班委", "干部", "社团", "助管", "辅导员助理"]):
        score += 35
    if any(x in text for x in ["优秀学生干部", "优秀团员", "优秀团干", "标兵", "先进个人"]):
        score += 25
    try:
        vh = float(profile.get("volunteer_hours") or 0)
        score += min(20, vh / 5)
    except Exception:
        if "志愿" in text or "支教" in text:
            score += 15
    return clamp(score)


def score_research(profile: dict) -> float:
    text = str(profile.get("research_experiences") or "") + " " + str(profile.get("projects") or "") + " " + str(profile.get("papers") or "")
    score = 0
    if any(x in text for x in ["国家级大创", "国创", "优秀结题", "发明专利", "导师", "科研项目", "课题", "实验室"]):
        score += 45
    if any(x in text for x in ["负责人", "主持", "第一", "一作", "第一作者"]):
        score += 25
    if any(x in text.lower() for x in ["ccf", "sci", "ei", "ssci", "论文", "专利"]):
        score += 30
    return clamp(score)


def score_major(profile: dict) -> float:
    major = str(profile.get("major") or "")
    target = str(profile.get("target") or "") + " " + str(profile.get("skills") or "") + " " + str(profile.get("papers") or "")
    if not major:
        return 60
    if any(x in major for x in ["计算机", "软件", "网安", "信息安全", "数据", "人工智能", "智能科学"]):
        return 95
    if any(x in major for x in ["电子", "自动化", "地信", "测绘", "数学", "物联网"]):
        return 80
    return 65


def score_english(profile: dict) -> float:
    """Evaluate English ability using CET-4 as threshold and CET-6 as an additional advantage."""
    cet4 = profile.get("cet4")
    cet6 = profile.get("cet6")
    score = 40
    try:
        c4 = float(cet4 or 0)
        if c4 >= 425:
            score = max(score, 70)
        if c4 >= 500:
            score = max(score, 78)
        if c4 >= 550:
            score = max(score, 82)
    except Exception:
        pass
    try:
        c6 = float(cet6 or 0)
        if c6 >= 425:
            score = max(score, 85)
        if c6 >= 500:
            score = max(score, 92)
        if c6 >= 550:
            score = max(score, 96)
    except Exception:
        pass
    return clamp(score)


def infer_communication_score(profile: dict) -> float:
    text = " ".join(map(str, [profile.get("self_description", ""), profile.get("student_work", []), profile.get("honors", []), profile.get("competitions", []), profile.get("certificates", [])]))
    score = 30
    for kw in ["演讲", "写作", "辩论", "主持", "汇报", "宣传", "新闻稿", "公众号", "组织", "协调", "学生会", "班长", "团支书"]:
        if kw in text:
            score += 8
    return clamp(score)


def score_honor(profile: dict) -> float:
    text = str(profile.get("honors") or "") + " " + str(profile.get("certificates") or "") + " " + str(profile.get("student_work") or "")
    score = 0
    if any(x in text for x in ["国家", "全国", "国奖", "国家奖学金"]): score += 45
    if any(x in text for x in ["省", "湖北", "省级"]): score += 30
    if any(x in text for x in ["校级", "优秀学生", "优秀团员", "优秀干部", "奖学金", "标兵", "先进个人"]): score += 30
    return clamp(score)


def score_volunteer(profile: dict) -> float:
    try:
        hours = float(profile.get("volunteer_hours") or 0)
    except Exception:
        hours = 0
    text = str(profile.get("student_work") or "") + " " + str(profile.get("honors") or "")
    base = min(100, hours * 1.2)
    if "志愿" in text or "支教" in text or "三下乡" in text:
        base = max(base, 40)
    return clamp(base)


def score_growth_planning(profile: dict, sub_scores: dict) -> float:
    score = 15.0
    target = str(profile.get("target") or "") + " " + str(profile.get("self_description") or "")
    if any(x in target for x in ["保研", "推免", "考研", "就业", "考公", "出国", "留学", "创业", "支教", "辅导员"]):
        score += 20
    breadth_count = sum([
        1 if sub_scores.get("competition_score", 0) >= 30 else 0,
        1 if sub_scores.get("paper_score", 0) >= 30 else 0,
        1 if sub_scores.get("internship_score", 0) >= 30 else 0,
        1 if sub_scores.get("student_work_score", 0) >= 30 else 0,
        1 if sub_scores.get("research_score", 0) >= 30 else 0,
    ])
    if breadth_count >= 3:
        score += 30
    elif breadth_count >= 2:
        score += 15
    text = str(profile)
    has_cross = (
        (sub_scores.get("research_score", 0) >= 30 and sub_scores.get("internship_score", 0) >= 30)
        or (sub_scores.get("competition_score", 0) >= 30 and sub_scores.get("student_work_score", 0) >= 30)
        or any(x in text for x in ["跨学科", "交叉", "双学位", "辅修"])
    )
    if has_cross:
        score += 20
    weak_dims = sum([
        1 if sub_scores.get("gpa_score", 0) < 60 else 0,
        1 if sub_scores.get("english_score", 0) < 60 else 0,
        1 if sub_scores.get("competition_score", 0) < 20 else 0,
        1 if sub_scores.get("paper_score", 0) < 20 else 0,
        1 if sub_scores.get("internship_score", 0) < 20 else 0,
    ])
    if weak_dims == 0:
        score += 15
    return clamp(score)


def calculate_dimension_scores(profile: dict) -> dict[str, float]:
    competitions = profile.get("competitions") or []
    papers = profile.get("papers") or []
    gpa_score = round(gpa_to_score(profile.get("gpa")), 2)
    competition_score = round(score_competitions(competitions, mode="weighted_top3"), 2)
    normal_competition_score = round(score_competitions(competitions, mode="max_only"), 2)
    paper_score = round(score_papers(papers), 2)
    internship_score = round(score_internship(profile), 2)
    student_work_score = round(score_student_work(profile), 2)
    major_score = round(score_major(profile), 2)
    research_score = round(score_research(profile), 2)
    english_score = round(score_english(profile), 2)
    communication_score = round(infer_communication_score(profile), 2)
    honor_score = round(score_honor(profile), 2)
    volunteer_score = round(score_volunteer(profile), 2)

    sub = {
        "gpa_score": gpa_score, "competition_score": competition_score,
        "paper_score": paper_score, "internship_score": internship_score,
        "student_work_score": student_work_score, "research_score": research_score,
        "english_score": english_score, "honor_score": honor_score,
    }

    academic_foundation = round(clamp(0.70 * gpa_score + 0.20 * english_score + 0.10 * honor_score), 2)
    research_innovation = round(clamp(0.65 * paper_score + 0.35 * research_score), 2)
    competition_practice = competition_score
    engineering_practice = internship_score
    organization_service = round(clamp(0.70 * student_work_score + 0.30 * volunteer_score), 2)
    growth_planning = round(score_growth_planning(profile, sub), 2)

    return {
        "gpa_score": gpa_score,
        "competition_score": competition_score,
        "normal_competition_score": normal_competition_score,
        "paper_score": paper_score,
        "internship_score": internship_score,
        "student_work_score": student_work_score,
        "major_score": major_score,
        "research_score": research_score,
        "english_score": english_score,
        "communication_score": communication_score,
        "honor_score": honor_score,
        "volunteer_score": volunteer_score,
        # Six-dimension synthesis (used by radar chart and matcher)
        "academic_foundation": academic_foundation,
        "research_innovation": research_innovation,
        "competition_practice": competition_practice,
        "engineering_practice": engineering_practice,
        "organization_service": organization_service,
        "growth_planning": growth_planning,
    }


def calculate_civil_service_score(profile: dict, scores: dict[str, float]) -> float:
    return clamp(scores.get("student_work_score", 0) * 0.25 + scores.get("communication_score", 0) * 0.20 + scores.get("gpa_score", 0) * 0.15 + scores.get("honor_score", 0) * 0.15 + scores.get("volunteer_score", 0) * 0.10 + scores.get("major_score", 0) * 0.10 + scores.get("english_score", 0) * 0.05)


def apply_fallback_policy(path_scores: dict[str, float], scores: dict[str, float]) -> dict[str, float]:
    adjusted = dict(path_scores)
    fallback_keys = ["考研", "考公", "考研+实习双线", "考公+实习双线"]
    primary_keys = ["普通推免", "特殊专长A类", "特殊专长B/本硕博", "特殊专长C/辅导员计划", "支教计划", "工程专项/专硕", "校企合作实习", "实习就业", "秋招就业", "项目补强"]
    best_primary = max([adjusted.get(k, 0) for k in primary_keys], default=0)
    has_growth_path = best_primary >= 55 or scores.get("internship_score", 0) >= 60 or scores.get("competition_score", 0) >= 60 or scores.get("research_score", 0) >= 60 or scores.get("paper_score", 0) >= 60 or scores.get("student_work_score", 0) >= 70
    for key in fallback_keys:
        if key not in adjusted:
            continue
        adjusted[key] = min(adjusted[key], 42) if has_growth_path else max(adjusted[key], 58)
    return adjusted


def calculate_path_scores(profile: dict, scores: dict[str, float]) -> dict[str, float]:
    g = scores.get("gpa_score", 0); c = scores.get("competition_score", 0); cn = scores.get("normal_competition_score", c)
    p = scores.get("paper_score", 0); i = scores.get("internship_score", 0); sw = scores.get("student_work_score", 0)
    m = scores.get("major_score", 0); r = scores.get("research_score", 0); english = scores.get("english_score", 40); volunteer = scores.get("volunteer_score", 0)
    basic_penalty = 1.0
    try:
        if float(profile.get("gpa") or 0) < 2.8: basic_penalty *= 0.25
    except Exception: pass
    if profile.get("has_failed_course") is True: basic_penalty *= 0.3
    try:
        if profile.get("cet4") and float(profile.get("cet4") or 0) < 425: basic_penalty *= 0.5
    except Exception: pass
    normal = (g * 0.50 + cn * 0.20 + p * 0.12 + r * 0.10 + english * 0.05 + sw * 0.03) * basic_penalty
    special_a = (max(c, p) * 0.35 + c * 0.20 + p * 0.25 + r * 0.10 + g * 0.10) * basic_penalty
    special_b = (r * 0.30 + p * 0.20 + c * 0.15 + g * 0.20 + m * 0.15) * basic_penalty
    special_c = (sw * 0.45 + volunteer * 0.20 + scores.get("honor_score", 0) * 0.15 + scores.get("communication_score", 0) * 0.10 + g * 0.10) * basic_penalty
    service = (sw * 0.35 + volunteer * 0.30 + scores.get("honor_score", 0) * 0.15 + g * 0.10 + scores.get("communication_score", 0) * 0.10) * basic_penalty
    engineering = g * 0.20 + i * 0.20 + c * 0.15 + p * 0.10 + r * 0.15 + m * 0.10 + min(100, i + 10) * 0.10
    internship = i * 0.45 + min(100, i + 10) * 0.20 + m * 0.10 + c * 0.10 + g * 0.05 + r * 0.10
    exam = g * 0.25 + english * 0.15 + m * 0.15 + max(r, c, i) * 0.15 + 70 * 0.30
    civil = calculate_civil_service_score(profile, scores)
    raw = {k: round(clamp(v), 2) for k, v in {
        "普通推免": normal, "特殊专长A类": special_a, "特殊专长B/本硕博": special_b,
        "特殊专长C/辅导员计划": special_c, "支教计划": service, "工程专项/专硕": engineering,
        "实习就业": internship, "考研": exam, "考公": civil,
    }.items()}
    adjusted = apply_fallback_policy(raw, scores)
    return {k: round(clamp(v), 2) for k, v in adjusted.items()}


def convert_legacy_scores_to_six_dimensions(scores_raw: dict, raw_student: dict | None = None) -> dict:
    """Normalise any scores dict to the 6-dim format used by matcher.py."""
    _key_map = {
        "academic_foundation":  ["academic_foundation", "gpa_score"],
        "research_innovation":  ["research_innovation", "paper_score", "research_score"],
        "competition_practice": ["competition_practice", "competition_score"],
        "engineering_practice": ["engineering_practice", "internship_score"],
        "organization_service": ["organization_service", "student_work_score", "volunteer_score"],
        "growth_planning":      ["growth_planning", "major_score"],
    }
    result: dict = {}
    for dim, candidates in _key_map.items():
        for c in candidates:
            if c in scores_raw and scores_raw[c] is not None:
                result[dim] = float(scores_raw[c])
                break
        else:
            result[dim] = 0.0
    return result

