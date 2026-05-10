from __future__ import annotations
import json
import os
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

from student_growth_system.config import DIMENSIONS, DIMENSION_LABELS, ADMIN_PASSWORD, DEFAULT_POLICY_SUMMARY, COUNSELOR_FORM_PATH, BENSHUOBO_FORM_PATH
from student_growth_system.storage import (
    load_students, save_students, load_companies, save_companies, load_policy, save_policy,
    clear_all_data, load_cache, save_cache, load_imported_files, add_import_record,
    remove_import_source, new_source_id, save_uploaded_file
)
from student_growth_system.data_loader import load_students_excel, load_companies_excel, excel_to_text
from student_growth_system.recommender import run_recommendation, extract_student_profile, build_context, generate_llm_advice
from student_growth_system.scoring import calculate_dimension_scores, calculate_path_scores
from student_growth_system.matcher import match_similar_seniors, match_companies
from student_growth_system.text_extract import extract_text_from_file
from student_growth_system.llm_client import SiliconFlowClient
from student_growth_system.llm_extractors import extract_policy_summary_with_llm, extract_companies_with_llm
from student_growth_system.utils import list_to_review_text, text_to_list, sanitize_profile_for_review
from student_growth_system.chat_agent import answer_student_question
from student_growth_system.report_exporter import build_word_report, report_filename

st.set_page_config(
    page_title="智伴同行",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS_PATH = Path(__file__).parent / "assets" / "style.css"


def load_css():
    if _CSS_PATH.exists():
        css = _CSS_PATH.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


load_css()


def hero(title: str, subtitle: str, badges: list[str] | None = None):
    badge_html = ""
    if badges:
        badge_html = '<div class="hero-badges">' + "".join(
            f'<span class="hero-badge">{b}</span>' for b in badges
        ) + "</div>"
    st.markdown(f"""
    <div class="hero">
      <h1>{title}</h1>
      <p>{subtitle}</p>
      {badge_html}
    </div>
    """, unsafe_allow_html=True)


def card_start(title: str | None = None, subtitle: str | None = None):
    st.markdown('<div class="card">', unsafe_allow_html=True)
    if title:
        st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="subtle">{subtitle}</div>', unsafe_allow_html=True)


def card_end():
    st.markdown('</div>', unsafe_allow_html=True)


def metric_card(label: str, value: str, hint: str = ""):
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value">{value}</div>
      <div class="metric-hint">{hint}</div>
    </div>
    """, unsafe_allow_html=True)


def score_badge(score: float) -> str:
    cls = "success-badge" if score >= 75 else "warning-badge" if score >= 55 else "danger-badge"
    return f'<span class="badge {cls}">{score:.1f}/100</span>'

def safe_dataframe(data, **kwargs):
    """Render a table. If pyarrow DLL fails on Windows, fall back to a simple table."""
    try:
        st.dataframe(data, **kwargs)
    except Exception as e:
        st.warning(f"表格预览组件加载失败，已切换为简易表格：{e}")
        try:
            st.table(data)
        except Exception:
            st.write(data)


def download_path_forms(main_path: str):
    """Show reference form downloads for route-specific recommendations."""
    main_path = main_path or ""
    if "辅导员" in main_path and COUNSELOR_FORM_PATH.exists():
        st.download_button(
            "下载 1+3 辅导员报名表",
            data=COUNSELOR_FORM_PATH.read_bytes(),
            file_name=COUNSELOR_FORM_PATH.name,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True,
        )
    if ("特殊专长B" in main_path or "本硕博" in main_path or "本-硕-博" in main_path) and BENSHUOBO_FORM_PATH.exists():
        st.download_button(
            "下载 本硕博贯通培养计划申请表",
            data=BENSHUOBO_FORM_PATH.read_bytes(),
            file_name=BENSHUOBO_FORM_PATH.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )



def html_escape(x):
    import html
    return html.escape(str(x or ""))


def render_senior_cards(seniors: list[dict]):
    if not seniors:
        st.info("暂无历史学生数据。")
        return
    html = ['<div class="senior-grid">']
    for idx, item in enumerate(seniors, start=1):
        case_id = html_escape(item.get("case_id") or f"匿名案例{idx}")
        major = html_escape(item.get("major") or "未标注专业")
        path = html_escape(item.get("path_type") or item.get("growth_destination_type") or "成长路径")
        dest = html_escape(item.get("destination") or "未标注去向")
        sim = html_escape(item.get("similarity", ""))
        summary = html_escape(item.get("summary") or "暂无成长路径摘要")
        reason = html_escape(item.get("match_reason") or "综合画像相似度较高。")
        html.append(
            '<div class="info-card">'
            f'<span class="small-chip">{case_id}</span><span class="small-chip">相似度 {sim}%</span>'
            f'<h4>{path}</h4>'
            f'<div class="line"><b>专业：</b>{major}</div>'
            f'<div class="line"><b>去向：</b>{dest}</div>'
            f'<div class="line"><b>成长路径：</b>{summary}</div>'
            f'<div class="reason"><b>匹配原因：</b>{reason}</div>'
            '</div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


def render_job_cards(cards: list[dict]):
    if not cards:
        st.info("暂无校企合作单位或外部岗位推荐。")
        return
    html = ['<div class="job-grid">']
    for c in cards:
        name = html_escape(c.get("company_name") or "推荐单位")
        pos = html_escape(c.get("position") or "推荐岗位")
        score = html_escape(c.get("match_score", ""))
        ctype = html_escape(c.get("cooperation_type") or "候选单位")
        salary = html_escape(c.get("salary_treatment") or "以最新招聘信息为准")
        reason = html_escape(c.get("match_reason") or "与学生画像匹配。")
        core = c.get("core_functions") or []
        if isinstance(core, str):
            core = [core]
        core_html = "".join([f"<li>{html_escape(x)}</li>" for x in core[:4]])
        refs = c.get("online_references") or []
        ref_hint = "已联网检索岗位信息" if refs else "本地岗位画像/校企库推荐"
        html.append(
            '<div class="info-card">'
            f'<span class="small-chip">{ctype}</span><span class="small-chip">匹配度 {score}</span>'
            f'<h4>{name}</h4>'
            f'<div class="line"><b>推荐岗位：</b>{pos}</div>'
            f'<div class="line"><b>薪资待遇：</b>{salary}</div>'
            f'<div class="line"><b>核心职能：</b><ul style="margin:6px 0 0 18px; padding:0;">{core_html}</ul></div>'
            f'<div class="reason"><b>匹配原因：</b>{reason}</div>'
            f'<div class="muted">{ref_hint}，薪资和岗位以企业最新招聘信息为准。</div>'
            '</div>'
        )
    html.append('</div>')
    st.markdown("".join(html), unsafe_allow_html=True)

def radar_chart(scores: dict):
    labels = [DIMENSION_LABELS[d] for d in DIMENSIONS]
    values = [float(scores.get(d, 0) or 0) for d in DIMENSIONS]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=values + [values[0]], theta=labels + [labels[0]], fill='toself', name='当前学生画像'))
    fig.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=False,
        height=420,
        margin=dict(l=40, r=40, t=40, b=40),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def path_bar_chart(path_scores: dict):
    df = pd.DataFrame({"路径": list(path_scores.keys()), "适配度": list(path_scores.values())}).sort_values("适配度", ascending=True)
    fig = px.bar(df, x="适配度", y="路径", orientation="h", text="适配度")
    fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
    fig.update_layout(
        height=390,
        xaxis_range=[0, 105],
        margin=dict(l=10, r=40, t=25, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="适配度 / 100",
        yaxis_title="",
    )
    return fig


def profile_editor(profile: dict):
    profile = sanitize_profile_for_review(profile)
    with st.expander("核对/微调学生画像（修改后点击下方按钮重新评估）", expanded=True):
        st.caption("系统已按语义把个人信息、竞赛、论文、实习分区；如果 PDF 排版复杂，请在这里做最终核对。")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            profile["major"] = st.text_input("专业", value=str(profile.get("major") or ""), key="edit_major")
        with c2:
            profile["gpa"] = st.number_input("绩点", min_value=0.0, max_value=5.0, value=float(profile.get("gpa") or 0), step=0.01, key="edit_gpa")
        with c3:
            profile["cet4"] = st.number_input("CET4", min_value=0, max_value=710, value=int(profile.get("cet4") or 0), step=1, key="edit_cet4")
        with c4:
            profile["cet6"] = st.number_input("CET6", min_value=0, max_value=710, value=int(profile.get("cet6") or 0), step=1, key="edit_cet6")
        with c5:
            profile["volunteer_hours"] = st.number_input("志愿时长", min_value=0, max_value=1000, value=int(profile.get("volunteer_hours") or 0), step=1, key="edit_volunteer_hours")

        profile["competitions"] = text_to_list(st.text_area("竞赛经历（每行一条）", value=list_to_review_text(profile.get("competitions")), key="edit_competitions", height=130))
        profile["papers"] = text_to_list(st.text_area("论文/专利/成果（每行一条）", value=list_to_review_text(profile.get("papers")), key="edit_papers", height=170))
        profile["internships"] = text_to_list(st.text_area("实习经历（每行一条）", value=list_to_review_text(profile.get("internships")), key="edit_internships", height=150))
        profile["research_experiences"] = text_to_list(st.text_area("科研/项目经历（每行一条）", value=list_to_review_text(profile.get("research_experiences") or profile.get("projects")), key="edit_research", height=130))
        profile["student_work"] = text_to_list(st.text_area("学生工作/志愿服务（每行一条）", value=list_to_review_text(profile.get("student_work")), key="edit_student_work", height=110))
    return sanitize_profile_for_review(profile)


def sidebar_nav():
    st.sidebar.markdown("""
    <div style="padding:16px 8px 20px;">
      <div style="font-size:20px;font-weight:800;color:#f1f5f9;letter-spacing:-.01em;">🎓 智伴同行</div>
      <div style="font-size:12px;color:#94a3b8;margin-top:4px;">智能体系统</div>
    </div>
    """, unsafe_allow_html=True)
    pages = ["用户端｜路径评估", "智能问答｜AI辅导员", "管理员｜数据导入"]
    if st.session_state.get("admin_ok"):
        pages += ["管理员｜规则配置", "数据看板", "系统设置"]
    page = st.sidebar.radio("导航", pages, label_visibility="collapsed")
    st.sidebar.divider()
    return page


def admin_login() -> bool:
    if st.session_state.get("admin_ok"):
        return True
    card_start("管理员登录", "上传和维护学生信息、校企合作单位、政策规则需要管理员权限。")
    pwd = st.text_input("管理员密码", type="password", placeholder="默认 admin123，可通过环境变量 ADMIN_PASSWORD 修改")
    if st.button("登录", use_container_width=True):
        if pwd == ADMIN_PASSWORD:
            st.session_state.admin_ok = True
            st.success("登录成功")
            st.rerun()
        else:
            st.error("密码错误")
    card_end()
    return False


def page_student():
    hero(
        "智伴同行——辅导员指导学生成长的AI助手",
        "融合六维能力画像、多指标综合评价（TOPSIS）、历史案例匹配与大模型建议生成，为辅导员提供学生成长分析与帮扶指导依据。",
        badges=["六维能力画像", "9条成长路径", "目标意向识别", "相似案例匹配", "Word报告导出"],
    )
    students, companies = load_students(), load_companies()
    if not students:
        st.warning("管理员尚未上传历史学生库。系统仍可评分，但相似学长匹配会受限。")
    if not companies:
        st.info("管理员尚未上传校企合作单位。系统仍可推荐路径，但不会显示合作单位匹配。")

    c1, c2 = st.columns([1.1, 0.9])
    with c1:
        card_start("录入学生信息", "支持非结构化自述、简历 PDF/DOCX/TXT，或用快速表单生成。")
        mode = st.radio("输入方式", ["填写学生自述", "上传简历", "快速表单"], horizontal=True)
        raw_text = ""
        if mode == "填写学生自述":
            raw_text = st.text_area("学生自述", height=210, placeholder="例如：该生绩点2.95，四级480，蓝桥杯省一，美团后端实习4个月，做Java、Redis、MySQL，也做过校园外卖系统……")
        elif mode == "上传简历":
            f = st.file_uploader("上传简历", type=["pdf", "docx", "txt", "md"])
            if f:
                raw_text = extract_text_from_file(f)
                st.text_area("解析出的文本", raw_text[:6000], height=210)
        else:
            a, b, c = st.columns(3)
            with a:
                major = st.text_input("专业", "软件工程")
                gpa = st.number_input("绩点", 0.0, 5.0, 3.20, 0.01)
            with b:
                cet4 = st.number_input("四级", 0, 710, 480)
                cet6 = st.number_input("六级", 0, 710, 0)
                target = st.selectbox("初步目标", ["不确定", "普通推免", "特殊专长", "工程专项/专硕", "实习就业", "考研", "考公", "支教/辅导员"])

            with c:
                volunteer = st.number_input("志愿时长", 0, 1000, 0)
                failed = st.selectbox("是否有挂科", ["无", "有"])
            comp = st.text_area("竞赛", placeholder="蓝桥杯省一；数学建模国二")
            paper = st.text_area("论文/科研", placeholder="CCF B一作录用；导师科研项目；大创负责人")
            internship = st.text_area("实习/项目/技术栈", placeholder="美团后端实习4个月；Java Redis MySQL Kafka；校园外卖系统")
            work = st.text_area("学生工作", placeholder="班长；学生会部长；志愿服务60小时")
            raw_text = f"专业{major}，绩点{gpa}，四级{cet4}，六级{cet6}，志愿时长{volunteer}小时，{'有挂科' if failed=='有' else '无挂科'}，目标{target}。竞赛：{comp}。论文科研：{paper}。实习项目技能：{internship}。学生工作：{work}。"
        use_extract_llm = st.toggle("使用大模型抽取简历/自述", value=True, help="未配置 API 时会自动回退到本地启发式抽取。")
        use_advice_llm = st.toggle("使用大模型生成最终建议", value=True, help="关闭后只使用本地规则解释，几乎不消耗 token。")
        use_web_jobs = st.toggle("联网检索匹配岗位/薪资", value=False, help="可选。需配置 TAVILY_API_KEY；不配置时自动使用本地岗位画像兜底。")
        st.session_state.use_web_jobs = use_web_jobs
        run = st.button("分析学生画像", use_container_width=True)
        card_end()

    with c2:
        card_start("路径适配度说明", "六维能力画像：不同路径采用差异化权重，避免用单一标准评价所有学生。")
        st.markdown("""
        <span class="badge">普通推免：学业基础 + 科研创新 + 竞赛实践</span>
        <span class="badge">特殊专长A/B：科研创新 + 竞赛实践</span>
        <span class="badge">工程专项/专硕：工程实践 + 成长规划</span>
        <span class="badge">支教/辅导员：组织服务 + 成长规划</span>
        <span class="badge">实习就业：工程实践优先（55%）</span>
        <span class="badge warning-badge">考研/考公：最低优先级兜底路径</span>
        """, unsafe_allow_html=True)
        st.markdown("---")
        client = SiliconFlowClient()
        mode_text = "大模型增强模式" if client.available else "本地规则模式（未配置 API Key）"
        mode_color = "#15803d" if client.available else "#92400e"
        st.markdown(f'<div style="font-size:13px;color:{mode_color};font-weight:600;">当前模式：{mode_text}</div>', unsafe_allow_html=True)
        st.caption("相同输入会命中 MD5 缓存，不重复调用 API。六维能力画像由底层评分合成，专业方向作为辅助参考。")
        card_end()

    if run:
        if not raw_text.strip():
            st.error("请先录入学生信息或上传简历。")
            return
        with st.spinner("正在抽取学生画像，请在下方核对/微调后再生成推荐……"):
            st.session_state.draft_profile = extract_student_profile(raw_text, use_llm=use_extract_llm)
        st.success('画像已抽取。请核对绩点、CET4、CET6、志愿时长等字段；修改后点击”使用微调后的画像生成推荐”。')

    if st.session_state.get("draft_profile"):
        st.markdown("---")
        st.markdown("## 画像核对")
        edited_profile = profile_editor(dict(st.session_state.draft_profile))
        if st.button("使用微调后的画像生成推荐", use_container_width=True):
            with st.spinner("正在基于调整后的信息重新计算路径适配度、匹配匿名案例和校企单位……"):
                edited_profile["scores"] = calculate_dimension_scores(edited_profile)
                edited_profile["tags"] = list(set(edited_profile.get("tags", []) + []))
                context = build_context(edited_profile, use_web_jobs=st.session_state.get("use_web_jobs", False))
                advice = generate_llm_advice(context, use_llm=use_advice_llm)
            st.session_state.last_result = {"profile": edited_profile, "context": context, "advice": advice}
            st.success("已使用微调后的信息完成重新评估。")

    result = st.session_state.get("last_result")
    if result:
        profile, context, advice = result["profile"], result["context"], result["advice"]
        scores = context["current_student"]["scores"]
        path_scores = context["path_scores"]
        ranked = sorted(path_scores.items(), key=lambda x: x[1], reverse=True)
        main_path = ranked[0][0]
        algo = context.get("algorithm_analysis") or {}

        st.markdown("---")
        st.markdown("## 成长路径评估结果")
        client_ok = SiliconFlowClient().available
        mode_label = "大模型增强模式" if client_ok else "本地规则模式"
        intent_detected = context.get("intent_analysis", {}).get("detected_intents") or []
        intent_str = "、".join(intent_detected) if intent_detected else "未识别到明确意向"
        m1, m2, m3, m4 = st.columns(4)
        with m1: metric_card("主推荐路径", main_path, f"路径适配度 {ranked[0][1]:.1f}/100")
        with m2: metric_card("最强能力维度", max([(DIMENSION_LABELS[d], scores.get(d,0)) for d in DIMENSIONS], key=lambda x: x[1])[0], "六维能力画像最高项")
        with m3: metric_card("目标意向", intent_str[:12] if len(intent_str) > 12 else intent_str, "系统识别结果")
        with m4: metric_card("当前模式", mode_label, f"相似案例 {len(context.get('similar_seniors') or [])} 条")

        left, right = st.columns([1, 1])
        with left:
            card_start("六维能力画像", "学业基础 · 科研创新 · 竞赛实践 · 工程实践 · 组织服务 · 成长规划")
            st.plotly_chart(radar_chart(scores), use_container_width=True)
            card_end()
        with right:
            card_start("各路径适配度", "9条成长路径综合评分（规则评分75% + 算法评分25% + 意向修正）")
            st.plotly_chart(path_bar_chart(path_scores), use_container_width=True)
            card_end()

        # ── Algorithm analysis card ──────────────────────────────────────
        if algo:
            card_start("推荐依据说明", "系统综合采用规则评分、多指标综合评价（TOPSIS）、历史案例相似度匹配和可解释性分析，辅助学生和辅导员进行成长规划参考。")
            strengths = algo.get("strengths") or []
            weaknesses = algo.get("weaknesses") or []
            reasons = algo.get("top_path_reasons") or []
            risks = algo.get("risk_factors") or []
            suggestions = algo.get("improvement_suggestions") or []

            # Intent analysis block
            intent = context.get("intent_analysis") or {}
            detected_intents = intent.get("detected_intents") or []
            intent_bonus = intent.get("applied_bonus") or {}
            intent_exp = intent.get("explanation") or ""
            if detected_intents or intent_exp:
                st.markdown("**目标意向识别**")
                if detected_intents:
                    st.markdown(
                        " ".join(f'<span class="badge">{i}</span>' for i in detected_intents),
                        unsafe_allow_html=True,
                    )
                if intent_bonus:
                    bonus_str = "；".join(f"{p} +{v:.0f}分" for p, v in intent_bonus.items())
                    st.caption(f"意向修正（最多 8 分）：{bonus_str}")
                if intent_exp:
                    st.caption(intent_exp)
                st.markdown("---")

            col_a, col_b = st.columns(2)
            with col_a:
                if strengths:
                    st.markdown("**优势维度**")
                    st.markdown(" ".join(f'<span class="badge success-badge">{s}</span>' for s in strengths), unsafe_allow_html=True)
                if reasons:
                    st.markdown("**主推荐路径依据**")
                    for r in reasons:
                        st.markdown(f"- {r}")
            with col_b:
                if weaknesses:
                    st.markdown("**短板维度**")
                    st.markdown(" ".join(f'<span class="badge warning-badge">{w}</span>' for w in weaknesses), unsafe_allow_html=True)
                if risks:
                    st.markdown("**风险提示**")
                    for r in risks:
                        st.markdown(f"- {r}")

            if suggestions:
                st.markdown("**提升建议**")
                for i, s in enumerate(suggestions, 1):
                    st.markdown(f"{i}. {s}")

            methods = algo.get("method_used") or []
            if methods:
                st.caption("评估方法：" + " · ".join(methods))
            card_end()

        card_start("综合成长建议", "基于六维能力画像、路径评分、相似案例和政策规则生成，仅供参考。辅导员可据此制定个性化帮扶方案。")
        st.markdown(advice)
        card_end()
        card_start("相关申请表下载", "当主推荐路径涉及辅导员计划或特殊专长B/本硕博时，系统会提供对应表格供参考。")
        download_path_forms(main_path)
        card_end()

        card_start("相似学长学姐案例", "仅隐藏姓名、学号和联系方式；保留成长路径、去向和匹配原因，供辅导员参考。")
        render_senior_cards(context.get("similar_seniors") or [])
        card_end()

        card_start("就业/实习/升学岗位推荐", "优先展示校企合作单位；可选联网检索其他单位的匹配岗位、核心职能和薪资待遇。")
        render_job_cards(context.get("recommended_companies") or [])
        card_end()

        # ── Report export card ───────────────────────────────────────
        st.markdown("""
        <div class="export-card">
          <div class="export-title">报告导出</div>
          <div class="export-desc">将本次成长路径评估结果导出为结构化数据或正式 Word 报告，可存档、可打印、可用于帮扶记录。</div>
        </div>
        """, unsafe_allow_html=True)
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "下载 JSON 结构化报告",
                data=json.dumps(result, ensure_ascii=False, indent=2),
                file_name="student_growth_report.json",
                mime="application/json",
                use_container_width=True,
            )
        with dl2:
            try:
                word_buf = build_word_report(result)
                st.download_button(
                    "下载 Word 正式评估报告",
                    data=word_buf,
                    file_name=report_filename(),
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                )
            except Exception as e:
                st.warning(f"Word 报告生成失败：{e}")


def _render_structured_student_detail(student: dict):
    """Render a full structured student detail view in Streamlit."""
    semesters = ["大一上", "大一下", "大二上", "大二下", "大三上", "大三下", "大四上"]

    st.markdown(f"**姓名：** {student.get('name')}　**班级：** {student.get('class_name')}　**学号：** {student.get('student_no')}")
    st.markdown(f"**去向：** {student.get('destination') or '暂无'}　**去向单位：** {student.get('destination_unit') or '暂无'}　**特长：** {student.get('specialty') or '暂无'}")

    # GPA trend
    gpa_map = student.get("gpa_by_semester") or {}
    gpa_vals = [gpa_map.get(s) for s in semesters]
    gpa_display = {s: (f"{v:.2f}" if v is not None else "—") for s, v in zip(semesters, gpa_vals)}
    st.markdown("**各学期平均学分绩点：**")
    gpa_df = pd.DataFrame([gpa_display])
    safe_dataframe(gpa_df, use_container_width=True)

    # Positions
    pos_map = student.get("positions_by_semester") or {}
    pos_data = [{"学期": s, "担任职务": pos_map.get(s) or "—"} for s in semesters]
    with st.expander("担任职务（各学期）"):
        safe_dataframe(pd.DataFrame(pos_data), use_container_width=True)

    # Awards
    awd_map = student.get("awards_by_semester") or {}
    awd_data = [{"学期": s, "所获奖项": awd_map.get(s) or "—"} for s in semesters]
    with st.expander("所获奖项（各学期）"):
        safe_dataframe(pd.DataFrame(awd_data), use_container_width=True)

    # Evaluations
    evl_map = student.get("evaluations_by_semester") or {}
    evl_data = [{"学期": s, "学期评价": evl_map.get(s) or "—"} for s in semesters]
    with st.expander("学期评价（各学期）"):
        safe_dataframe(pd.DataFrame(evl_data), use_container_width=True)

    # 6-dim scores radar
    scores = student.get("scores") or {}
    if any(scores.get(d) for d in ["academic_foundation", "research_innovation", "competition_practice",
                                    "engineering_practice", "organization_service", "growth_planning"]):
        dim_vals = [scores.get(d, 0) for d in ["academic_foundation", "research_innovation",
                                                 "competition_practice", "engineering_practice",
                                                 "organization_service", "growth_planning"]]
        dim_labels = ["学业基础", "科研创新", "竞赛实践", "工程实践", "组织服务", "成长规划"]
        fig = go.Figure(go.Scatterpolar(
            r=dim_vals + [dim_vals[0]],
            theta=dim_labels + [dim_labels[0]],
            fill="toself",
            line_color="#1d4ed8",
            fillcolor="rgba(29,78,216,0.15)",
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False,
            height=320,
            margin=dict(l=40, r=40, t=30, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

    # Word report download
    try:
        from student_growth_system.report_exporter import build_word_report, report_filename
        buf = build_word_report(student)
        st.download_button(
            "下载 Word 评估报告",
            data=buf,
            file_name=report_filename(),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    except Exception as e:
        st.warning(f"Word 报告生成失败：{e}")


def page_admin_import():
    hero("管理员｜数据导入", "上传历史学生信息、校企合作单位和政策文件。系统可用大模型首次提取摘要，后续推荐直接读取结构化数据，降低 token 成本。")
    if not admin_login():
        return
    t1, t2, t3, t4 = st.tabs(["历史学生库", "校企合作单位", "政策/规则库", "文件来源管理"])

    with t1:
        card_start("上传历史学生 Excel", "支持两行表头格式：基础信息 + 平均学分绩点/担任职务/所获奖项/学期评价（各7个学期）。")
        f = st.file_uploader("学生信息 Excel", type=["xlsx", "xls"], key="student_xlsx")
        if f and st.button("导入学生库", use_container_width=True):
            try:
                source_id = new_source_id("students")
                saved_path = save_uploaded_file(f, "students", source_id)
                f.seek(0)
                students = load_students_excel(f, source_id=source_id, source_name=f.name)
                all_students = [s for s in load_students() if s.get("source_id") != source_id] + students
                save_students(all_students)
                add_import_record({
                    "source_id": source_id,
                    "kind": "students",
                    "file_name": f.name,
                    "saved_path": saved_path,
                    "derived_count": len(students),
                    "extract_method": "python_rules",
                })
                st.success(f"已导入 {len(students)} 条学生画像。")
                # Show flat summary table (not raw nested dicts)
                preview_rows = []
                for s in students:
                    gpa_vals = [v for v in s.get("gpa_by_semester", {}).values() if v is not None]
                    preview_rows.append({
                        "姓名": s.get("name"),
                        "班级": s.get("class_name"),
                        "学号": s.get("student_no"),
                        "GPA均值": round(sum(gpa_vals)/len(gpa_vals), 2) if gpa_vals else None,
                        "去向": s.get("destination"),
                        "去向单位": s.get("destination_unit"),
                    })
                safe_dataframe(pd.DataFrame(preview_rows), use_container_width=True)
            except Exception as e:
                st.error(f"导入失败：{e}")
        existing = load_students()
        if existing:
            st.markdown("#### 当前学生库预览")
            preview_rows = []
            for s in existing[:20]:
                if "gpa_by_semester" in s:
                    gpa_vals = [v for v in s.get("gpa_by_semester", {}).values() if v is not None]
                    preview_rows.append({
                        "姓名": s.get("name"), "班级": s.get("class_name"),
                        "学号": s.get("student_no"),
                        "GPA均值": round(sum(gpa_vals)/len(gpa_vals), 2) if gpa_vals else None,
                        "去向": s.get("destination"), "去向单位": s.get("destination_unit"),
                    })
                else:
                    preview_rows.append({
                        "姓名": s.get("name"), "班级": s.get("grade", ""),
                        "学号": s.get("student_id", ""), "GPA均值": s.get("gpa"),
                        "去向": s.get("destination", ""), "去向单位": "",
                    })
            safe_dataframe(pd.DataFrame(preview_rows), use_container_width=True)
        card_end()

    with t2:
        card_start("上传校企合作单位 Excel", "可选择 Python 规则抽取或大模型精准抽取。大模型抽取更适合字段混乱、备注较多的企业表。")
        f = st.file_uploader("校企合作单位 Excel", type=["xlsx", "xls"], key="company_xlsx")
        use_company_llm = st.toggle("使用大模型提取企业画像", value=True, help="首次导入会消耗 token，但结果会存入 companies.json，后续推荐不再重复读取原表。")
        if f and st.button("导入合作单位", use_container_width=True):
            try:
                source_id = new_source_id("companies")
                saved_path = save_uploaded_file(f, "companies", source_id)
                f.seek(0)
                if use_company_llm and SiliconFlowClient().available:
                    excel_text = excel_to_text(f)
                    companies = extract_companies_with_llm(excel_text, source_id=source_id, source_name=f.name)
                    method = "llm"
                else:
                    f.seek(0)
                    companies = load_companies_excel(f, source_id=source_id, source_name=f.name)
                    method = "python_rules"
                all_companies = [c for c in load_companies() if c.get("source_id") != source_id] + companies
                save_companies(all_companies)
                add_import_record({
                    "source_id": source_id,
                    "kind": "companies",
                    "file_name": f.name,
                    "saved_path": saved_path,
                    "derived_count": len(companies),
                    "extract_method": method,
                })
                st.success(f"已导入 {len(companies)} 个合作单位，提取方式：{method}。")
                safe_dataframe(pd.DataFrame(companies), use_container_width=True)
            except Exception as e:
                st.error(f"导入失败：{e}")
        existing = load_companies()
        if existing:
            st.markdown("#### 当前合作单位预览")
            safe_dataframe(pd.DataFrame(existing).head(20), use_container_width=True)
        card_end()

    with t3:
        card_start("政策摘要与规则维护", "可上传政策文件并用大模型提取压缩摘要。摘要保存后，推荐阶段只传摘要，不传全文。")
        policy = load_policy()
        new_policy = {}
        for k, default in DEFAULT_POLICY_SUMMARY.items():
            new_policy[k] = st.text_area(k, value=policy.get(k, default), height=90)
        st.markdown("##### 上传政策文件并提取摘要")
        pf = st.file_uploader("政策文件 PDF/DOCX/TXT", type=["pdf", "docx", "txt", "md"], accept_multiple_files=True, key="policy_files")
        use_policy_llm = st.toggle("使用大模型提取政策摘要", value=True, help="适合把长政策文件压缩成固定 JSON 摘要。")
        if pf:
            texts = []
            for f in pf:
                texts.append(f"【{f.name}】\n" + extract_text_from_file(f)[:12000])
            policy_text = "\n\n".join(texts)
            st.text_area("政策原文预览", policy_text[:12000], height=240)
            if st.button("从政策文件提取并保存摘要", use_container_width=True):
                try:
                    if use_policy_llm and SiliconFlowClient().available:
                        extracted_policy = extract_policy_summary_with_llm(policy_text, existing=new_policy)
                    else:
                        extracted_policy = new_policy
                    save_policy(extracted_policy)
                    for f in pf:
                        source_id = new_source_id("policy")
                        f.seek(0)
                        saved_path = save_uploaded_file(f, "policy", source_id)
                        add_import_record({
                            "source_id": source_id,
                            "kind": "policy",
                            "file_name": f.name,
                            "saved_path": saved_path,
                            "derived_count": len(extracted_policy),
                            "extract_method": "llm" if use_policy_llm else "manual_preview",
                        })
                    st.success("政策摘要已提取并保存。")
                    st.json(extracted_policy)
                except Exception as e:
                    st.error(f"政策提取失败：{e}")
        if st.button("仅保存当前手工编辑摘要", use_container_width=True):
            save_policy(new_policy)
            st.success("政策摘要已保存。")
        card_end()

    with t4:
        card_start("文件来源管理", "移除某个上传文件时，会同步移除该文件派生出的学生画像、企业画像或政策摘要，并清空推荐缓存。")
        records = load_imported_files()
        if not records:
            st.info("暂无上传文件记录。")
        else:
            safe_dataframe(pd.DataFrame(records), use_container_width=True)
            options = {f"{r.get('kind')}｜{r.get('file_name')}｜{r.get('source_id')}": r.get("source_id") for r in records}
            selected = st.selectbox("选择要移除的文件来源", list(options.keys()))
            if st.button("移除该文件及其提取结果", use_container_width=True):
                result = remove_import_source(options[selected])
                if result.get("removed"):
                    st.success(result.get("message"))
                    st.rerun()
                else:
                    st.error(result.get("message"))
        card_end()

def page_policy():
    hero("管理员｜规则配置", "查看各路径的评价逻辑说明和 token 成本控制策略。")
    if not admin_login():
        return
    card_start("当前路径规则", "规则核心计算在 scoring.py 中，六维能力画像由底层评分合成；可在这里维护给大模型使用的简明政策摘要。")
    policy = load_policy()
    for k, v in policy.items():
        st.markdown(f"**{k}**")
        st.info(v)
    card_end()
    card_start("成本优化策略")
    st.markdown("""
    - Excel 表格读取、绩点计算、路径打分、相似度匹配全部由 Python 完成，不消耗大模型 token。
    - 政策文件只在首次导入时压缩成规则摘要，后续推荐只传摘要。
    - 历史学生先量化成六维能力画像，后续只传 Top 5 相似学长摘要。
    - 校企合作单位先标签化，后续只传 Top 5 匹配单位。
    - 同一简历/自述会用 MD5 缓存抽取结果和建议，重复点击不重复调用 API。
    - 专业方向（major_score）作为路径推荐辅助特征，不在雷达图中单独展示。
    """)
    card_end()


def page_dashboard():
    hero("数据看板", "查看历史学生库、校企合作单位和系统运行状态。")
    if not admin_login():
        return
    students = load_students()
    companies = load_companies()
    m1, m2, m3, m4 = st.columns(4)
    with m1: metric_card("历史学生", str(len(students)), "用于相似学长匹配")
    with m2: metric_card("合作单位", str(len(companies)), "优先推荐实习单位")
    with m3: metric_card("缓存记录", str(len(load_cache())), "减少重复 API 调用")
    with m4: metric_card("大模型状态", "已配置" if SiliconFlowClient().available else "未配置", "硅基流动 API")
    if students:
        card_start("学生库分布")
        # Build a flat summary table that works for both old and new structured formats
        rows = []
        for s in students:
            if "gpa_by_semester" in s:
                # New structured format
                gpa_vals = [v for v in s.get("gpa_by_semester", {}).values() if v is not None]
                gpa_avg = round(sum(gpa_vals) / len(gpa_vals), 2) if gpa_vals else None
                scores = s.get("scores") or {}
                rows.append({
                    "姓名": s.get("name", ""),
                    "班级": s.get("class_name", ""),
                    "学号": s.get("student_no", ""),
                    "GPA均值": gpa_avg,
                    "去向": s.get("destination", ""),
                    "去向单位": s.get("destination_unit", ""),
                    "路径类型": (s.get("profile") or {}).get("path_type", ""),
                    "学业基础": scores.get("academic_foundation"),
                    "科研创新": scores.get("research_innovation"),
                    "竞赛实践": scores.get("competition_practice"),
                    "工程实践": scores.get("engineering_practice"),
                    "组织服务": scores.get("organization_service"),
                    "成长规划": scores.get("growth_planning"),
                })
            else:
                # Old flat format
                scores = s.get("scores") or {}
                rows.append({
                    "姓名": s.get("name", ""),
                    "班级": s.get("grade", ""),
                    "学号": s.get("student_id", ""),
                    "GPA均值": s.get("gpa"),
                    "去向": s.get("destination", ""),
                    "去向单位": "",
                    "路径类型": s.get("path_type", ""),
                    "学业基础": scores.get("academic_foundation"),
                    "科研创新": scores.get("research_innovation"),
                    "竞赛实践": scores.get("competition_practice"),
                    "工程实践": scores.get("engineering_practice"),
                    "组织服务": scores.get("organization_service"),
                    "成长规划": scores.get("growth_planning"),
                })
        df = pd.DataFrame(rows)
        # Path distribution pie chart
        if "路径类型" in df.columns:
            counts = df["路径类型"].replace("", "未标注").value_counts().reset_index()
            counts.columns = ["路径", "人数"]
            st.plotly_chart(px.pie(counts, names="路径", values="人数", hole=0.45), use_container_width=True)
        safe_dataframe(df.head(50), use_container_width=True)

        # Detailed student view
        st.markdown("#### 学生详情查看")
        names = [s.get("name", f"学生{i+1}") for i, s in enumerate(students)]
        sel_name = st.selectbox("选择学生", names, key="dashboard_student_sel")
        sel_student = next((s for s in students if s.get("name") == sel_name), None)
        if sel_student and "gpa_by_semester" in sel_student:
            _render_structured_student_detail(sel_student)
        card_end()
    if companies:
        card_start("合作单位库")
        safe_dataframe(pd.DataFrame(companies).head(50), use_container_width=True)
        card_end()


def page_settings():
    hero("系统设置", "API 配置、缓存管理和数据清理。")
    if not admin_login():
        return
    card_start("API 配置")
    st.code("SILICONFLOW_API_KEY=你的key\nSF_MODEL_NAME=deepseek-ai/DeepSeek-V3.1\nADMIN_PASSWORD=你的管理员密码", language="bash")
    st.caption("建议在 .env 文件或服务器环境变量中配置，不要把真实 Key 写入代码仓库。")
    client = SiliconFlowClient()
    st.write("当前模型：", client.model)
    st.write("API 状态：", "已配置" if client.available else "未配置")
    card_end()

    card_start("缓存管理")
    if st.button("清空查询缓存", use_container_width=True):
        save_cache({})
        st.success("已清空缓存。")
    st.caption("清空缓存后，相同输入将重新调用 API 生成结果。")
    card_end()

    st.markdown("""
    <div class="danger-zone">
      <div class="danger-zone-title">⚠️ 危险操作区域</div>
      <div class="danger-zone-desc">以下操作不可撤销，将永久删除所有学生库、企业库、政策库和缓存数据。请确认后再操作。</div>
    </div>
    """, unsafe_allow_html=True)
    if st.button("清空全部数据（不可撤销）", use_container_width=True):
        clear_all_data()
        st.success("已清空学生库、企业库、政策库和缓存。")


def page_chat():
    hero(
        "智能问答｜AI辅导员",
        "围绕学生保研、考研、就业等路径，辅助辅导员进行分析与帮扶指导。",
        badges=["多轮对话", "画像上下文注入", "本地规则兜底"],
    )

    last_result = st.session_state.get("last_result")
    context = last_result.get("context") if last_result else None
    client = SiliconFlowClient()

    # ── AI 助手头部 ───────────────────────────────────────────────
    st.markdown("""
    <div class="assistant-header">
      <div class="assistant-avatar">🤖</div>
      <div class="assistant-meta">
        <div class="assistant-name">AI 辅导员助手</div>
        <div class="assistant-status"><span class="status-dot-online"></span>在线 · 随时为您答疑</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 画像状态卡片 ──────────────────────────────────────────────
    if context:
        path_scores = context.get("path_scores") or {}
        main_path = context.get("main_path") or (
            max(path_scores.items(), key=lambda x: x[1])[0] if path_scores else "暂无"
        )
        scores = (context.get("current_student") or {}).get("scores") or {}
        best_dim = max([(DIMENSION_LABELS[d], scores.get(d, 0)) for d in DIMENSIONS], key=lambda x: x[1])[0] if scores else "暂无"
        intents = context.get("intent_analysis", {}).get("detected_intents") or []
        intent_str = "、".join(intents) if intents else "未识别到明确意向"
        mode_str = "大模型增强模式" if client.available else "本地规则模式"
        st.markdown(f"""
        <div class="status-card">
          <div style="font-size:13px;font-weight:700;color:#1e3a8a;margin-bottom:8px;">当前已加载学生画像</div>
          <div class="status-row"><span class="status-dot status-dot-green"></span>主推荐路径：<b>{html_escape(main_path)}</b></div>
          <div class="status-row"><span class="status-dot"></span>最强能力维度：<b>{html_escape(best_dim)}</b></div>
          <div class="status-row"><span class="status-dot"></span>目标意向识别：<b>{html_escape(intent_str)}</b></div>
          <div class="status-row"><span class="status-dot {'status-dot-green' if client.available else 'status-dot-gray'}"></span>回答模式：<b>{mode_str}</b></div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="status-card-empty">
          尚未加载学生画像。请先在 <b>用户端｜路径评估</b> 页面完成画像抽取，AI辅导员可以结合该生的六维能力画像给出更有针对性的建议。<br>
          也可以直接在下方提问通用问题。
        </div>
        """, unsafe_allow_html=True)

    # ── 常见问题快捷按钮 ──────────────────────────────────────────
    QUICK_QUESTIONS = [
        "该生适合保研还是考研？",
        "该生应补科研还是补实习？",
        "该生适合投什么岗位？",
        "如何帮助该生规划三个月？",
        "该生情况该如何谈心谈话？",
        "绩点一般竞赛强如何规划？",
    ]
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    if not st.session_state.chat_messages:
        st.markdown('<div class="quick-title">💡 常见问题快捷提问</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        for i, q in enumerate(QUICK_QUESTIONS):
            with cols[i % 3]:
                if st.button(q, key=f"quick_{i}", use_container_width=True):
                    st.session_state.chat_messages.append({"role": "user", "content": q})
                    with st.spinner("AI 辅导员思考中……"):
                        reply = answer_student_question(q, [], context=context)
                    st.session_state.chat_messages.append({"role": "assistant", "content": reply})
                    st.rerun()

    # ── 清空按钮 ──────────────────────────────────────────────────
    if st.session_state.chat_messages:
        col_clear, _ = st.columns([1, 6])
        with col_clear:
            if st.button("清空对话", use_container_width=True):
                st.session_state.chat_messages = []
                st.rerun()

    # ── 历史消息 ──────────────────────────────────────────────────
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # ── 输入框 ────────────────────────────────────────────────────
    user_input = st.chat_input("向 AI 辅导员提问，例如：该生适合考研吗？如何帮助该生准备保研夏令营？")
    if user_input:
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        with st.chat_message("assistant"):
            with st.spinner("AI 辅导员思考中……"):
                reply = answer_student_question(
                    question=user_input,
                    history=st.session_state.chat_messages[:-1],
                    context=context,
                )
            st.markdown(reply)
        st.session_state.chat_messages.append({"role": "assistant", "content": reply})


def main():
    page = sidebar_nav()
    if page.startswith("用户端"):
        page_student()
    elif page.startswith("智能问答"):
        page_chat()
    elif page.startswith("管理员｜数据导入"):
        page_admin_import()
    elif page.startswith("管理员｜规则配置"):
        page_policy()
    elif page.startswith("数据看板"):
        page_dashboard()
    else:
        page_settings()


if __name__ == "__main__":
    main()
