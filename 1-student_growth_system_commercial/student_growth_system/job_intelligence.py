from __future__ import annotations

import os
import re
import json
import requests
from typing import Any


def _text(profile: dict) -> str:
    return " ".join(map(str, [
        profile.get("major", ""),
        profile.get("skills", []),
        profile.get("internships", []),
        profile.get("projects", []),
        profile.get("research_experiences", []),
        profile.get("target", ""),
    ])).lower()


def infer_role_keywords(profile: dict) -> list[str]:
    """Infer job direction from internship/project/skill text."""
    text = _text(profile)
    roles: list[str] = []
    rules = [
        (["后端", "java", "spring", "redis", "mysql", "kafka", "go"], "后端开发实习生"),
        (["算法", "pytorch", "深度学习", "机器学习", "大模型", "llm", "transformer", "遥感", "sam", "lora"], "算法工程师实习生"),
        (["数据", "sql", "python", "数据分析", "建模", "可视化"], "数据分析实习生"),
        (["前端", "vue", "react", "javascript", "typescript"], "前端开发实习生"),
        (["测试", "自动化测试", "selenium", "pytest"], "测试开发实习生"),
        (["安全", "网络安全", "ctf", "渗透"], "网络安全实习生"),
        (["gis", "遥感", "测绘", "地理信息"], "GIS/遥感开发实习生"),
        (["产品", "用户", "需求", "原型"], "产品经理实习生"),
    ]
    for kws, role in rules:
        if any(k.lower() in text for k in kws):
            roles.append(role)
    if not roles:
        roles.append("软件开发实习生")
    return roles[:3]


def default_core_functions(role: str, profile: dict | None = None) -> list[str]:
    r = role.lower()
    if "后端" in role or "java" in r:
        return ["接口设计与开发", "数据库表结构与查询优化", "缓存/消息队列等中间件应用", "业务模块联调与上线维护"]
    if "算法" in role or "大模型" in role:
        return ["数据清洗与标注校验", "模型训练与评估", "算法模块调参与优化", "实验复现与技术文档沉淀"]
    if "数据分析" in role:
        return ["业务数据清洗", "SQL取数与指标分析", "报表/看板搭建", "问题诊断与策略建议"]
    if "前端" in role:
        return ["页面组件开发", "接口联调", "交互体验优化", "前端工程化与性能优化"]
    if "测试" in role:
        return ["测试用例设计", "接口/自动化测试", "缺陷跟踪", "质量数据分析"]
    if "安全" in role:
        return ["漏洞验证", "安全测试", "日志分析", "安全加固建议"]
    if "gis" in r or "遥感" in role:
        return ["遥感/GIS数据处理", "空间数据分析", "模型或算法服务集成", "地图/影像应用开发"]
    return ["参与项目研发", "完成模块设计与实现", "协助测试联调", "沉淀技术文档"]


def default_salary(role: str, is_internship: bool = True) -> str:
    """Fallback salary wording. Actual salaries vary by city/company; online snippets override when available."""
    if is_internship:
        if any(k in role for k in ["算法", "大模型", "后端", "开发"]):
            return "实习常见区间约 150-350 元/天，具体以城市、公司和岗位 JD 为准"
        return "实习常见区间约 100-250 元/天，具体以城市、公司和岗位 JD 为准"
    return "薪资需结合城市、学历、岗位和公司级别确认，建议以最新招聘信息为准"


def _extract_salary_from_text(text: str) -> str | None:
    patterns = [
        r"\d+(?:\.\d+)?\s*[-~至]\s*\d+(?:\.\d+)?\s*[kK千万]/?月?",
        r"\d+\s*[-~至]\s*\d+\s*元/天",
        r"\d+\s*[-~至]\s*\d+\s*元每天",
        r"\d+\s*[-~至]\s*\d+\s*万/年",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return None


def tavily_search(query: str, max_results: int = 3) -> list[dict[str, str]]:
    """Optional online search via Tavily. Set TAVILY_API_KEY in .env to enable."""
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": max_results,
                "include_answer": False,
                "include_raw_content": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return [
            {
                "title": str(r.get("title", "")),
                "url": str(r.get("url", "")),
                "content": str(r.get("content", ""))[:500],
            }
            for r in data.get("results", [])
        ]
    except Exception:
        return []


def make_company_card(company: dict, profile: dict, use_web: bool = False) -> dict:
    roles = company.get("positions") or company.get("岗位") or []
    if isinstance(roles, str):
        roles = [roles]
    inferred_roles = infer_role_keywords(profile)
    role = roles[0] if roles else inferred_roles[0]
    name = company.get("company_name") or company.get("单位名称") or "推荐单位"
    search_results: list[dict[str, str]] = []
    salary = company.get("salary_treatment") or company.get("薪资待遇") or default_salary(role)
    core = company.get("core_functions") or company.get("核心职能") or default_core_functions(role, profile)
    if isinstance(core, str):
        core = [x.strip() for x in re.split(r"[;；、\n]", core) if x.strip()]
    if use_web:
        query = f"{name} {role} 实习 招聘 核心职责 薪资待遇"
        search_results = tavily_search(query, max_results=3)
        combined = " ".join([r.get("title", "") + " " + r.get("content", "") for r in search_results])
        found_salary = _extract_salary_from_text(combined)
        if found_salary:
            salary = found_salary
    return {
        "company_id": company.get("company_id"),
        "company_name": name,
        "position": role,
        "cooperation_type": company.get("cooperation_type") or company.get("合作类型") or "校企合作/候选单位",
        "core_functions": core[:4],
        "salary_treatment": salary,
        "required_skills": company.get("required_skills") or [],
        "match_score": company.get("match_score", 0),
        "match_reason": company.get("match_reason") or "与学生专业、技能或实习方向匹配。",
        "online_references": search_results,
        "is_online_enriched": bool(search_results),
    }


def build_external_job_cards(profile: dict, max_cards: int = 3, use_web: bool = False) -> list[dict]:
    """Generate external job cards. If Tavily is enabled, enrich from online snippets; otherwise provide role-level cards."""
    cards = []
    for role in infer_role_keywords(profile)[:max_cards]:
        refs = tavily_search(f"{role} 实习 招聘 薪资 核心职责", max_results=3) if use_web else []
        combined = " ".join([r.get("title", "") + " " + r.get("content", "") for r in refs])
        salary = _extract_salary_from_text(combined) or default_salary(role)
        cards.append({
            "company_name": "其他单位方向",
            "position": role,
            "cooperation_type": "外部岗位检索方向",
            "core_functions": default_core_functions(role, profile),
            "salary_treatment": salary,
            "required_skills": [],
            "match_score": 70,
            "match_reason": "根据学生已有实习/项目/技能标签推断的外部岗位方向，可用于校企合作单位之外的投递扩展。",
            "online_references": refs,
            "is_online_enriched": bool(refs),
        })
    return cards
