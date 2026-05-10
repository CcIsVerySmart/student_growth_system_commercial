from __future__ import annotations
import json
from typing import Any
from .llm_client import SiliconFlowClient
from .config import DEFAULT_POLICY_SUMMARY

POLICY_EXTRACT_SYSTEM_PROMPT = """
你是计算机学院学生成长系统的政策规则抽取模块。
请从上传的政策文件文本中抽取用于路径推荐的压缩规则摘要。
只输出 JSON，不要输出解释文字。缺失信息沿用给定默认摘要或写成空字符串。
必须包含以下键：
{
  "normal_recommendation": "普通推免规则摘要，必须说明学业70%+考核30%、竞赛取最高项等",
  "special_a": "特殊专长A规则摘要，说明高水平竞赛/论文/突出成果、成果组合、基础资格等",
  "special_b": "特殊专长B/本硕博规则摘要，说明本硕博计划、科研精神、创新能力、科研成果等",
  "engineering": "工程专项规则摘要，说明综合考察而非只看实习",
  "service": "支教/辅导员规则摘要，说明学生工作、志愿服务、政治面貌等",
  "internship": "实习就业和校企合作单位推荐策略摘要"
}
"""

COMPANY_EXTRACT_SYSTEM_PROMPT = """
你是校企合作单位信息抽取模块。
请从 Excel 转换文本中抽取企业/单位画像。只输出 JSON，不要输出解释文字。
输出格式：
{
  "companies": [
    {
      "company_name": "单位名称",
      "cooperation_type": "合作类型，如实习基地/校企合作/联合培养/就业单位，未知写校企合作",
      "positions": ["岗位方向"],
      "required_skills": ["技能关键词"],
      "preferred_major": ["适合专业"],
      "difficulty": "低/中等/较高/高，无法判断写中等",
      "tags": ["后端", "算法", "Java", "实习"],
      "summary": "不超过120字的单位推荐摘要"
    }
  ]
}
要求：
1. 不要编造单位；
2. 岗位、技能、专业缺失时用空数组；
3. tags 要服务于后续匹配，尽量包含方向、技术栈和合作性质。
"""


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def extract_policy_summary_with_llm(policy_text: str, existing: dict | None = None) -> dict:
    client = SiliconFlowClient()
    if not client.available:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY，无法用大模型提取政策摘要。")
    existing = existing or DEFAULT_POLICY_SUMMARY
    user_prompt = "默认摘要如下，可在文件依据充分时覆盖：\n" + json.dumps(existing, ensure_ascii=False, indent=2) + "\n\n政策文件文本：\n" + policy_text[:30000]
    result = client.extract_json(POLICY_EXTRACT_SYSTEM_PROMPT, user_prompt, temperature=0.1, max_tokens=2500)
    merged = DEFAULT_POLICY_SUMMARY.copy()
    merged.update({k: v for k, v in result.items() if isinstance(v, str) and v.strip()})
    return merged


def extract_companies_with_llm(excel_text: str, source_id: str | None = None, source_name: str | None = None) -> list[dict]:
    client = SiliconFlowClient()
    if not client.available:
        raise RuntimeError("未配置 SILICONFLOW_API_KEY，无法用大模型提取校企合作单位。")
    result = client.extract_json(COMPANY_EXTRACT_SYSTEM_PROMPT, "Excel文本如下：\n" + excel_text[:30000], temperature=0.1, max_tokens=5000)
    companies = result.get("companies", []) if isinstance(result, dict) else []
    out = []
    for i, c in enumerate(companies):
        if not isinstance(c, dict):
            continue
        name = c.get("company_name") or c.get("单位") or c.get("公司")
        if not name:
            continue
        item = {
            "source_id": source_id,
            "source_name": source_name,
            "company_id": f"C{i + 1:03d}",
            "company_name": str(name),
            "cooperation_type": c.get("cooperation_type") or "校企合作",
            "positions": c.get("positions") or [],
            "required_skills": c.get("required_skills") or [],
            "preferred_major": c.get("preferred_major") or [],
            "description": c.get("description") or "",
            "difficulty": c.get("difficulty") or "中等",
            "tags": sorted(set(c.get("tags") or [])),
            "summary": (c.get("summary") or str(name))[:240],
        }
        out.append(item)
    return out
