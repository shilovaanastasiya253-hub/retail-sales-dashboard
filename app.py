import io
import re
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="Retail BI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 2rem; max-width: 1650px;}
[data-testid="stMetric"] {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,.30);
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
div[data-baseweb="tab-list"] {gap: 6px;}
div[data-baseweb="tab"] {
    border-radius: 10px 10px 0 0;
    padding-left: 12px;
    padding-right: 12px;
}
.section-title {font-size:1.18rem;font-weight:700;margin:.45rem 0 .65rem;}
.small-note {opacity:.72;font-size:.86rem;}
</style>
""", unsafe_allow_html=True)

# -------------------- FORMATTERS --------------------
def money(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):,.0f} ₽".replace(",", " ")

def pct(v):
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):.1%}".replace(".", ",")

def qty(v, digits=0):
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):,.{digits}f}".replace(",", " ").replace(".", ",")

def clean_num(s):
    if isinstance(s, pd.Series):
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        x = s.astype(str)
    else:
        x = pd.Series(s).astype(str)

    x = (
        x.str.replace("\u00a0", "", regex=False)
         .str.replace(" ", "", regex=False)
         .str.replace("₽", "", regex=False)
         .str.replace("%", "", regex=False)
         .str.replace(",", ".", regex=False)
         .str.replace("—", "", regex=False)
         .str.replace("#REF!", "", regex=False)
         .str.replace("#VALUE!", "", regex=False)
    )
    return pd.to_numeric(x, errors="coerce")

def clean_text(s):
    return s.fillna("").astype(str).str.strip()

def parse_pct_series(s):
    x = clean_num(s)
    med = x.dropna().median() if x.notna().any() else np.nan
    if pd.notna(med) and med > 1.5:
        x = x / 100.0
    return x

def compact(s):
    s = str(s).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", s)

def normalize_store_code(v):
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

# -------------------- GOOGLE SHEET URL --------------------
def extract_sheet_id(url):
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", str(url))
    return m.group(1) if m else None

@st.cache_data(ttl=120, show_spinner=False)
def download_google_sheet_xlsx(url):
    sid = extract_sheet_id(url)
    if not sid:
        raise ValueError("Не удалось определить ID Google-таблицы.")
    export_url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    r = requests.get(export_url, timeout=30)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "")
    if "html" in ctype.lower():
        raise ValueError(
            "Google вернул страницу входа вместо файла. "
            "Для прямого подключения нужен доступ «Все, у кого есть ссылка»."
        )
    return r.content

# -------------------- WORKBOOK READER --------------------
def read_raw_workbook(file_bytes):
    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = {}
    for sh in xls.sheet_names:
        try:
            raw = pd.read_excel(xls, sheet_name=sh, header=None)
            sheets[sh] = raw
        except Exception:
            pass
    return sheets

def row_contains(raw, row_idx, tokens):
    if row_idx >= len(raw):
        return False
    vals = [compact(x) for x in raw.iloc[row_idx].tolist()]
    joined = "|".join(vals)
    return sum(compact(t) in joined for t in tokens)

def find_header_row(raw, tokens, max_rows=40):
    best = (0, None)
    for i in range(min(max_rows, len(raw))):
        score = row_contains(raw, i, tokens)
        if score > best[0]:
            best = (score, i)
    return best[1] if best[0] >= 2 else None

def slice_after(raw, header_row, ncols=None):
    x = raw.iloc[header_row + 1:].copy()
    if ncols:
        x = x.iloc[:, :ncols]
    x = x.dropna(how="all")
    return x.reset_index(drop=True)

# -------------------- KNOWN SHEETS: USER REPORT --------------------
def parse_daily_input(raw):
    # Ввод факта — header normally row 13 (1-based)
    h = find_header_row(raw, ["Дата", "Код салона", "Выручка РС", "Выручка МЗ", "МЗ итого шт"])
    if h is None:
        return pd.DataFrame()
    x = slice_after(raw, h, 15)
    x.columns = [
        "date","store","store_name","revenue_fact","mz_fact","mz_qty_fact",
        "mo_avg_fact","ol_avg_fact","mz_avg_fact",
        "sz_fact","sz_qty_fact","sz_avg_fact",
        "mkl_fact","mkl_qty_fact","mkl_avg_fact"
    ]
    x["date"] = pd.to_datetime(x["date"], errors="coerce", dayfirst=True)
    x["store"] = x["store"].map(normalize_store_code)
    x["store_name"] = clean_text(x["store_name"])
    for c in x.columns:
        if c not in ["date","store","store_name"]:
            x[c] = clean_num(x[c])
    x = x[x["date"].notna() & x["store"].ne("")]
    return x

def parse_current_day(raw):
    # Ежедневный план — fixed layout A:V, header normally row 16
    h = find_header_row(raw, ["Закрыта сегодня", "Код салона", "Выручка план", "Выручка факт", "План руб МЗ"])
    if h is None:
        return pd.DataFrame()
    x = slice_after(raw, h, 22)
    x.columns = [
        "closed","store","store_name","blank",
        "revenue_plan","revenue_fact","revenue_perf",
        "mz_plan","mz_fact","mz_perf",
        "mz_qty_plan","mz_qty_fact","mz_qty_perf",
        "mz_avg_plan","mz_avg_fact","mz_avg_perf",
        "diag_plan","diag_fact","diag_perf",
        "lo_plan","lo_fact","lo_perf"
    ]
    x["store"] = x["store"].map(normalize_store_code)
    x["store_name"] = clean_text(x["store_name"])
    x["closed"] = clean_text(x["closed"])
    x = x[x["store"].ne("") & ~x["store"].str.upper().eq("ИТОГО")]
    for c in [
        "revenue_plan","revenue_fact","mz_plan","mz_fact",
        "mz_qty_plan","mz_qty_fact","mz_avg_plan","mz_avg_fact",
        "diag_plan","diag_fact","lo_plan","lo_fact"
    ]:
        x[c] = clean_num(x[c])
    for c in ["revenue_perf","mz_perf","mz_qty_perf","mz_avg_perf","diag_perf","lo_perf"]:
        x[c] = parse_pct_series(x[c])
    # fallback calculations
    x["revenue_perf"] = np.where(
        x["revenue_perf"].notna(), x["revenue_perf"],
        np.where(x["revenue_plan"] > 0, x["revenue_fact"]/x["revenue_plan"], np.nan)
    )
    x["revenue_gap"] = x["revenue_fact"].fillna(0) - x["revenue_plan"].fillna(0)
    return x

def parse_monthly_plans(raw):
    # Планы — header normally row 12
    h = find_header_row(raw, ["Код салона", "Наименование ТТ", "Выручка РС", "Выручка МЗ", "МЗ итого шт"])
    if h is None:
        return pd.DataFrame()
    x = slice_after(raw, h, 16)
    x.columns = [
        "store","store_name","active","closed_today",
        "revenue_plan_month","mz_plan_month","mz_qty_plan_month",
        "mo_avg_plan","ol_avg_plan","mz_avg_plan_month",
        "sz_plan_month","sz_qty_plan_month","sz_avg_plan",
        "mkl_plan_month","mkl_qty_plan_month","mkl_avg_plan"
    ]
    x["store"] = x["store"].map(normalize_store_code)
    x["store_name"] = clean_text(x["store_name"])
    x["active"] = clean_text(x["active"])
    x["closed_today"] = clean_text(x["closed_today"])
    x = x[x["store"].ne("") & ~x["store"].str.upper().eq("ИТОГО")]
    for c in x.columns:
        if c not in ["store","store_name","active","closed_today"]:
            x[c] = clean_num(x[c])
    return x

def parse_employee_rating(raw):
    # Рейтинг сотрудников — header normally row 11
    h = find_header_row(raw, ["Место", "ФИО", "ТТ", "План выручки", "Выручка"])
    if h is None:
        return pd.DataFrame()
    x = slice_after(raw, h, 11)
    x.columns = [
        "place","employee","store","employee_plan","employee_fact",
        "employee_perf","mz_qty","mz_avg","mo_avg","status","comment"
    ]
    x["employee"] = clean_text(x["employee"])
    x["store"] = clean_text(x["store"])
    x["status"] = clean_text(x["status"])
    x["comment"] = clean_text(x["comment"])
    x = x[x["employee"].ne("")]
    x["employee_plan"] = clean_num(x["employee_plan"])
    x["employee_fact"] = clean_num(x["employee_fact"])
    x["employee_perf"] = parse_pct_series(x["employee_perf"])
    x["mz_qty"] = clean_num(x["mz_qty"])
    x["mz_avg"] = clean_num(x["mz_avg"])
    x["mo_avg"] = clean_num(x["mo_avg"])
    x["employee_perf"] = np.where(
        x["employee_perf"].notna(), x["employee_perf"],
        np.where(x["employee_plan"] > 0, x["employee_fact"]/x["employee_plan"], np.nan)
    )
    x["employee_gap"] = x["employee_fact"].fillna(0) - x["employee_plan"].fillna(0)
    return x

def parse_six_day(raw):
    # планы на 6 дней — row 1 is header
    if raw.empty:
        return pd.DataFrame()
    h = find_header_row(raw, ["Салон", "План РС", "План МЗ", "Диагностика"])
    if h is None:
        return pd.DataFrame()
    x = slice_after(raw, h, 27)
    cols = [
        "store_label","plan_rs","plan_rs_day","plan_mz","plan_mz_day",
        "plan_mz_qty","plan_mz_qty_day","plan_mz_avg",
        "diag_plan_6","lo_plan_6","blank",
        "store_label_2","fact_rs_accum","perf_rs","fact_mz_accum","perf_mz",
        "fact_mz_qty_accum","perf_mz_qty","diag_plan_again","diag_fact_accum",
        "diag_perf","lo_plan_sector","lo_fact_accum","lo_perf",
        "plan_mz_avg_2","fact_mz_avg","perf_mz_avg"
    ]
    x.columns = cols
    x["store_label"] = clean_text(x["store_label"])
    x = x[x["store_label"].ne("") & ~x["store_label"].str.upper().eq("ИТОГО")]
    for c in cols:
        if c not in ["store_label","store_label_2","blank"]:
            if "perf" in c:
                x[c] = parse_pct_series(x[c])
            else:
                x[c] = clean_num(x[c])
    x["store"] = x["store_label"].str.extract(r"^([0-9]+(?:-1)?)", expand=False).fillna("")
    return x

# -------------------- GENERIC SHIFT FILE --------------------
def parse_generic_shifts(raw):
    h = find_header_row(raw, ["ФИО", "САЛОН", "МАГАЗИН", "ЧАСОВ", "ДАТА СМЕНЫ"])
    if h is None:
        return pd.DataFrame()
    headers = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[h].tolist()]
    x = raw.iloc[h+1:].copy()
    x.columns = [compact(c) or f"col{i}" for i, c in enumerate(headers)]
    x = x.dropna(how="all")
    out = pd.DataFrame()
    def col(name_options):
        for n in name_options:
            k = compact(n)
            if k in x.columns:
                return x[k]
        return None
    emp = col(["ФИО"])
    store = col(["САЛОН","МАГАЗИН"])
    date = col(["ДАТА СМЕНЫ","Дата"])
    hours = col(["ЧАСОВ","Часы"])
    correction = col(["КОРРЕКТИРОВКИ","Корректировка"])
    if emp is None or store is None:
        return pd.DataFrame()
    out["employee"] = clean_text(emp)
    out["store"] = clean_text(store).map(normalize_store_code)
    out["date"] = pd.to_datetime(date, errors="coerce", dayfirst=True) if date is not None else pd.NaT
    out["hours"] = clean_num(hours) if hours is not None else np.nan
    out["correction"] = clean_text(correction) if correction is not None else ""
    return out[out["employee"].ne("")]

# -------------------- LOAD --------------------
st.title("📊 Retail BI")
st.caption("Продажи · сотрудники · рейтинг · антитоп · план/факт · динамика · графики смен")

with st.sidebar:
    st.header("Источник данных")
    gsheet_url = st.text_input(
        "Google Sheets URL (необязательно)",
        placeholder="https://docs.google.com/spreadsheets/d/..."
    )
    files = st.file_uploader(
        "Или загрузите Excel / XLSM",
        type=["xlsx","xls","xlsm"],
        accept_multiple_files=True
    )
    st.caption(
        "Можно использовать ссылку на Google-таблицу или загрузить выгруженный Excel. "
        "Для прямой ссылки таблица должна быть доступна по ссылке без входа."
    )

workbooks = []
load_messages = []

if gsheet_url.strip():
    try:
        with st.spinner("Загружаю Google-таблицу…"):
            b = download_google_sheet_xlsx(gsheet_url.strip())
            workbooks.append(("Google Sheet", read_raw_workbook(b)))
            load_messages.append("Google Sheet подключён")
    except Exception as e:
        st.sidebar.warning(str(e))

if files:
    for f in files:
        try:
            workbooks.append((f.name, read_raw_workbook(f.getvalue())))
            load_messages.append(f"{f.name} загружен")
        except Exception as e:
            st.sidebar.warning(f"{f.name}: {e}")

current_sales_parts = []
daily_history_parts = []
monthly_plan_parts = []
employee_parts = []
six_day_parts = []
shift_parts = []
unrecognized = []

for wb_name, sheets in workbooks:
    for sh, raw in sheets.items():
        shc = compact(sh)
        try:
            if shc == compact("Ввод факта"):
                d = parse_daily_input(raw)
                if not d.empty:
                    d["source"] = f"{wb_name} · {sh}"
                    daily_history_parts.append(d)
                    continue
            if shc == compact("Ежедневный план"):
                d = parse_current_day(raw)
                if not d.empty:
                    d["source"] = f"{wb_name} · {sh}"
                    current_sales_parts.append(d)
                    continue
            if shc == compact("Планы"):
                d = parse_monthly_plans(raw)
                if not d.empty:
                    d["source"] = f"{wb_name} · {sh}"
                    monthly_plan_parts.append(d)
                    continue
            if shc == compact("Рейтинг сотрудников"):
                d = parse_employee_rating(raw)
                if not d.empty:
                    d["source"] = f"{wb_name} · {sh}"
                    employee_parts.append(d)
                    continue
            if shc == compact("планы на 6 дней"):
                d = parse_six_day(raw)
                if not d.empty:
                    d["source"] = f"{wb_name} · {sh}"
                    six_day_parts.append(d)
                    continue

            # external shift workbook or other sheets
            d = parse_generic_shifts(raw)
            if not d.empty:
                d["source"] = f"{wb_name} · {sh}"
                shift_parts.append(d)
            else:
                unrecognized.append((f"{wb_name} · {sh}", raw))
        except Exception:
            unrecognized.append((f"{wb_name} · {sh}", raw))

current_sales = pd.concat(current_sales_parts, ignore_index=True) if current_sales_parts else pd.DataFrame()
daily_history = pd.concat(daily_history_parts, ignore_index=True) if daily_history_parts else pd.DataFrame()
monthly_plans = pd.concat(monthly_plan_parts, ignore_index=True) if monthly_plan_parts else pd.DataFrame()
employees = pd.concat(employee_parts, ignore_index=True) if employee_parts else pd.DataFrame()
six_day = pd.concat(six_day_parts, ignore_index=True) if six_day_parts else pd.DataFrame()
shifts = pd.concat(shift_parts, ignore_index=True) if shift_parts else pd.DataFrame()

with st.sidebar:
    st.divider()
    st.header("Фильтры")

    store_pool = set()
    for df in [current_sales, daily_history, monthly_plans, shifts]:
        if not df.empty and "store" in df:
            store_pool.update(df["store"].dropna().astype(str))
    stores = sorted(s for s in store_pool if s)
    sel_stores = st.multiselect("Салоны", stores)

    emp_pool = sorted(employees["employee"].dropna().unique()) if not employees.empty else []
    sel_employees = st.multiselect("Сотрудники", emp_pool)

def filter_store(df):
    if df.empty:
        return df
    x = df.copy()
    if sel_stores and "store" in x:
        x = x[x["store"].astype(str).isin(sel_stores)]
    return x

current_f = filter_store(current_sales)
history_f = filter_store(daily_history)
plans_f = filter_store(monthly_plans)
six_f = filter_store(six_day)
shifts_f = filter_store(shifts)

employees_f = employees.copy()
if sel_employees and not employees_f.empty:
    employees_f = employees_f[employees_f["employee"].isin(sel_employees)]
if sel_stores and not employees_f.empty:
    employees_f = employees_f[
        employees_f["store"].astype(str).apply(
            lambda s: any(code in [x.strip() for x in re.split(r"[;,]", s)] for code in sel_stores)
        )
    ]

tabs = st.tabs([
    "Главная",
    "Продажи",
    "Сотрудники",
    "Рейтинг",
    "Антитоп",
    "План / факт",
    "Динамика",
    "Графики смен",
    "Загрузка"
])

# -------------------- MAIN --------------------
with tabs[0]:
    if current_f.empty and history_f.empty and employees_f.empty:
        st.info(
            "Подключите Google-таблицу слева или загрузите Excel. "
            "Для вашей рабочей таблицы приложение понимает листы "
            "«Ежедневный план», «Ввод факта», «Планы» и «Рейтинг сотрудников»."
        )
    else:
        c1, c2, c3, c4 = st.columns(4)
        if not current_f.empty:
            fact = current_f["revenue_fact"].fillna(0).sum()
            plan = current_f["revenue_plan"].fillna(0).sum()
            perf = fact / plan if plan > 0 else np.nan
            red = int((current_f["revenue_perf"] < .8).fillna(False).sum())
            c1.metric("Выручка факт", money(fact))
            c2.metric("Выручка план", money(plan))
            c3.metric("Выполнение", pct(perf))
            c4.metric("Салонов <80%", red)

            chart = current_f[current_f["revenue_plan"] > 0].copy().sort_values("revenue_perf")
            if not chart.empty:
                st.markdown('<div class="section-title">Выполнение по салонам</div>', unsafe_allow_html=True)
                fig = px.bar(
                    chart,
                    x="revenue_perf",
                    y="store",
                    orientation="h",
                    hover_data=["store_name","revenue_plan","revenue_fact"],
                    text=chart["revenue_perf"].map(lambda x: f"{x:.0%}" if pd.notna(x) else "—"),
                    labels={"revenue_perf":"Выполнение","store":"Салон"}
                )
                fig.add_vline(x=.8, line_dash="dash")
                fig.update_xaxes(tickformat=".0%")
                fig.update_layout(height=max(420, len(chart)*30))
                st.plotly_chart(fig, use_container_width=True)
        else:
            c1.metric("История строк", len(history_f))
            c2.metric("Сотрудников", len(employees_f))
            c3.metric("Планов ТТ", len(plans_f))
            c4.metric("Смен", len(shifts_f))

        if not employees_f.empty:
            top = employees_f.sort_values("employee_fact", ascending=False).head(10)
            st.markdown('<div class="section-title">ТОП-10 сотрудников по выручке</div>', unsafe_allow_html=True)
            fig = px.bar(
                top, x="employee_fact", y="employee", orientation="h",
                labels={"employee_fact":"Выручка","employee":"Сотрудник"}
            )
            fig.update_layout(yaxis={"categoryorder":"total ascending"}, height=420)
            st.plotly_chart(fig, use_container_width=True)

# -------------------- SALES --------------------
with tabs[1]:
    st.subheader("Продажи по салонам · текущий день")
    if current_f.empty:
        st.info("Не найден лист «Ежедневный план».")
    else:
        v = current_f[[
            "closed","store","store_name",
            "revenue_plan","revenue_fact","revenue_perf",
            "mz_plan","mz_fact","mz_perf",
            "mz_qty_plan","mz_qty_fact","mz_qty_perf",
            "mz_avg_plan","mz_avg_fact","mz_avg_perf",
            "diag_plan","diag_fact","diag_perf",
            "lo_plan","lo_fact","lo_perf"
        ]].copy()
        v.columns = [
            "Закрыта","Салон","ТТ",
            "Выручка план","Выручка факт","Выручка %",
            "МЗ план ₽","МЗ факт ₽","МЗ %",
            "МЗ план шт","МЗ факт шт","МЗ шт %",
            "МЗ чек план","МЗ чек факт","МЗ чек %",
            "Диагн. план","Диагн. факт","Диагн. %",
            "ЛО план ₽","ЛО факт ₽","ЛО %"
        ]
        for c in ["Выручка план","Выручка факт","МЗ план ₽","МЗ факт ₽","МЗ чек план","МЗ чек факт","ЛО план ₽","ЛО факт ₽"]:
            v[c] = v[c].map(money)
        for c in ["Выручка %","МЗ %","МЗ шт %","МЗ чек %","Диагн. %","ЛО %"]:
            v[c] = v[c].map(pct)
        st.dataframe(v, use_container_width=True, hide_index=True)

# -------------------- EMPLOYEES --------------------
with tabs[2]:
    st.subheader("Сотрудники")
    if employees_f.empty:
        st.info("Не найден лист «Рейтинг сотрудников».")
    else:
        v = employees_f[[
            "employee","store","employee_plan","employee_fact","employee_perf",
            "mz_qty","mz_avg","mo_avg","status","comment"
        ]].copy()
        v.columns = [
            "Сотрудник","ТТ","План","Факт","Выполнение",
            "МЗ шт","Ср. чек МЗ","Ср. чек МО","Статус","Комментарий"
        ]
        for c in ["План","Факт","Ср. чек МЗ","Ср. чек МО"]:
            v[c] = v[c].map(money)
        v["Выполнение"] = v["Выполнение"].map(pct)
        v["МЗ шт"] = v["МЗ шт"].map(lambda x: qty(x) if pd.notna(x) else "—")
        st.dataframe(v, use_container_width=True, hide_index=True)

# -------------------- RATING --------------------
with tabs[3]:
    st.subheader("Рейтинг сотрудников")
    if employees_f.empty:
        st.info("Для рейтинга нужен лист «Рейтинг сотрудников».")
    else:
        metric = st.radio("Рейтинг по", ["Факт выручки","Выполнение плана"], horizontal=True)
        col = "employee_fact" if metric == "Факт выручки" else "employee_perf"
        r = employees_f.sort_values(col, ascending=False).reset_index(drop=True).copy()
        r.insert(0, "Место", range(1, len(r)+1))
        show = r[["Место","employee","store","employee_plan","employee_fact","employee_perf","status"]].copy()
        show.columns = ["Место","Сотрудник","ТТ","План","Факт","Выполнение","Статус"]
        show["План"] = show["План"].map(money)
        show["Факт"] = show["Факт"].map(money)
        show["Выполнение"] = show["Выполнение"].map(pct)
        st.dataframe(show, use_container_width=True, hide_index=True)

# -------------------- ANTITOP --------------------
with tabs[4]:
    st.subheader("Антитоп / красная зона")
    subtabs = st.tabs(["Салоны","Сотрудники"])
    with subtabs[0]:
        if current_f.empty:
            st.info("Нет данных текущего дня.")
        else:
            r = current_f[(current_f["revenue_plan"] > 0) & (current_f["revenue_perf"] < .8)].copy()
            r = r.sort_values("revenue_perf")
            if r.empty:
                st.success("Салонов ниже 80% нет.")
            else:
                show = r[["store","store_name","revenue_plan","revenue_fact","revenue_perf","revenue_gap"]].copy()
                show.columns = ["Салон","ТТ","План","Факт","Выполнение","Gap"]
                for c in ["План","Факт","Gap"]:
                    show[c] = show[c].map(money)
                show["Выполнение"] = show["Выполнение"].map(pct)
                st.dataframe(show.head(20), use_container_width=True, hide_index=True)

    with subtabs[1]:
        if employees_f.empty:
            st.info("Нет данных сотрудников.")
        else:
            r = employees_f[employees_f["employee_perf"] < .8].sort_values("employee_perf")
            if r.empty:
                st.success("Сотрудников ниже 80% нет.")
            else:
                show = r[["employee","store","employee_plan","employee_fact","employee_perf","employee_gap"]].copy()
                show.columns = ["Сотрудник","ТТ","План","Факт","Выполнение","Gap"]
                for c in ["План","Факт","Gap"]:
                    show[c] = show[c].map(money)
                show["Выполнение"] = show["Выполнение"].map(pct)
                st.dataframe(show.head(20), use_container_width=True, hide_index=True)

# -------------------- PLAN FACT --------------------
with tabs[5]:
    st.subheader("План / факт")
    if current_f.empty:
        st.info("Нет данных «Ежедневного плана».")
    else:
        rows = []
        specs = [
            ("Выручка","revenue_plan","revenue_fact"),
            ("МЗ, ₽","mz_plan","mz_fact"),
            ("МЗ, шт","mz_qty_plan","mz_qty_fact"),
            ("Средний чек МЗ","mz_avg_plan","mz_avg_fact"),
            ("Диагностика, шт","diag_plan","diag_fact"),
            ("ЛО, ₽","lo_plan","lo_fact"),
        ]
        for name, pcol, fcol in specs:
            p = current_f[pcol].fillna(0).sum()
            f = current_f[fcol].fillna(0).sum()
            # average ticket is not additive: weighted/mean fallback
            if "avg" in pcol:
                p = current_f.loc[current_f[pcol] > 0, pcol].mean()
                f = current_f.loc[current_f[fcol] > 0, fcol].mean()
            perf = f/p if pd.notna(p) and p > 0 else np.nan
            rows.append([name,p,f,f-p if pd.notna(p) and pd.notna(f) else np.nan,perf])

        t = pd.DataFrame(rows, columns=["Показатель","План","Факт","Отклонение Ф–П","Выполнение"])
        # Форматируем отображение в отдельной object-таблице.
        # Это совместимо с новыми версиями pandas, которые запрещают
        # записывать строки вроде "398 140 ₽" прямо в float-колонки.
        show = t.astype(object).copy()
        money_rows = {"Выручка","МЗ, ₽","Средний чек МЗ","ЛО, ₽"}
        for idx, row in show.iterrows():
            if row["Показатель"] in money_rows:
                for c in ["План","Факт","Отклонение Ф–П"]:
                    show.at[idx,c] = money(row[c])
            else:
                for c in ["План","Факт","Отклонение Ф–П"]:
                    show.at[idx,c] = qty(row[c])
            show.at[idx,"Выполнение"] = pct(row["Выполнение"])
        st.dataframe(show, use_container_width=True, hide_index=True)

        st.caption("Прогноз не рассчитываю автоматически: в источнике нет подтверждённой формулы прогноза.")

# -------------------- DYNAMICS --------------------
with tabs[6]:
    st.subheader("Динамика")
    if history_f.empty:
        st.info("Для динамики нужен лист «Ввод факта».")
    else:
        dyn = history_f.groupby("date", as_index=False).agg(
            revenue=("revenue_fact","sum"),
            mz=("mz_fact","sum"),
            mz_qty=("mz_qty_fact","sum"),
            sz=("sz_fact","sum"),
            mkl=("mkl_fact","sum")
        ).sort_values("date")

        metric = st.selectbox(
            "Показатель",
            ["Выручка","МЗ, ₽","МЗ, шт","СЗ, ₽","МКЛ, ₽"]
        )
        m = {
            "Выручка":"revenue",
            "МЗ, ₽":"mz",
            "МЗ, шт":"mz_qty",
            "СЗ, ₽":"sz",
            "МКЛ, ₽":"mkl"
        }[metric]
        fig = px.line(dyn, x="date", y=m, markers=True, labels={"date":"Дата",m:metric})
        st.plotly_chart(fig, use_container_width=True)

        if len(dyn) >= 2:
            first = dyn.iloc[0][m]
            last = dyn.iloc[-1][m]
            delta = (last-first)/first if pd.notna(first) and first != 0 else np.nan
            a,b,c = st.columns(3)
            a.metric("Начало периода", money(first) if m != "mz_qty" else qty(first))
            b.metric("Конец периода", money(last) if m != "mz_qty" else qty(last))
            c.metric("Изменение", pct(delta))

# -------------------- SHIFTS --------------------
with tabs[7]:
    st.subheader("Графики смен")
    if shifts_f.empty:
        st.info("Для графиков смен загрузите отдельный файл с ФИО, салоном, датой смены и часами.")
    else:
        if shifts_f["date"].notna().any():
            d = shifts_f.dropna(subset=["date"]).groupby(["store","date"], as_index=False).agg(
                people=("employee","nunique"),
                hours=("hours","sum")
            )
            d["Смена"] = d["people"].map(lambda n: f"В смене {int(n)} чел." if n > 0 else "В смене никого нет")
            show = d.copy()
            show["date"] = show["date"].dt.strftime("%d.%m.%Y")
            show.columns = ["Салон","Дата","Вышло","Часов","Смена"]
            st.dataframe(show, use_container_width=True, hide_index=True)

            fig = px.bar(d, x="date", y="people", color="store", labels={"date":"Дата","people":"В смене","store":"Салон"})
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.dataframe(shifts_f, use_container_width=True, hide_index=True)

# -------------------- LOAD DIAGNOSTICS --------------------
with tabs[8]:
    st.subheader("Загрузка и распознавание")
    if not workbooks:
        st.info("Подключите источник слева.")
    else:
        rows = [
            ["Текущий день", len(current_sales)],
            ["История факта", len(daily_history)],
            ["Месячные планы", len(monthly_plans)],
            ["Сотрудники", len(employees)],
            ["Планы на 6 дней", len(six_day)],
            ["Смены", len(shifts)],
            ["Нераспознанные листы", len(unrecognized)],
        ]
        st.dataframe(pd.DataFrame(rows, columns=["Раздел","Строк"]), use_container_width=True, hide_index=True)

        if load_messages:
            st.success(" · ".join(load_messages))

        if unrecognized:
            st.warning("Часть листов не используется в расчётах — это нормально для служебных и оформительских вкладок.")
            for name, raw in unrecognized[:12]:
                with st.expander(name):
                    st.write(f"Размер: {raw.shape[0]} × {raw.shape[1]}")
                    st.dataframe(raw.head(15), use_container_width=True)
