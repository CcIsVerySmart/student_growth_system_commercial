from __future__ import annotations
import argparse
import json
from pathlib import Path
from student_growth_system.data_loader import load_students_excel, load_companies_excel
from student_growth_system.storage import save_students, save_companies, load_students, load_companies
from student_growth_system.recommender import run_recommendation


def cmd_init(args):
    if args.students:
        students = load_students_excel(args.students)
        save_students(students)
        print(f"已导入学生 {len(students)} 条")
    if args.companies:
        companies = load_companies_excel(args.companies)
        save_companies(companies)
        print(f"已导入合作单位 {len(companies)} 条")
    print(f"当前学生库：{len(load_students())} 条，合作单位：{len(load_companies())} 条")


def cmd_recommend(args):
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    result = run_recommendation(text, use_extract_llm=not args.no_extract_llm, use_advice_llm=not args.no_advice_llm)

    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告已保存至 {args.output}")

    if args.output_docx:
        from student_growth_system.report_exporter import build_word_report
        buf = build_word_report(result)
        Path(args.output_docx).write_bytes(buf.read())
        print(f"Word 报告已保存至 {args.output_docx}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not args.output and not args.output_docx:
        print(result["advice"])


def main():
    parser = argparse.ArgumentParser(description="学生成长路径推荐系统")
    sub = parser.add_subparsers(required=True)
    p1 = sub.add_parser("init", help="导入学生和校企单位 Excel")
    p1.add_argument("--students", default="")
    p1.add_argument("--companies", default="")
    p1.set_defaults(func=cmd_init)
    p2 = sub.add_parser("recommend", help="基于自述文本生成建议")
    p2.add_argument("--text", default="")
    p2.add_argument("--file", default="")
    p2.add_argument("--no-extract-llm", action="store_true")
    p2.add_argument("--no-advice-llm", action="store_true")
    p2.add_argument("--json", action="store_true")
    p2.add_argument("--output", default="", help="保存 JSON 报告到指定路径")
    p2.add_argument("--output-docx", default="", help="保存 Word 报告到指定路径")
    p2.set_defaults(func=cmd_recommend)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
