from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
UPLOAD_DIR = DATA_DIR / "uploads"
ASSETS_DIR = ROOT_DIR / "assets"
FORM_DIR = ASSETS_DIR / "forms"

for p in [DATA_DIR, CACHE_DIR, UPLOAD_DIR, ASSETS_DIR, FORM_DIR]:
    p.mkdir(parents=True, exist_ok=True)

STUDENTS_DB = DATA_DIR / "students.json"
COMPANIES_DB = DATA_DIR / "companies.json"
POLICY_DB = DATA_DIR / "policy_rules.json"
QUERY_CACHE_DB = DATA_DIR / "query_cache.json"
IMPORTED_FILES_DB = DATA_DIR / "imported_files.json"

COUNSELOR_FORM_PATH = FORM_DIR / "中国地质大学2025-2026学年1+3辅导员报名表.docx"
BENSHUOBO_FORM_PATH = FORM_DIR / "本硕博贯通培养计划申请表.xlsx"

SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
SF_MODEL_NAME = os.getenv("SF_MODEL_NAME", "deepseek-ai/DeepSeek-V3.1")
SF_BASE_URL = os.getenv("SF_BASE_URL", "https://api.siliconflow.cn/v1/chat/completions")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

DIMENSIONS = [
    "academic_foundation",
    "research_innovation",
    "competition_practice",
    "engineering_practice",
    "organization_service",
    "growth_planning",
]

DIMENSION_LABELS = {
    "academic_foundation": "学业基础",
    "research_innovation": "科研创新",
    "competition_practice": "竞赛实践",
    "engineering_practice": "工程实践",
    "organization_service": "组织服务",
    "growth_planning": "成长规划",
}

DEFAULT_POLICY_SUMMARY = {
    "normal_recommendation": "普通推免按学业成绩70%+考核成绩30%综合评价，竞赛类在普通推免中按最高项取分，不叠加。",
    "special_a": "特殊专长A类重点考察高水平竞赛、论文、创新成果，可考虑成果组合与个人贡献。",
    "special_b": "特殊专长B/本硕博重点考察科研精神、创新能力、科研成果、导师方向匹配和长期科研潜力。",
    "engineering": "工程专项综合考察学业基础、工程项目、实习经历、竞赛科研、技术栈成熟度与项目方向匹配。",
    "service": "支教计划和辅导员计划重点考察学生工作、志愿服务、组织协调能力、政治面貌与综合素质。",
    "internship": "实习就业路径优先考虑实习质量、项目深度、技术栈和校企合作单位匹配度。",
    "fallback": "考研和考公属于最低优先级兜底路径；只在保研、专项、工程、校企实习和就业路径都不明显时才作为主推荐。",
}
