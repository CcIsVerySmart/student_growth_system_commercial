from __future__ import annotations
import json
import hashlib
import uuid
import shutil
from pathlib import Path
from typing import Any
from .config import (
    STUDENTS_DB, COMPANIES_DB, POLICY_DB, QUERY_CACHE_DB, IMPORTED_FILES_DB,
    DEFAULT_POLICY_SUMMARY, UPLOAD_DIR
)


def load_json(path: Path, default: Any):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def text_hash(text: str) -> str:
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def new_source_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def load_students() -> list[dict]:
    return load_json(STUDENTS_DB, [])


def save_students(students: list[dict]):
    save_json(STUDENTS_DB, students)


def load_companies() -> list[dict]:
    return load_json(COMPANIES_DB, [])


def save_companies(companies: list[dict]):
    save_json(COMPANIES_DB, companies)


def load_policy() -> dict:
    return load_json(POLICY_DB, DEFAULT_POLICY_SUMMARY)


def save_policy(policy: dict):
    merged = DEFAULT_POLICY_SUMMARY.copy()
    merged.update(policy or {})
    save_json(POLICY_DB, merged)


def load_cache() -> dict:
    return load_json(QUERY_CACHE_DB, {})


def save_cache(cache: dict):
    save_json(QUERY_CACHE_DB, cache)


def load_imported_files() -> list[dict]:
    return load_json(IMPORTED_FILES_DB, [])


def save_imported_files(records: list[dict]):
    save_json(IMPORTED_FILES_DB, records)


def save_uploaded_file(uploaded_file, kind: str, source_id: str) -> str:
    safe_name = Path(uploaded_file.name).name
    target_dir = UPLOAD_DIR / kind
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source_id}_{safe_name}"
    data = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    target.write_bytes(data)
    return str(target)


def add_import_record(record: dict):
    records = load_imported_files()
    records.append(record)
    save_imported_files(records)


def remove_import_source(source_id: str) -> dict:
    """Remove one uploaded source and all derived structured data.
    For policy files, policy summary is reset to defaults because policy entries are merged.
    """
    records = load_imported_files()
    hit = next((r for r in records if r.get("source_id") == source_id), None)
    if not hit:
        return {"removed": False, "message": "未找到该文件来源。"}

    kind = hit.get("kind")
    if kind == "students":
        save_students([s for s in load_students() if s.get("source_id") != source_id])
    elif kind == "companies":
        save_companies([c for c in load_companies() if c.get("source_id") != source_id])
    elif kind == "policy":
        # 简化处理：移除政策来源时重置政策摘要，管理员可重新提取/保存。
        save_policy(DEFAULT_POLICY_SUMMARY)

    path = hit.get("saved_path")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    records = [r for r in records if r.get("source_id") != source_id]
    save_imported_files(records)
    save_cache({})
    return {"removed": True, "kind": kind, "message": "已移除文件及其提取结果，并清空相关缓存。"}


def clear_all_data():
    save_students([])
    save_companies([])
    save_policy(DEFAULT_POLICY_SUMMARY)
    save_cache({})
    save_imported_files([])
