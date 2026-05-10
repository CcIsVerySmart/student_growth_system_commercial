# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import logging
import re
import warnings
from typing import Any

import pandas as pd

from .scoring import calculate_dimension_scores

logger = logging.getLogger(__name__)

# ── semester order ─────────────────────────────────────────────────────────
SEMESTERS = ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上"]

# ── group column names (level-0 header) ────────────────────────────────────
GROUP_GPA = "平均学分绩点"
GROUP_POS = "担任职务"
GROUP_AWD = "所获奖项"
GROUP_EVL = "学期评价"
REQUIRED_GROUPS = {GROUP_GPA, GROUP_POS, GROUP_AWD, GROUP_EVL}

# ── basic field candidates ─────────────────────────────────────────────────
BASIC_FIELDS = {
    "id":               ["序号", "id", "编号"],
    "class_name":       ["班级", "class", "班"],
    "student_no":       ["学号", "student_no", "学生编号"],
    "name":             ["姓名", "name", "学生姓名"],
    "destination":      ["去向", "destination", "最终去向", "毕业去向"],
    "destination_unit": ["去向单位", "destination_unit", "单位"],
    "specialty":        ["特长", "specialty", "特长/爱好"],
}


# ── helpers ────────────────────────────────────────────────────────────────

def _clean_str(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return "" if s.lower() in ("nan", "none", "null") else s


def _to_float_or_none(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "nan", "none", "null", "无", "/", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def split_items(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return []
    try:
        data = json.loads(s)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return [x.strip() for x in re.split(r"[;；\n、]+", s) if x.strip()]


def first_present(row: dict, candidates: list[str], default=None):
    """Flexible column lookup for flat-dict rows (used by company loader)."""
    keys = {str(k).strip().lower(): k for k in row.keys()}
    for c in candidates:
        c_low = c.strip().lower()
        for low, raw in keys.items():
            if c_low == low or c_low in low:
                val = row.get(raw)
                if pd.notna(val) and val != "":
                    return val
    return default


# ── two-row header parser ──────────────────────────────────────────────────

def _parse_two_row_header(file_obj_or_path) -> tuple[pd.DataFrame, list[str]]:
    """Read an Excel with a two-row merged header.

    Row 0: level-0 group names (merged cells → NaN for continuation columns).
    Row 1: level-1 sub-names (semester labels for grouped columns, NaN for basics).

    Returns:
        df   – DataFrame with flat string column names like "平均学分绩点_大一上"
        cols – list of flat column names in order
    """
    # Read raw without any header so we can inspect both rows
    raw = pd.read_excel(file_obj_or_path, header=None, dtype=str)
    if raw.shape[0] < 2:
        raise ValueError("Excel 文件行数不足，无法识别两行表头。")

    row0 = list(raw.iloc[0])  # level-0 header
    row1 = list(raw.iloc[1])  # level-1 header

    # Forward-fill level-0 so merged cells propagate
    current_group = ""
    flat_cols: list[str] = []
    for l0, l1 in zip(row0, row1):
        l0_s = _clean_str(l0)
        l1_s = _clean_str(l1)
        if l0_s:
            current_group = l0_s
        if l1_s:
            flat_cols.append(f"{current_group}_{l1_s}")
        else:
            flat_cols.append(current_group)

    # Build data frame from data rows (skip first two header rows)
    data = raw.iloc[2:].reset_index(drop=True)
    data.columns = flat_cols

    return data, flat_cols


def _validate_groups(flat_cols: list[str]) -> None:
    """Raise if any required group is missing; warn if semester count != 7."""
    found_groups = set()
    for col in flat_cols:
        for g in REQUIRED_GROUPS:
            if col.startswith(g + "_") or col == g:
                found_groups.add(g)
    missing = REQUIRED_GROUPS - found_groups
    if missing:
        raise ValueError(
            f"Excel 表头缺少必要分组：{missing}。"
            '请确认表头包含"平均学分绩点"、"担任职务"、"所获奖项"、"学期评价"四组。'
        )
    for g in REQUIRED_GROUPS:
        sem_cols = [c for c in flat_cols if c.startswith(g + "_")]
        if len(sem_cols) != 7:
            warnings.warn(
                f'分组"{g}"下检测到 {len(sem_cols)} 个学期列，预期 7 个。',
                stacklevel=4,
            )


def _extract_semester_dict(row: pd.Series, group: str) -> dict[str, str | float | None]:
    """Extract {semester: value} for a given group from a flat-column row."""
    result: dict[str, Any] = {}
    for sem in SEMESTERS:
        col = f"{group}_{sem}"
        val = row.get(col)
        result[sem] = val if pd.notna(val) else None
    return result


# ── row → structured student ───────────────────────────────────────────────

def _row_to_structured_student(
    row: pd.Series,
    idx: int,
    source_id: str | None = None,
    source_name: str | None = None,
) -> dict | None:
    """Convert one data row to a fully structured student dict.

    Returns None (with a warning) if name or student_no is missing.
    """
    # ── basic fields ──────────────────────────────────────────────────────
    def _get(candidates: list[str]) -> str:
        for c in candidates:
            for col in row.index:
                if str(col).strip().lower() == c.lower() or c.lower() in str(col).strip().lower():
                    v = row.get(col)
                    if v is not None and pd.notna(v):
                        s = str(v).strip()
                        if s and s.lower() not in ("nan", "none"):
                            return s
        return ""

    name = _get(BASIC_FIELDS["name"])
    student_no = _get(BASIC_FIELDS["student_no"])

    if not name:
        warnings.warn(f"第 {idx + 3} 行姓名为空，已跳过。", stacklevel=3)
        return None
    if not student_no:
        warnings.warn(f"第 {idx + 3} 行（{name}）学号为空，已跳过。", stacklevel=3)
        return None

    # ── semester groups ───────────────────────────────────────────────────
    gpa_raw = _extract_semester_dict(row, GROUP_GPA)
    pos_raw = _extract_semester_dict(row, GROUP_POS)
    awd_raw = _extract_semester_dict(row, GROUP_AWD)
    evl_raw = _extract_semester_dict(row, GROUP_EVL)

    # Convert GPA values to float; keep None for missing/invalid
    gpa_by_semester: dict[str, float | None] = {}
    for sem, v in gpa_raw.items():
        gpa_by_semester[sem] = _to_float_or_none(v)

    # String fields: preserve newlines, normalise empty → None
    def _str_sem(raw: dict) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for sem, v in raw.items():
            s = _clean_str(v) if v is not None else ""
            out[sem] = s if s and s not in ("无", "/", "-", "—") else None
        return out

    positions_by_semester = _str_sem(pos_raw)
    awards_by_semester = _str_sem(awd_raw)
    evaluations_by_semester = _str_sem(evl_raw)

    student: dict[str, Any] = {
        "source_id": source_id,
        "source_name": source_name,
        # basic
        "id": _clean_str(_get(BASIC_FIELDS["id"])) or str(idx + 1),
        "class_name": _clean_str(_get(BASIC_FIELDS["class_name"])),
        "student_no": student_no,
        "name": name,
        "destination": _clean_str(_get(BASIC_FIELDS["destination"])),
        "destination_unit": _clean_str(_get(BASIC_FIELDS["destination_unit"])),
        "specialty": _clean_str(_get(BASIC_FIELDS["specialty"])),
        # semester groups
        "gpa_by_semester": gpa_by_semester,
        "positions_by_semester": positions_by_semester,
        "awards_by_semester": awards_by_semester,
        "evaluations_by_semester": evaluations_by_semester,
    }

    # ── derive flat profile for scoring ──────────────────────────────────
    profile = _derive_scoring_profile(student)
    student["profile"] = profile

    # ── compute 6-dim scores ──────────────────────────────────────────────
    scores = calculate_dimension_scores(profile)
    student["scores"] = scores

    # ── tags & summary ────────────────────────────────────────────────────
    student["tags"] = _build_tags(student, scores)
    student["summary"] = _build_summary(student)

    return student


def _derive_scoring_profile(student: dict) -> dict:
    """Flatten semester data into a scoring-compatible profile dict.

    - gpa: average of all non-None semester GPAs (weighted toward recent semesters)
    - competitions / honors: extracted from all-semester awards text
    - student_work: extracted from all-semester positions text
    - self_description: concatenation of all semester evaluations
    - destination / path_type: from basic fields
    """
    gpa_vals = [v for v in student["gpa_by_semester"].values() if v is not None]
    if gpa_vals:
        # Weight recent semesters more: last 3 semesters get 2× weight
        n = len(gpa_vals)
        weights = [1.0] * n
        for i in range(max(0, n - 3), n):
            weights[i] = 2.0
        gpa = sum(g * w for g, w in zip(gpa_vals, weights)) / sum(weights)
    else:
        gpa = None

    # Aggregate all awards text across semesters
    all_awards_text = "\n".join(
        v for v in student["awards_by_semester"].values() if v
    )
    # Aggregate all positions text
    all_positions_text = "\n".join(
        v for v in student["positions_by_semester"].values() if v
    )
    # Aggregate all evaluations
    all_evals_text = "\n".join(
        v for v in student["evaluations_by_semester"].values() if v
    )

    # Extract competitions from awards (lines containing competition keywords)
    competitions = _extract_competitions_from_text(all_awards_text)
    # Extract honors (scholarships, awards not competition-specific)
    honors = _extract_honors_from_text(all_awards_text)
    # Extract CET from awards text
    cet4, cet6 = _extract_cet_from_text(all_awards_text)
    # Extract volunteer hours from evaluations + positions
    volunteer_hours = _extract_volunteer_hours(all_evals_text + " " + all_positions_text)

    # Build student_work list from positions
    student_work = _extract_student_work_list(all_positions_text)

    # Infer destination / path_type from destination field
    destination = student.get("destination", "")
    path_type = _infer_path_type(destination)

    return {
        "student_id": student["student_no"],
        "name": student["name"],
        "major": "",  # not in this Excel; can be enriched later
        "gpa": round(gpa, 4) if gpa is not None else None,
        "cet4": cet4,
        "cet6": cet6,
        "has_failed_course": False,
        "competitions": competitions,
        "papers": [],
        "research_experiences": [],
        "internships": [],
        "projects": [],
        "student_work": student_work,
        "volunteer_hours": volunteer_hours,
        "honors": honors,
        "certificates": [],
        "skills": [],
        "target": "",
        "destination": destination,
        "destination_unit": student.get("destination_unit", ""),
        "path_type": path_type,
        "specialty": student.get("specialty", ""),
        # Pass full text blobs for heuristic scoring
        "self_description": all_evals_text,
        "_awards_text": all_awards_text,
        "_positions_text": all_positions_text,
    }


# ── text extraction helpers ────────────────────────────────────────────────

_COMPETITION_KW = [
    "竞赛", "比赛", "大赛", "挑战杯", "蓝桥杯", "ACM", "数学建模", "美赛", "MCM",
    "CTF", "创新创业", "互联网+", "一等奖", "二等奖", "三等奖", "特等奖",
    "省级", "国家级", "全国", "校级", "优秀奖", "获奖",
]
_HONOR_KW = [
    "奖学金", "国家奖学金", "国家励志", "省级奖学金", "校级奖学金",
    "优秀学生", "三好学生", "优秀团员", "优秀干部", "标兵", "先进个人",
    "优秀毕业生", "荣誉",
]
_CET_PATTERNS = [
    (re.compile(r"CET[-\s]?4[^\d]*?(\d{3,3})", re.I), "cet4"),
    (re.compile(r"四级[^\d]*?(\d{3,3})", re.I), "cet4"),
    (re.compile(r"CET[-\s]?6[^\d]*?(\d{3,3})", re.I), "cet6"),
    (re.compile(r"六级[^\d]*?(\d{3,3})", re.I), "cet6"),
    (re.compile(r"CET[-\s]?4\s*通过", re.I), "cet4_pass"),
    (re.compile(r"CET[-\s]?6\s*通过", re.I), "cet6_pass"),
    (re.compile(r"四级\s*通过", re.I), "cet4_pass"),
    (re.compile(r"六级\s*通过", re.I), "cet6_pass"),
]
_VOLUNTEER_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?小时")


def _extract_competitions_from_text(text: str) -> list[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in re.split(r"[；;\n]", text) if ln.strip()]
    result = []
    for ln in lines:
        if any(kw in ln for kw in _COMPETITION_KW):
            result.append(ln)
    return result


def _extract_honors_from_text(text: str) -> list[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in re.split(r"[；;\n]", text) if ln.strip()]
    result = []
    for ln in lines:
        if any(kw in ln for kw in _HONOR_KW):
            result.append(ln)
    return result


def _extract_cet_from_text(text: str) -> tuple[float | None, float | None]:
    cet4: float | None = None
    cet6: float | None = None
    for pat, kind in _CET_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        if kind == "cet4":
            try:
                cet4 = float(m.group(1))
            except Exception:
                pass
        elif kind == "cet6":
            try:
                cet6 = float(m.group(1))
            except Exception:
                pass
        elif kind == "cet4_pass" and cet4 is None:
            cet4 = 425.0  # treat "通过" as minimum passing score
        elif kind == "cet6_pass" and cet6 is None:
            cet6 = 425.0
    return cet4, cet6


def _extract_volunteer_hours(text: str) -> float:
    total = 0.0
    for m in _VOLUNTEER_PATTERN.finditer(text):
        try:
            total += float(m.group(1))
        except Exception:
            pass
    if total == 0 and ("志愿" in text or "支教" in text):
        return 10.0  # default if mentioned but no hours found
    return total


_POSITION_KW = [
    "主席", "部长", "班长", "团支书", "书记", "学生会", "党支部", "团委",
    "班委", "干部", "委员", "副班长", "副部长", "社团", "助管", "辅导员助理",
    "组织委员", "宣传委员", "生活委员", "学习委员", "文艺委员", "体育委员",
]


def _extract_student_work_list(text: str) -> list[str]:
    if not text:
        return []
    lines = [ln.strip() for ln in re.split(r"[；;\n]", text) if ln.strip()]
    result = []
    for ln in lines:
        if any(kw in ln for kw in _POSITION_KW):
            result.append(ln)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped = []
    for item in result:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _infer_path_type(destination: str) -> str:
    if not destination:
        return ""
    d = destination.lower()
    if any(x in d for x in ["保研", "推免", "直博", "硕士", "研究生"]):
        return "普通推免"
    if any(x in d for x in ["考研", "考取"]):
        return "考研"
    if any(x in d for x in ["就业", "工作", "入职", "签约"]):
        return "实习就业"
    if any(x in d for x in ["考公", "选调", "公务员"]):
        return "考公"
    if any(x in d for x in ["支教", "基层", "西部"]):
        return "支教计划"
    return ""


def _build_tags(student: dict, scores: dict) -> list[str]:
    tags: set[str] = set()
    dest = student.get("destination", "")
    if dest:
        pt = _infer_path_type(dest)
        if pt:
            tags.add(pt)
    text = str(student)
    for tag in ["保研", "考研", "就业", "实习", "后端", "前端", "算法",
                "人工智能", "网络安全", "数据", "GIS", "学生工作", "支教"]:
        if tag in text:
            tags.add(tag)
    if scores.get("gpa_score", 0) >= 88:
        tags.add("GPA高")
    if scores.get("competition_score", 0) >= 60:
        tags.add("竞赛强")
    if scores.get("student_work_score", 0) >= 55:
        tags.add("学生工作强")
    return sorted(tags)


def _build_summary(student: dict) -> str:
    bits = []
    gpa_vals = [v for v in student["gpa_by_semester"].values() if v is not None]
    if gpa_vals:
        bits.append(f"GPA均值 {sum(gpa_vals)/len(gpa_vals):.2f}")
    dest = student.get("destination", "")
    if dest:
        bits.append(f"去向: {dest}")
    dest_unit = student.get("destination_unit", "")
    if dest_unit:
        bits.append(f"单位: {dest_unit}")
    # Top awards
    all_awards = [v for v in student["awards_by_semester"].values() if v]
    if all_awards:
        bits.append(f"奖项: {all_awards[0][:40]}")
    return "；".join(bits)[:240]


# ── public API ─────────────────────────────────────────────────────────────

def load_students_excel(
    file_obj_or_path,
    source_id: str | None = None,
    source_name: str | None = None,
) -> list[dict]:
    """Parse a two-row-header student Excel and return structured student dicts.

    Logs:
    - Number of students successfully parsed
    - Column structure detected
    - First student's parsed result
    - Any skipped rows (missing name / student_no / GPA parse errors)
    """
    data, flat_cols = _parse_two_row_header(file_obj_or_path)
    _validate_groups(flat_cols)

    logger.info("Excel 列结构（共 %d 列）: %s", len(flat_cols), flat_cols)

    students: list[dict] = []
    for idx, (_, row) in enumerate(data.iterrows()):
        # Skip fully empty rows
        if row.isna().all():
            continue
        s = _row_to_structured_student(row, idx, source_id=source_id, source_name=source_name)
        if s is not None:
            students.append(s)

    logger.info("成功解析学生 %d 条", len(students))
    if students:
        first = students[0]
        logger.info(
            "第一条学生示例 — 姓名: %s, 学号: %s, GPA均值: %s, 去向: %s",
            first.get("name"),
            first.get("student_no"),
            {k: v for k, v in first["gpa_by_semester"].items() if v is not None},
            first.get("destination"),
        )

    return students


# ── company loader (unchanged logic, kept here for import compatibility) ───

def row_to_company_profile(
    row: dict,
    idx: int,
    source_id: str | None = None,
    source_name: str | None = None,
) -> dict:
    name = first_present(row, ["单位", "公司", "企业", "company", "合作单位"], f"合作单位{idx + 1}")
    positions = split_items(first_present(row, ["岗位", "职位", "position", "招聘"], ""))
    skills = split_items(first_present(row, ["技能", "要求", "技术", "skill"], ""))
    majors = split_items(first_present(row, ["专业", "major"], ""))
    ctype = str(first_present(row, ["类型", "合作类型", "cooperation"], "校企合作"))
    desc = str(first_present(row, ["介绍", "描述", "备注", "description"], ""))
    text = " ".join([str(name), str(positions), str(skills), str(majors), ctype, desc])
    tags = []
    for tag in ["后端", "前端", "算法", "测试", "数据", "安全", "Java", "Python", "C++", "GIS", "实习", "就业", "校企合作"]:
        if tag.lower() in text.lower():
            tags.append(tag)
    return {
        "source_id": source_id,
        "source_name": source_name,
        "company_id": f"C{idx + 1:03d}",
        "company_name": str(name),
        "cooperation_type": ctype,
        "positions": positions,
        "required_skills": skills,
        "preferred_major": majors,
        "description": desc,
        "difficulty": str(first_present(row, ["难度", "difficulty"], "中等")),
        "tags": sorted(set(tags)),
        "summary": f"{name}｜{ctype}｜岗位：{'、'.join(map(str, positions[:3]))}｜技能：{'、'.join(map(str, skills[:5]))}"[:240],
    }


def load_companies_excel(
    file_obj_or_path,
    source_id: str | None = None,
    source_name: str | None = None,
) -> list[dict]:
    df = pd.read_excel(file_obj_or_path)
    df = df.dropna(how="all")
    return [
        row_to_company_profile(row.to_dict(), i, source_id=source_id, source_name=source_name)
        for i, row in df.iterrows()
    ]


def excel_to_text(file_obj_or_path, max_rows: int = 200) -> str:
    df = pd.read_excel(file_obj_or_path)
    df = df.dropna(how="all").head(max_rows)
    return df.to_csv(index=False)


# ── legacy compat: build_student_summary ──────────────────────────────────

def build_student_summary(p: dict) -> str:
    """Compatibility shim — works for both old flat profiles and new structured students."""
    if "gpa_by_semester" in p:
        return _build_summary(p)
    bits = []
    if p.get("gpa") not in [None, "", "nan"]:
        bits.append(f"GPA {p.get('gpa')}")
    for key, label in [("competitions", "竞赛"), ("papers", "论文"),
                       ("internships", "实习"), ("student_work", "学生工作")]:
        items = p.get(key) or []
        if items:
            bits.append(f"{label}: {str(items[:2])}")
    if p.get("destination"):
        bits.append(f"最终去向: {p.get('destination')}")
    return "；".join(bits)[:240]
