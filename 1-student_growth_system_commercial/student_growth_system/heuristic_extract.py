from __future__ import annotations
import re
from .utils import remove_sensitive_text, sanitize_profile_for_review


def _lines(text: str) -> list[str]:
    out = []
    for line in (text or "").replace("\r", "\n").split("\n"):
        s = re.sub(r"\s+", " ", line).strip(" •\t")
        if s:
            out.append(s)
    return out


def _find_int(patterns: list[str], text: str):
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
    return None


def _find_gpa(text: str):
    m = re.search(r"(?:绩点|GPA|gpa)\s*[:：]?\s*(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _duration_months(start: str, end: str):
    try:
        sy, sm = map(int, start.split("."))
        ey, em = map(int, end.split("."))
        return max(1, (ey - sy) * 12 + (em - sm) + 1)
    except Exception:
        return None


def _extract_internships(text: str) -> list[dict]:
    internships = []
    # 匹配 “时间：2024.07——2024.09 公司：xxx 岗位：xxx ...” 到下一段时间/论文/自然语言处理等
    pattern = re.compile(
        r"时\s*间[:：]\s*(\d{4}\.\d{1,2})\s*[—\-–~至]+\s*(\d{4}\.\d{1,2})\s*公司[:：]\s*(.*?)\s*岗位[:：]\s*(.*?)(?=(?:时\s*间[:：]\s*\d{4}\.\d{1,2})|(?:\s*[A-Z][A-Za-z]+,)|(?:自然语言处理领域)|(?:算法研究领域)|(?:遥感领域)|$)",
        re.S,
    )
    for m in pattern.finditer(text):
        start, end = m.group(1), m.group(2)
        company = remove_sensitive_text(m.group(3)).strip()
        rest = remove_sensitive_text(m.group(4)).strip()
        # PDF 双栏文本可能把后面的论文列表拼到第一段实习后面，这里再次按语义截断
        rest = re.split(r"(?:实习经历\s*\(Internship experience\)|[A-Z][a-z]+,\s*[A-Z]\.?,)", rest)[0].strip()
        role = rest.split("技术栈")[0].split("经历描述")[0].strip(" ：:")[:40] or None
        skills = []
        for kw in ["SpringBoot", "Spring Boot", "MySQL", "Redis", "OCR", "Git", "Java", "Python", "PyTorch", "Pytorch", "LoRA", "DeepSpeed", "Accelerate", "FlashAttention", "SAM2", "分布式训练"]:
            if kw.lower() in rest.lower():
                skills.append(kw)
        internships.append({
            "company": company,
            "role": role,
            "duration_months": _duration_months(start, end),
            "description": rest[:600],
            "skills": sorted(set(skills)),
        })
    return internships


def _extract_papers(lines: list[str]) -> list[dict]:
    """按作者行聚合论文，避免 PDF 换行导致一篇论文拆成多条。"""
    blocks: list[str] = []
    cur: list[str] = []

    def is_author_start(s: str) -> bool:
        return re.search(r"^[A-Z][A-Za-z]+,\s*[A-Z]\.?,", s) is not None

    stop_markers = ["自然语言处理领域", "算法研究领域", "遥感领域", "时 间：", "时 间:", "技能奖项", "实习经历"]
    for s in lines:
        if any(m in s for m in stop_markers):
            if cur:
                blocks.append(" ".join(cur))
                cur = []
            continue
        if is_author_start(s):
            if cur:
                blocks.append(" ".join(cur))
            cur = [s]
        elif cur:
            # 作者行之后，继续收集明显属于论文的换行
            cur.append(s)
            if "(EI)" in s or "（EI）" in s or "SCI" in s or "外审" in s:
                blocks.append(" ".join(cur))
                cur = []
    if cur:
        blocks.append(" ".join(cur))

    papers = []
    for raw in blocks:
        if not any(x.lower() in raw.lower() for x in ["doi", "sci", "ei", "journal", "conference", "remote sensing", "ieee", "international journal", "complex & intelligent systems"]):
            continue
        if any(x in raw for x in ["数学建模", "竞赛", "比赛", "大赛", "奖"]):
            continue
        sci_zone = None
        m = re.search(r"SCI\s*([一二三四1234])\s*区", raw, re.I)
        if m:
            z = m.group(1)
            sci_zone = {"一": "Q1", "二": "Q2", "三": "Q3", "四": "Q4", "1": "Q1", "2": "Q2", "3": "Q3", "4": "Q4"}.get(z)
        indexed_by = []
        if re.search(r"SCI", raw, re.I): indexed_by.append("SCI")
        if re.search(r"EI", raw, re.I): indexed_by.append("EI")
        status = "under_review" if "外审" in raw else ("published" if ("doi" in raw.lower() or indexed_by) else None)
        mtitle = re.search(r"\(\d{4}\)\.\s*(.*?)(?:\.\s*(?:Remote Sensing|IEEE|International Journal|Complex|In International|In 2024)|\(SCI|\(EI|DOI|$)", raw)
        title = mtitle.group(1).strip() if mtitle else raw[:160]
        papers.append({
            "title": remove_sensitive_text(title)[:300],
            "venue": remove_sensitive_text(raw)[:500],
            "ccf_rank": None,
            "sci_zone": sci_zone,
            "indexed_by": indexed_by,
            "author_rank": None,
            "is_co_first": False,
            "status": status,
            "research_area": [],
        })
    return papers


def _extract_competitions(lines: list[str]) -> tuple[list[str], list[str]]:
    competitions, honors = [], []
    comp_kws = [
        "数学建模", "美赛", "MCM", "ICM", "MathorCup", "Mathorcup", "mathor",
        "机器人及人工智能", "机器人大赛", "人工智能大赛", "人工智能",
        "泰迪杯", "算法精英", "华为软件精英", "英语演讲",
        "挑战杯", "互联网+", "蓝桥杯", "ACM", "ICPC",
        "RoboMaster", "软件杯", "创新创业", "程序设计", "算法竞赛",
        "信息安全", "网络安全竞赛", "数据挖掘",
        "Finalist", "Meritorious", "Honorable",
    ]
    honor_kws = ["奖学金", "优秀", "科技论文报告会", "心理班会", "省级奖", "校级奖"]
    for s in lines:
        sl = s.lower()
        if any(x.lower() in sl for x in comp_kws):
            competitions.append(remove_sensitive_text(s))
        elif any(x in s for x in honor_kws):
            honors.append(remove_sensitive_text(s))
    return competitions, honors


def _extract_student_work(joined: str) -> list[str]:
    """Extract student work / volunteer entries from free text."""
    work = []
    sw_kws = [
        "班长", "团支书", "班委", "学习委员", "生活委员", "文艺委员",
        "学生会", "社团", "部长", "主席", "干部", "辅导员助理", "助管",
        "党支部", "团委", "志愿", "支教", "三下乡", "社会实践",
    ]
    for kw in sw_kws:
        if kw in joined:
            # Extract a short snippet around the keyword
            idx = joined.find(kw)
            snippet = joined[max(0, idx-10):idx+40].strip()
            work.append(remove_sensitive_text(snippet))
    return list(dict.fromkeys(work))  # deduplicate while preserving order


def _extract_target(joined: str) -> str | None:
    """Extract goal/target keywords from free text."""
    target_kws = [
        "希望", "目标", "打算", "计划", "想要", "准备", "考虑",
        "保研", "考研", "就业", "实习", "读研", "出国", "留学",
        "辅导员", "支教", "考公", "选调", "基层",
    ]
    found = [kw for kw in target_kws if kw in joined]
    if found:
        # Return a short excerpt around the first goal keyword
        kw = found[0]
        idx = joined.find(kw)
        return joined[max(0, idx-5):idx+60].strip()
    return None


def extract_profile_heuristic(text: str) -> dict:
    text = text or ""
    lines = _lines(text)
    joined = "\n".join(lines)

    cet4 = _find_int([r"CET[-\s]*4\s*[:：]?\s*(\d{3})", r"四级\s*[:：]?\s*(\d{3})"], joined)
    cet6 = _find_int([r"CET[-\s]*6\s*[:：]?\s*(\d{3})", r"六级\s*[:：]?\s*(\d{3})"], joined)
    gpa = _find_gpa(joined)

    name = None
    m = re.search(r"姓\s*名[:：]\s*([^\n\s]+)", joined)
    if m:
        name = m.group(1).strip()

    major = None
    # 优先从教育背景行识别本科专业，避免被“已推免至人工智能学院”等去向覆盖
    edu_major = re.search(r"中国地质大学（武汉）\s*计算机学院\s*([^\n]+?)\s*本科", joined)
    if edu_major:
        major = edu_major.group(1).strip()
    else:
        for x in ["数据科学与大数据技术", "计算机科学与技术", "软件工程", "网络空间安全", "信息安全", "地理信息科学", "人工智能", "机器人工程"]:
            if x in joined:
                major = x
                break

    college = "计算机学院" if "计算机学院" in joined else None
    school = "中国地质大学（武汉）" if "中国地质大学" in joined else None
    destination = None
    m = re.search(r"目前已推免至\s*(.+?)(?:\s|$)", joined)
    if m:
        destination = m.group(0).replace("目前已推免至", "").strip()

    competitions, honors = _extract_competitions(lines)
    papers = _extract_papers(lines)
    internships = _extract_internships(joined)
    student_work = _extract_student_work(joined)
    target = _extract_target(joined)

    skills = []
    for skill in ["C++", "Java", "Python", "SpringBoot", "Spring Boot", "MySQL", "Redis", "OCR", "Git", "PyTorch", "Pytorch", "LoRA", "DeepSpeed", "Accelerate", "FlashAttention", "SAM2", "机器学习", "深度学习", "后端", "算法", "多模态大模型", "遥感"]:
        if skill.lower() in joined.lower():
            skills.append(skill)

    research_experiences = []
    for marker in ["自然语言处理领域", "算法研究领域", "遥感领域"]:
        if marker in joined:
            idx = joined.find(marker)
            research_experiences.append(remove_sensitive_text(joined[idx:idx+700]))

    volunteer_hours = None
    m = re.search(r"志愿.*?(\d+)\s*(?:小时|h|H)", joined)
    if m:
        volunteer_hours = int(m.group(1))

    profile = {
        "personal_info": {"name": name, "phone": None, "email": None, "wechat": None},
        "name": name,
        "major": major,
        "college": college,
        "school": school,
        "gpa": gpa,
        "rank": None,
        "cet4": cet4,
        "cet6": cet6,
        "has_failed_course": True if "挂科" in joined and "无挂科" not in joined else False,
        "destination": destination,
        "competitions": competitions,
        "papers": papers,
        "research_experiences": research_experiences,
        "internships": internships,
        "projects": [],
        "student_work": student_work,
        "volunteer_hours": volunteer_hours,
        "honors": honors,
        "certificates": [],
        "skills": sorted(set(skills)),
        "target": target,
        "uncertainty": ["本地启发式抽取结果，建议在界面中人工核对。"],
    }
    return sanitize_profile_for_review(profile)
