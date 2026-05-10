from __future__ import annotations
import re
from typing import Any

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WECHAT_RE = re.compile(r"(?:微信|联系方式|VX|vx|WeChat|wechat)[:：]?\s*[A-Za-z0-9_\-]{5,}", re.I)
PERSONAL_LINE_RE = re.compile(r"^(姓名|姓\s*名|民族|电话|联系方式|出生年月|籍贯|邮箱|邮\s*箱|政治面貌)[:： ]", re.I)

SENSITIVE_WORDS = ["电话", "联系方式", "微信", "邮箱", "出生年月", "籍贯", "民族"]


def remove_sensitive_text(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    text = PHONE_RE.sub("", text)
    text = EMAIL_RE.sub("", text)
    text = WECHAT_RE.sub("", text)
    # 不粗暴删除“姓名”，避免论文作者中出现姓名时破坏句子；只过滤整行个人信息
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if PERSONAL_LINE_RE.search(s):
            continue
        # 一行里如果同时含多个个人信息关键词，基本就是个人信息块
        if sum(1 for w in SENSITIVE_WORDS if w in s) >= 2:
            continue
        lines.append(s)
    return "\n".join(lines).strip()


def sanitize_profile_for_review(profile: dict) -> dict:
    """进入画像核对页前清洗隐私，防止手机号/邮箱/微信误入论文、实习等字段。"""
    if not isinstance(profile, dict):
        return {}
    profile = dict(profile)
    fields = [
        "competitions", "papers", "research_experiences", "internships",
        "projects", "student_work", "honors", "certificates", "skills",
    ]
    for field in fields:
        items = profile.get(field) or []
        if not isinstance(items, list):
            items = [items]
        cleaned = []
        for item in items:
            if isinstance(item, dict):
                obj = {k: remove_sensitive_text(v) if isinstance(v, str) else v for k, v in item.items()}
                # 删除全空 dict
                if any(v not in [None, "", [], {}] for v in obj.values()):
                    cleaned.append(obj)
            else:
                s = remove_sensitive_text(str(item))
                if s:
                    cleaned.append(s)
        profile[field] = cleaned
    return profile


def flatten_item(item: Any) -> str:
    """把 dict/list/string 转为适合 text_area 展示的一行，跳过隐私字段。"""
    if item is None:
        return ""
    if isinstance(item, str):
        return remove_sensitive_text(item)
    if isinstance(item, dict):
        skip = {"phone", "email", "wechat", "personal_info", "name"}
        parts = []
        for k, v in item.items():
            if k in skip or v in [None, "", [], {}]:
                continue
            if isinstance(v, list):
                v = "、".join(map(str, v))
            if isinstance(v, dict):
                continue
            parts.append(str(v))
        return remove_sensitive_text("；".join(parts))
    if isinstance(item, list):
        return "；".join(filter(None, [flatten_item(x) for x in item]))
    return remove_sensitive_text(str(item))


def list_to_review_text(items: Any) -> str:
    if not items:
        return ""
    if not isinstance(items, list):
        items = [items]
    lines = []
    for item in items:
        s = flatten_item(item).strip()
        if not s:
            continue
        # 避免明显个人信息块进入核对区
        if PERSONAL_LINE_RE.search(s) or sum(1 for w in SENSITIVE_WORDS if w in s) >= 2:
            continue
        lines.append(s)
    return "\n".join(lines)


def text_to_list(text: str) -> list[str]:
    return [remove_sensitive_text(x.strip()) for x in (text or "").splitlines() if remove_sensitive_text(x.strip())]
