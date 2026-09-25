import io
import re
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(
    page_title="Retail BI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- STYLE ----------
st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1600px;}
[data-testid="stMetric"] {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,.28);
    padding: 14px 16px;
    border-radius: 14px;
    box-shadow: 0 4px 14px rgba(0,0,0,.08);
}
[data-testid="stMetricLabel"],
[data-testid="stMetricValue"],
[data-testid="stMetricDelta"] {
    color: var(--text-color) !important;
}
[data-testid="stSidebar"] {
    background: var(--secondary-background-color);
    color: var(--text-color);
}
div[data-baseweb="tab-list"] {gap: 8px;}
div[data-baseweb="tab"] {
    border-radius: 10px 10px 0 0;
    padding-left: 14px;
    padding-right: 14px;
}
.small-note {color:#64748b;font-size:.88rem;}
.section-title {font-size:1.20rem;font-weight:700;margin:.4rem 0 .7rem;}
</style>
""", unsafe_allow_html=True)

# ---------- HELPERS ----------
def canon(s):
    s = str(s).strip().lower()
    s = s.replace("ё", "е")
    s = re.sub(r"\s+", " ", s)
    return s

ALIASES = {
    "employee": [
        "сотрудник", "фио", "сотрудник фио", "продавец", "кто продал"
    ],
    "store": [
        "салон", "магазин", "тт", "код тт", "код салона", "магазин/салон"
    ],
    "city": ["город"],
    "category": ["категория", "категория abcd", "abc", "abcd"],
    "position": ["должность"],
    "date": ["дата", "дата среза", "дата отчета", "дата смены"],
    "hours": ["часов", "часы"],
    "shifts": ["смены"],
    "outputs": ["выходы", "выход", "кол-во выходов", "количество выходов"],

    "revenue_plan": [
        "выручка план", "план выручки", "выручка рс план", "план рс",
        "план салона", "выручка салона план", "выручка салона, план"
    ],
    "revenue_fact": [
        "выручка факт", "факт выручки", "выручка рс факт", "факт рс",
        "факт салона", "выручка салона факт", "выручка салона, факт"
    ],
    "revenue_forecast": [
        "выручка прогноз", "прогноз выручки", "прогноз"
    ],

    "employee_plan": [
        "выручка ок план", "выручка ок, план", "план ок",
        "план сотрудника", "личный план", "выручка сотрудника план"
    ],
    "employee_fact": [
        "выручка ок факт", "выручка ок, факт", "факт ок",
        "факт сотрудника", "личный факт", "выручка сотрудника факт"
    ],

    "mz_plan": ["мз план", "мз выручка план", "выручка мз план"],
    "mz_fact": ["мз факт", "мз выручка факт", "выручка мз факт"],
    "mz_forecast": ["мз прогноз", "мз выручка прогноз", "выручка мз прогноз"],
    "mz_qty": ["мз шт", "мз шт.", "мз количество", "мз, шт"],
    "mz_avg": ["мз ср чек", "ср чек мз", "средний чек мз"],

    "mo_plan": ["мо план", "мо выручка план"],
    "mo_fact": ["мо факт", "мо выручка факт"],
    "mo_forecast": ["мо прогноз", "мо выручка прогноз"],
    "mo_avg": ["мо ср чек", "ср чек мо", "средний чек мо"],

    "ol_plan": ["ол план", "lo план", "ол выручка план", "lo выручка план"],
    "ol_fact": ["ол факт", "lo факт", "ол выручка факт", "lo выручка факт"],
    "ol_forecast": ["ол прогноз", "lo прогноз", "ол выручка прогноз", "lo выручка прогноз"],
    "ol_avg": ["ол ср чек", "lo ср чек", "ср чек ол", "ср чек lo"],

    "sz_plan": ["сз план", "сз выручка план"],
    "sz_fact": ["сз факт", "сз выручка факт"],
    "sz_forecast": ["сз прогноз", "сз выручка прогноз"],
    "sz_qty": ["сз шт", "сз шт.", "сз количество"],
    "sz_avg": ["сз ср чек", "ср чек сз"],

    "mkl_plan": ["мкл план", "мкл выручка план"],
    "mkl_fact": ["мкл факт", "мкл выручка факт"],
    "mkl_forecast": ["мкл прогноз", "мкл выручка прогноз"],
    "mkl_qty": ["мкл шт", "мкл шт.", "мкл количество"],
    "mkl_avg": ["мкл ср чек", "ср чек мкл"],

    "traffic": ["трафик", "посетители"],
    "checks": ["чеки", "количество чеков", "чеков"],
    "conversion": ["конверсия", "конверсия %", "% конверсии"],
    "status": ["статус", "закрыт/открыт", "статус салона"],
    "correction": ["корректировки", "корректировка"],
}

def find_col(df, key):
    normalized = {canon(c): c for c in df.columns}
    for a in ALIASES.get(key, []):
        if canon(a) in normalized:
            return normalized[canon(a)]
    # fuzzy contains fallback for important fields
    for c in df.columns:
        cc = canon(c)
        for a in ALIASES.get(key, []):
            aa = canon(a)
            if len(aa) >= 5 and (aa in cc or cc in aa):
                return c
    return None

def to_num(s):
    if s is None:
        return pd.Series(dtype=float)
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    x = s.astype(str).str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    x = x.str.replace("%", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(x, errors="coerce")

def fmt_money(v):
    if pd.isna(v): return "—"
    return f"{v:,.0f} ₽".replace(",", " ")

def fmt_pct(v):
    if pd.isna(v): return "—"
    return f"{v:.1%}".replace(".", ",")

def fmt_num(v, digits=0):
    if pd.isna(v): return "—"
    return f"{v:,.{digits}f}".replace(",", " ").replace(".", ",")

def read_workbook(uploaded):
    name = uploaded.name
    raw = uploaded.getvalue()
    ext = name.lower().split(".")[-1]
    out = {}
    if ext == "csv":
        for sep in [";", ",", "\t"]:
            try:
                df = pd.read_csv(io.BytesIO(raw), sep=sep)
                if len(df.columns) > 1:
                    out["CSV"] = df
                    return out
            except Exception:
                pass
        raise ValueError(f"Не удалось прочитать CSV: {name}")
    xls = pd.ExcelFile(io.BytesIO(raw))
    for sh in xls.sheet_names:
        try:
            df = pd.read_excel(xls, sheet_name=sh)
            if df is not None and (len(df.columns) > 0):
                out[sh] = df
        except Exception:
            pass
    if not out:
        raise ValueError(f"Не удалось прочитать листы: {name}")
    return out

def classify(df):
    keys = {k: find_col(df, k) for k in ALIASES}
    has = lambda *ks: all(keys.get(k) for k in ks)

    if has("employee", "store") and (keys.get("employee_fact") or keys.get("employee_plan")):
        return "employees"
    if has("employee", "store") and (keys.get("date") or keys.get("hours") or keys.get("shifts")):
        return "shifts"
    if keys.get("store") and (keys.get("revenue_fact") or keys.get("revenue_plan")):
        return "sales"
    return "other"

def standardize_sales(df, source):
    out = pd.DataFrame(index=df.index)
    for key in [
        "store","city","category","date","status",
        "revenue_plan","revenue_fact","revenue_forecast",
        "mz_plan","mz_fact","mz_forecast","mz_qty","mz_avg",
        "mo_plan","mo_fact","mo_forecast","mo_avg",
        "ol_plan","ol_fact","ol_forecast","ol_avg",
        "sz_plan","sz_fact","sz_forecast","sz_qty","sz_avg",
        "mkl_plan","mkl_fact","mkl_forecast","mkl_qty","mkl_avg",
        "traffic","checks","conversion"
    ]:
        c = find_col(df, key)
        if c:
            out[key] = df[c]
    out["source"] = source

    for c in out.columns:
        if c in ["store","city","category","status","source"]:
            out[c] = out[c].fillna("").astype(str).str.strip()
        elif c == "date":
            out[c] = pd.to_datetime(out[c], errors="coerce")
        else:
            out[c] = to_num(out[c])

    if "store" in out:
        out = out[out["store"].astype(str).str.strip().ne("")]
    # MZ = OL + MO if source has no MZ fact/plan
    if "mz_fact" not in out and "ol_fact" in out and "mo_fact" in out:
        out["mz_fact"] = out["ol_fact"].fillna(0) + out["mo_fact"].fillna(0)
    if "mz_plan" not in out and "ol_plan" in out and "mo_plan" in out:
        out["mz_plan"] = out["ol_plan"].fillna(0) + out["mo_plan"].fillna(0)
    if "mz_forecast" not in out and "ol_forecast" in out and "mo_forecast" in out:
        out["mz_forecast"] = out["ol_forecast"].fillna(0) + out["mo_forecast"].fillna(0)

    if "revenue_plan" in out and "revenue_fact" in out:
        out["revenue_perf"] = np.where(out["revenue_plan"] > 0, out["revenue_fact"]/out["revenue_plan"], np.nan)
        out["revenue_gap"] = out["revenue_fact"] - out["revenue_plan"]
    if "revenue_plan" in out and "revenue_forecast" in out:
        out["forecast_perf"] = np.where(out["revenue_plan"] > 0, out["revenue_forecast"]/out["revenue_plan"], np.nan)
    if "mz_plan" in out and "mz_fact" in out:
        out["mz_perf"] = np.where(out["mz_plan"] > 0, out["mz_fact"]/out["mz_plan"], np.nan)

    if "conversion" not in out and "traffic" in out and "checks" in out:
        out["conversion"] = np.where(out["traffic"] > 0, out["checks"]/out["traffic"], np.nan)
    else:
        if "conversion" in out:
            # if values look like 80 instead of 0.8
            med = out["conversion"].dropna().median() if out["conversion"].notna().any() else np.nan
            if pd.notna(med) and med > 1.5:
                out["conversion"] = out["conversion"]/100
    return out

def standardize_employees(df, source):
    out = pd.DataFrame(index=df.index)
    for key in [
        "employee","store","category","position","date","shifts","outputs",
        "employee_plan","employee_fact","revenue_plan","revenue_fact",
        "mz_qty","mz_avg","sz_qty","mo_avg"
    ]:
        c = find_col(df, key)
        if c:
            out[key] = df[c]
    out["source"] = source

    for c in out.columns:
        if c in ["employee","store","category","position","source"]:
            out[c] = out[c].fillna("").astype(str).str.strip()
        elif c == "date":
            out[c] = pd.to_datetime(out[c], errors="coerce")
        else:
            out[c] = to_num(out[c])

    if "employee" in out and "store" in out:
        out = out[out["employee"].ne("") & out["store"].ne("")]
    if "employee_plan" in out and "employee_fact" in out:
        out["employee_perf"] = np.where(out["employee_plan"] > 0, out["employee_fact"]/out["employee_plan"], np.nan)
        out["employee_gap"] = out["employee_fact"] - out["employee_plan"]
    if "outputs" in out and "employee_fact" in out:
        out["sales_per_output"] = np.where(out["outputs"] > 0, out["employee_fact"]/out["outputs"], np.nan)
    return out

def standardize_shifts(df, source):
    out = pd.DataFrame(index=df.index)
    for key in ["employee","store","date","hours","shifts","correction","status"]:
        c = find_col(df, key)
        if c:
            out[key] = df[c]
    out["source"] = source
    for c in out.columns:
        if c in ["employee","store","correction","status","source"]:
            out[c] = out[c].fillna("").astype(str).str.strip()
        elif c == "date":
            out[c] = pd.to_datetime(out[c], errors="coerce")
        else:
            out[c] = to_num(out[c])
    if "employee" in out:
        out = out[out["employee"].ne("")]
    return out

def unique_join(s):
    vals = [str(x).strip() for x in s if str(x).strip() and str(x).strip().lower() != "nan"]
    return ", ".join(dict.fromkeys(vals))

# ---------- LOAD FILES ----------
st.title("📊 Retail BI")
st.caption("Одно приложение для продаж, сотрудников, рейтинга, антитопа, план/факт/прогноз и графиков смен")

with st.sidebar:
    st.header("Загрузка данных")
    files = st.file_uploader(
        "Загрузите один или несколько файлов",
        type=["xlsx","xls","xlsm","csv"],
        accept_multiple_files=True,
        help="Можно одновременно загрузить отчёт по продажам, сотрудников и графики смен."
    )
    st.caption("Файлы обрабатываются внутри приложения. Данные не хранятся в GitHub.")
    st.divider()
    st.markdown("**Красная зона:** выполнение ниже 80%")

all_raw = []
errors = []
if files:
    for up in files:
        try:
            wb = read_workbook(up)
            for sh, df in wb.items():
                if df is None or df.empty:
                    continue
                source = f"{up.name} · {sh}"
                all_raw.append((source, df, classify(df)))
        except Exception as e:
            errors.append(f"{up.name}: {e}")

if errors:
    for e in errors:
        st.warning(e)

sales_parts = []
emp_parts = []
shift_parts = []
other_parts = []

for source, df, kind in all_raw:
    try:
        if kind == "sales":
            sales_parts.append(standardize_sales(df, source))
        elif kind == "employees":
            emp_parts.append(standardize_employees(df, source))
        elif kind == "shifts":
            shift_parts.append(standardize_shifts(df, source))
        else:
            other_parts.append((source, df))
    except Exception:
        other_parts.append((source, df))

sales = pd.concat(sales_parts, ignore_index=True, sort=False) if sales_parts else pd.DataFrame()
employees = pd.concat(emp_parts, ignore_index=True, sort=False) if emp_parts else pd.DataFrame()
shifts = pd.concat(shift_parts, ignore_index=True, sort=False) if shift_parts else pd.DataFrame()

# ---------- GLOBAL FILTERS ----------
with st.sidebar:
    st.header("Фильтры")
    all_stores = sorted(set(
        list(sales["store"].dropna().astype(str).unique()) if "store" in sales else []
    ) | set(
        list(employees["store"].dropna().astype(str).unique()) if "store" in employees else []
    ) | set(
        list(shifts["store"].dropna().astype(str).unique()) if "store" in shifts else []
    ))
    sel_stores = st.multiselect("Салоны", all_stores)

    all_cats = sorted(set(
        list(sales["category"].dropna().astype(str).unique()) if "category" in sales else []
    ) | set(
        list(employees["category"].dropna().astype(str).unique()) if "category" in employees else []
    ))
    sel_cats = st.multiselect("Категории", [x for x in all_cats if x])

    all_emps = sorted(
        list(employees["employee"].dropna().astype(str).unique()) if "employee" in employees else []
    )
    sel_emps = st.multiselect("Сотрудники", all_emps)

def apply_filters(df, store_col="store", cat_col="category", emp_col="employee"):
    x = df.copy()
    if sel_stores and store_col in x:
        x = x[x[store_col].astype(str).isin(sel_stores)]
    if sel_cats and cat_col in x:
        x = x[x[cat_col].astype(str).isin(sel_cats)]
    if sel_emps and emp_col in x:
        x = x[x[emp_col].astype(str).isin(sel_emps)]
    return x

sales_f = apply_filters(sales)
emp_f = apply_filters(employees)
shifts_f = apply_filters(shifts)

# ---------- TABS ----------
tabs = st.tabs([
    "Главная",
    "Продажи",
    "Сотрудники",
    "Рейтинг",
    "Антитоп",
    "План / факт / прогноз",
    "Графики смен",
    "Загрузка файлов",
])

# ---------- MAIN ----------
with tabs[0]:
    if not files:
        st.info("Загрузите файлы слева. Можно сразу несколько: продажи, сотрудники и графики смен.")
        st.markdown("""
        После загрузки приложение автоматически раскладывает данные по разделам:
        **Продажи → Сотрудники → Рейтинг → Антитоп → План/факт/прогноз → Графики смен**.
        """)
    else:
        c1, c2, c3, c4 = st.columns(4)
        if not sales_f.empty and "revenue_fact" in sales_f:
            fact = sales_f["revenue_fact"].sum()
            plan = sales_f["revenue_plan"].sum() if "revenue_plan" in sales_f else np.nan
            perf = fact/plan if pd.notna(plan) and plan > 0 else np.nan
            red = int((sales_f["revenue_perf"] < .8).sum()) if "revenue_perf" in sales_f else 0
            c1.metric("Выручка факт", fmt_money(fact))
            c2.metric("Выручка план", fmt_money(plan))
            c3.metric("Выполнение", fmt_pct(perf))
            c4.metric("Салонов <80%", red)
        elif not emp_f.empty and "employee_fact" in emp_f:
            fact = emp_f["employee_fact"].sum()
            plan = emp_f["employee_plan"].sum() if "employee_plan" in emp_f else np.nan
            perf = fact/plan if pd.notna(plan) and plan > 0 else np.nan
            red = int((emp_f["employee_perf"] < .8).sum()) if "employee_perf" in emp_f else 0
            c1.metric("Факт сотрудников", fmt_money(fact))
            c2.metric("План сотрудников", fmt_money(plan))
            c3.metric("Выполнение", fmt_pct(perf))
            c4.metric("Сотрудников <80%", red)
        else:
            c1.metric("Файлов", len(files))
            c2.metric("Листов распознано", len(all_raw))
            c3.metric("Продажи", len(sales_f))
            c4.metric("Сотрудники", len(emp_f))

        if not sales_f.empty and "store" in sales_f and "revenue_perf" in sales_f:
            chart = sales_f.dropna(subset=["revenue_perf"]).groupby("store", as_index=False).agg(
                revenue_perf=("revenue_perf","mean"),
                revenue_fact=("revenue_fact","sum")
            ).sort_values("revenue_perf")
            if not chart.empty:
                st.markdown('<div class="section-title">Выполнение по салонам</div>', unsafe_allow_html=True)
                fig = px.bar(chart, x="revenue_perf", y="store", orientation="h",
                             labels={"revenue_perf":"Выполнение","store":"Салон"},
                             text=chart["revenue_perf"].map(lambda x:f"{x:.0%}"))
                fig.add_vline(x=.8, line_dash="dash")
                fig.update_xaxes(tickformat=".0%")
                fig.update_layout(height=max(420, 30*len(chart)))
                st.plotly_chart(fig, use_container_width=True)

        if not emp_f.empty and "employee" in emp_f and "employee_fact" in emp_f:
            top = emp_f.groupby("employee", as_index=False)["employee_fact"].sum().nlargest(10, "employee_fact")
            if not top.empty:
                st.markdown('<div class="section-title">ТОП-10 сотрудников по факту</div>', unsafe_allow_html=True)
                fig = px.bar(top, x="employee_fact", y="employee", orientation="h",
                             labels={"employee_fact":"Факт","employee":"Сотрудник"})
                fig.update_layout(yaxis={"categoryorder":"total ascending"}, height=420)
                st.plotly_chart(fig, use_container_width=True)

# ---------- SALES ----------
with tabs[1]:
    st.subheader("Продажи по салонам")
    if sales_f.empty:
        st.info("Не найден отчёт по продажам. Загрузите файл, где есть салон и план/факт выручки.")
    else:
        cols = [c for c in [
            "store","city","category","revenue_plan","revenue_fact","revenue_forecast",
            "revenue_perf","revenue_gap","mz_plan","mz_fact","mz_forecast","mz_perf",
            "mo_fact","ol_fact","sz_fact","mkl_fact","traffic","checks","conversion"
        ] if c in sales_f]
        v = sales_f[cols].copy()
        rename = {
            "store":"Салон","city":"Город","category":"Категория",
            "revenue_plan":"План выручки","revenue_fact":"Факт выручки","revenue_forecast":"Прогноз выручки",
            "revenue_perf":"Выполнение","revenue_gap":"Gap",
            "mz_plan":"МЗ план","mz_fact":"МЗ факт","mz_forecast":"МЗ прогноз","mz_perf":"МЗ %",
            "mo_fact":"МО факт","ol_fact":"ОЛ факт","sz_fact":"СЗ факт","mkl_fact":"МКЛ факт",
            "traffic":"Трафик","checks":"Чеки","conversion":"Конверсия"
        }
        v = v.rename(columns=rename)
        for c in ["План выручки","Факт выручки","Прогноз выручки","Gap","МЗ план","МЗ факт","МЗ прогноз","МО факт","ОЛ факт","СЗ факт","МКЛ факт"]:
            if c in v: v[c] = v[c].map(fmt_money)
        for c in ["Выполнение","МЗ %","Конверсия"]:
            if c in v: v[c] = v[c].map(fmt_pct)
        st.dataframe(v, use_container_width=True, hide_index=True)

# ---------- EMPLOYEES ----------
with tabs[2]:
    st.subheader("Сотрудники")
    if emp_f.empty:
        st.info("Не найден отчёт сотрудников. Загрузите файл с ФИО, салоном и личным планом/фактом.")
    else:
        agg = {
            "store": ("store", unique_join),
            "category": ("category", unique_join),
            "position": ("position", unique_join),
        }
        if "outputs" in emp_f: agg["outputs"] = ("outputs","sum")
        if "employee_plan" in emp_f: agg["employee_plan"] = ("employee_plan","sum")
        if "employee_fact" in emp_f: agg["employee_fact"] = ("employee_fact","sum")
        g = emp_f.groupby("employee", as_index=False).agg(**agg)

        if "employee_plan" in g and "employee_fact" in g:
            g["employee_perf"] = np.where(g["employee_plan"]>0, g["employee_fact"]/g["employee_plan"], np.nan)
            g["gap"] = g["employee_fact"]-g["employee_plan"]
        if "outputs" in g and "employee_fact" in g:
            g["sales_per_output"] = np.where(g["outputs"]>0, g["employee_fact"]/g["outputs"], np.nan)

        rv = g.copy().rename(columns={
            "employee":"Сотрудник","store":"Салоны","category":"Категория","position":"Должность",
            "outputs":"Выходы","employee_plan":"План","employee_fact":"Факт",
            "employee_perf":"Выполнение","gap":"Gap","sales_per_output":"₽/выход"
        })
        for c in ["План","Факт","Gap","₽/выход"]:
            if c in rv: rv[c] = rv[c].map(fmt_money)
        if "Выполнение" in rv: rv["Выполнение"] = rv["Выполнение"].map(fmt_pct)
        st.dataframe(rv, use_container_width=True, hide_index=True)

# ---------- RATING ----------
with tabs[3]:
    st.subheader("Рейтинг сотрудников")
    if emp_f.empty or "employee" not in emp_f:
        st.info("Для рейтинга нужен отчёт сотрудников.")
    else:
        agg = {}
        if "store" in emp_f: agg["store"] = ("store", unique_join)
        if "outputs" in emp_f: agg["outputs"] = ("outputs","sum")
        if "employee_plan" in emp_f: agg["employee_plan"] = ("employee_plan","sum")
        if "employee_fact" in emp_f: agg["employee_fact"] = ("employee_fact","sum")
        if "mz_qty" in emp_f: agg["mz_qty"] = ("mz_qty","sum")
        if "sz_qty" in emp_f: agg["sz_qty"] = ("sz_qty","sum")

        g = emp_f.groupby("employee", as_index=False).agg(**agg)
        if "employee_plan" in g and "employee_fact" in g:
            g["employee_perf"] = np.where(g["employee_plan"]>0, g["employee_fact"]/g["employee_plan"], np.nan)
        if "outputs" in g and "employee_fact" in g:
            g["sales_per_output"] = np.where(g["outputs"]>0, g["employee_fact"]/g["outputs"], np.nan)

        options = []
        mapping = {}
        if "employee_fact" in g:
            options.append("Факт выручки"); mapping["Факт выручки"] = "employee_fact"
        if "employee_perf" in g:
            options.append("Выполнение плана"); mapping["Выполнение плана"] = "employee_perf"
        if "sales_per_output" in g:
            options.append("₽ на выход"); mapping["₽ на выход"] = "sales_per_output"
        if "mz_qty" in g:
            options.append("МЗ шт."); mapping["МЗ шт."] = "mz_qty"
        if "sz_qty" in g:
            options.append("СЗ шт."); mapping["СЗ шт."] = "sz_qty"

        if options:
            metric = st.radio("Рейтинг по", options, horizontal=True)
            rank = g.sort_values(mapping[metric], ascending=False).reset_index(drop=True)
            rank.insert(0, "Место", range(1, len(rank)+1))
            rv = rank.rename(columns={
                "employee":"Сотрудник","store":"Салоны","employee_fact":"Факт",
                "employee_plan":"План","employee_perf":"Выполнение",
                "sales_per_output":"₽/выход","mz_qty":"МЗ шт.","sz_qty":"СЗ шт."
            })
            for c in ["Факт","План","₽/выход"]:
                if c in rv: rv[c] = rv[c].map(fmt_money)
            if "Выполнение" in rv: rv["Выполнение"] = rv["Выполнение"].map(fmt_pct)
            st.dataframe(rv, use_container_width=True, hide_index=True)
        else:
            st.info("В отчёте недостаточно числовых полей для рейтинга.")

# ---------- ANTI-TOP ----------
with tabs[4]:
    st.subheader("Антитоп / красная зона")
    red_tabs = st.tabs(["Салоны", "Сотрудники"])

    with red_tabs[0]:
        if sales_f.empty or "revenue_perf" not in sales_f:
            st.info("Для красной зоны салонов нужен план и факт выручки.")
        else:
            r = sales_f[sales_f["revenue_perf"] < .8].sort_values("revenue_perf").copy()
            if r.empty:
                st.success("Салонов ниже 80% нет.")
            else:
                cols = [c for c in ["store","category","revenue_plan","revenue_fact","revenue_perf","revenue_gap"] if c in r]
                r = r[cols].rename(columns={
                    "store":"Салон","category":"Категория","revenue_plan":"План",
                    "revenue_fact":"Факт","revenue_perf":"Выполнение","revenue_gap":"Gap"
                })
                for c in ["План","Факт","Gap"]:
                    if c in r: r[c]=r[c].map(fmt_money)
                r["Выполнение"]=r["Выполнение"].map(fmt_pct)
                st.dataframe(r.head(20), use_container_width=True, hide_index=True)

    with red_tabs[1]:
        if emp_f.empty or "employee_perf" not in emp_f:
            st.info("Для красной зоны сотрудников нужен личный план и факт.")
        else:
            g = emp_f.groupby("employee", as_index=False).agg(
                store=("store", unique_join),
                employee_plan=("employee_plan","sum"),
                employee_fact=("employee_fact","sum")
            )
            g["employee_perf"]=np.where(g["employee_plan"]>0,g["employee_fact"]/g["employee_plan"],np.nan)
            g["gap"]=g["employee_fact"]-g["employee_plan"]
            g=g[g["employee_perf"]<.8].sort_values("employee_perf")
            if g.empty:
                st.success("Сотрудников ниже 80% нет.")
            else:
                g=g.rename(columns={
                    "employee":"Сотрудник","store":"Салоны","employee_plan":"План",
                    "employee_fact":"Факт","employee_perf":"Выполнение","gap":"Gap"
                })
                for c in ["План","Факт","Gap"]: g[c]=g[c].map(fmt_money)
                g["Выполнение"]=g["Выполнение"].map(fmt_pct)
                st.dataframe(g.head(20), use_container_width=True, hide_index=True)

# ---------- PLAN FACT FORECAST ----------
with tabs[5]:
    st.subheader("План / факт / прогноз")
    if sales_f.empty:
        st.info("Загрузите отчёт по продажам.")
    else:
        metrics = [
            ("Выручка","revenue_plan","revenue_fact","revenue_forecast"),
            ("МЗ","mz_plan","mz_fact","mz_forecast"),
            ("МО","mo_plan","mo_fact","mo_forecast"),
            ("ОЛ","ol_plan","ol_fact","ol_forecast"),
            ("СЗ","sz_plan","sz_fact","sz_forecast"),
            ("МКЛ","mkl_plan","mkl_fact","mkl_forecast"),
        ]
        rows=[]
        for name, p, fct, fc in metrics:
            if p in sales_f or fct in sales_f or fc in sales_f:
                plan=sales_f[p].sum() if p in sales_f else np.nan
                fact=sales_f[fct].sum() if fct in sales_f else np.nan
                forecast=sales_f[fc].sum() if fc in sales_f else np.nan
                perf=fact/plan if pd.notna(plan) and plan>0 and pd.notna(fact) else np.nan
                prog=forecast/plan if pd.notna(plan) and plan>0 and pd.notna(forecast) else np.nan
                rows.append([name,plan,fact,forecast,perf,prog])
        if rows:
            t=pd.DataFrame(rows,columns=["Показатель","План","Факт","Прогноз","Факт %","Прогноз %"])
            show=t.copy()
            for c in ["План","Факт","Прогноз"]: show[c]=show[c].map(fmt_money)
            for c in ["Факт %","Прогноз %"]: show[c]=show[c].map(fmt_pct)
            st.dataframe(show,use_container_width=True,hide_index=True)

            plot=t.melt(id_vars="Показатель",value_vars=["План","Факт","Прогноз"],
                        var_name="Тип",value_name="Сумма").dropna()
            fig=px.bar(plot,x="Показатель",y="Сумма",color="Тип",barmode="group")
            st.plotly_chart(fig,use_container_width=True)
        else:
            st.info("Не распознаны колонки план/факт/прогноз.")

# ---------- SHIFTS ----------
with tabs[6]:
    st.subheader("Графики смен")
    if shifts_f.empty:
        st.info("Загрузите файл графика смен: ФИО, салон, дата смены, часы.")
    else:
        if "date" in shifts_f and shifts_f["date"].notna().any():
            min_d = shifts_f["date"].min().date()
            max_d = shifts_f["date"].max().date()
            date_range = st.date_input("Период", value=(min_d, max_d))
            sh = shifts_f.copy()
            if isinstance(date_range, tuple) and len(date_range) == 2:
                sh = sh[
                    (sh["date"].dt.date >= date_range[0]) &
                    (sh["date"].dt.date <= date_range[1])
                ]
        else:
            sh = shifts_f.copy()

        if "store" in sh and "date" in sh:
            daily = sh.groupby(["store","date"], as_index=False).agg(
                people=("employee","nunique"),
                hours=("hours","sum") if "hours" in sh else ("employee","size")
            )
            daily["Смена"] = daily["people"].map(lambda n: "В смене никого нет" if n==0 else f"В смене {n} чел.")
            rv = daily.rename(columns={"store":"Салон","date":"Дата","people":"Вышло","hours":"Часов"})
            rv["Дата"] = rv["Дата"].dt.strftime("%d.%m.%Y")
            st.dataframe(rv, use_container_width=True, hide_index=True)

            fig = px.bar(daily, x="date", y="people", color="store",
                         labels={"date":"Дата","people":"В смене","store":"Салон"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            rv=sh.copy().rename(columns={
                "employee":"ФИО","store":"Салон","date":"Дата","hours":"Часов",
                "correction":"Корректировки","status":"Статус"
            })
            st.dataframe(rv,use_container_width=True,hide_index=True)

# ---------- UPLOAD DIAGNOSTICS ----------
with tabs[7]:
    st.subheader("Загрузка файлов")
    if not files:
        st.info("Загрузите файлы в левой панели.")
    else:
        st.markdown("**Что приложение распознало:**")
        summary=[]
        for source, df, kind in all_raw:
            label={"sales":"Продажи","employees":"Сотрудники","shifts":"График смен","other":"Не распознано"}[kind]
            summary.append({"Источник":source,"Тип":label,"Строк":len(df),"Колонок":len(df.columns)})
        st.dataframe(pd.DataFrame(summary),use_container_width=True,hide_index=True)

        st.markdown("**Итог после объединения:**")
        a,b,c,d=st.columns(4)
        a.metric("Продажи",len(sales))
        b.metric("Сотрудники",len(employees))
        c.metric("Смены",len(shifts))
        d.metric("Не распознано",len(other_parts))

        if other_parts:
            st.warning("Есть листы, которые приложение не смогло автоматически отнести к разделу.")
            for source, df in other_parts:
                with st.expander(source):
                    st.write("Колонки:", list(map(str,df.columns)))
                    st.dataframe(df.head(20),use_container_width=True)
