import io
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Retail Sales Dashboard", page_icon="📊", layout="wide")

ALIASES = {
    "employee": ["Сотрудник", "сотрудник", "ФИО"],
    "store": ["Салон", "салон", "ТТ", "Магазин", "Код ТТ"],
    "category": ["Категория ABCD", "Категория", "категория"],
    "position": ["Должность", "должность"],
    "shifts": ["Смены", "смены"],
    "outputs": ["Выходы", "выходы"],
    "store_plan": ["Выручка салона, план", "План салона"],
    "store_fact": ["Выручка салона, факт", "Факт салона"],
    "employee_plan": ["Выручка ОК, план", "План ОК"],
    "employee_fact": ["Выручка ОК, факт", "Факт ОК"],
    "date": ["Дата", "Дата среза", "Дата отчёта"],
}

def first_existing(df, names):
    for n in names:
        if n in df.columns:
            return n
    return None

def money(v):
    return "—" if pd.isna(v) else f"{v:,.0f} ₽".replace(",", " ")

def pct(v):
    return "—" if pd.isna(v) else f"{v:.1%}".replace(".", ",")

def read_file(uploaded):
    data = uploaded.getvalue()
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        for sep in [";", ",", "\t"]:
            try:
                df = pd.read_csv(io.BytesIO(data), sep=sep)
                if len(df.columns) > 1:
                    return df
            except Exception:
                pass
        raise ValueError("Не удалось прочитать CSV.")
    xls = pd.ExcelFile(io.BytesIO(data))
    sheet = "Исходные данные" if "Исходные данные" in xls.sheet_names else xls.sheet_names[0]
    return pd.read_excel(xls, sheet_name=sheet)

def normalize(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    col = {k: first_existing(df, v) for k, v in ALIASES.items()}
    required = ["employee", "store", "employee_plan", "employee_fact"]
    if any(not col[k] for k in required):
        raise ValueError("Нужны поля: Сотрудник, Салон, Выручка ОК план, Выручка ОК факт.")

    out = pd.DataFrame({
        "Сотрудник": df[col["employee"]].fillna("").astype(str).str.strip(),
        "Салон": df[col["store"]].fillna("").astype(str).str.strip(),
        "Категория": df[col["category"]].fillna("").astype(str).str.strip() if col["category"] else "",
        "Должность": df[col["position"]].fillna("").astype(str).str.strip() if col["position"] else "",
        "Смены": pd.to_numeric(df[col["shifts"]], errors="coerce").fillna(0) if col["shifts"] else 0,
        "Выходы": pd.to_numeric(df[col["outputs"]], errors="coerce").fillna(0) if col["outputs"] else 0,
        "План сотрудника": pd.to_numeric(df[col["employee_plan"]], errors="coerce").fillna(0),
        "Факт сотрудника": pd.to_numeric(df[col["employee_fact"]], errors="coerce").fillna(0),
        "План салона": pd.to_numeric(df[col["store_plan"]], errors="coerce").fillna(0) if col["store_plan"] else 0,
        "Факт салона": pd.to_numeric(df[col["store_fact"]], errors="coerce").fillna(0) if col["store_fact"] else 0,
    })
    out = out[(out["Сотрудник"] != "") & (out["Салон"] != "")]
    out["Выполнение сотрудника"] = np.where(out["План сотрудника"] > 0, out["Факт сотрудника"] / out["План сотрудника"], np.nan)
    if col["date"]:
        out["Дата"] = pd.to_datetime(df.loc[out.index, col["date"]], errors="coerce")
    return out

st.title("📊 Retail Sales Dashboard")
st.caption("Салоны • сотрудники • рейтинг • красная зона • динамика")

uploaded = st.sidebar.file_uploader("Загрузить отчёт", type=["xlsx", "xls", "xlsm", "csv"])
st.sidebar.caption("Рабочие данные не хранятся в GitHub — файл загружается только в приложение.")

if not uploaded:
    st.info("Загрузите отчёт сотрудников по продажам.")
    st.stop()

try:
    data = normalize(read_file(uploaded))
except Exception as e:
    st.error(str(e))
    st.stop()

stores = sorted(data["Салон"].unique())
employees = sorted(data["Сотрудник"].unique())
categories = sorted([x for x in data["Категория"].unique() if x])
positions = sorted([x for x in data["Должность"].unique() if x])

f_store = st.sidebar.multiselect("Салон", stores)
f_emp = st.sidebar.multiselect("Сотрудник", employees)
f_cat = st.sidebar.multiselect("Категория", categories)
f_pos = st.sidebar.multiselect("Должность", positions)

f = data.copy()
if f_store: f = f[f["Салон"].isin(f_store)]
if f_emp: f = f[f["Сотрудник"].isin(f_emp)]
if f_cat: f = f[f["Категория"].isin(f_cat)]
if f_pos: f = f[f["Должность"].isin(f_pos)]

emp = f.groupby("Сотрудник", as_index=False).agg(
    Салон=("Салон", lambda s: ", ".join(sorted(set(s.astype(str))))),
    Категория=("Категория", lambda s: ", ".join(sorted(set(x for x in s if x)))),
    Должность=("Должность", lambda s: ", ".join(sorted(set(x for x in s if x)))),
    Выходы=("Выходы", "sum"),
    План=("План сотрудника", "sum"),
    Факт=("Факт сотрудника", "sum"),
)
emp["Выполнение"] = np.where(emp["План"] > 0, emp["Факт"] / emp["План"], np.nan)
emp["Gap"] = emp["Факт"] - emp["План"]
emp["₽/выход"] = np.where(emp["Выходы"] > 0, emp["Факт"] / emp["Выходы"], np.nan)

sal = f.groupby("Салон", as_index=False).agg(
    План=("План салона", "max"),
    Факт=("Факт салона", "max"),
    Сотрудников=("Сотрудник", "nunique")
)
sal["Выполнение"] = np.where(sal["План"] > 0, sal["Факт"] / sal["План"], np.nan)
sal["Gap"] = sal["Факт"] - sal["План"]

tabs = st.tabs(["Главная", "Салоны", "Сотрудники", "Рейтинг", "Красная зона", "Динамика"])

with tabs[0]:
    total_plan = emp["План"].sum()
    total_fact = emp["Факт"].sum()
    perf = total_fact / total_plan if total_plan else np.nan
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Факт", money(total_fact))
    c2.metric("План", money(total_plan))
    c3.metric("Выполнение", pct(perf))
    c4.metric("Красная зона", int((emp["Выполнение"] < 0.8).sum()))

    top = emp.sort_values("Факт", ascending=False).head(10)
    fig = px.bar(top, x="Факт", y="Сотрудник", orientation="h", title="ТОП-10 сотрудников")
    fig.update_layout(yaxis={"categoryorder":"total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with tabs[1]:
    v = sal.sort_values("Выполнение", ascending=False).copy()
    v["План"] = v["План"].map(money)
    v["Факт"] = v["Факт"].map(money)
    v["Выполнение"] = v["Выполнение"].map(pct)
    v["Gap"] = v["Gap"].map(money)
    st.dataframe(v, use_container_width=True, hide_index=True)

with tabs[2]:
    v = emp.sort_values("Факт", ascending=False).copy()
    v["План"] = v["План"].map(money)
    v["Факт"] = v["Факт"].map(money)
    v["Выполнение"] = v["Выполнение"].map(pct)
    v["₽/выход"] = v["₽/выход"].map(money)
    v["Gap"] = v["Gap"].map(money)
    st.dataframe(v, use_container_width=True, hide_index=True)

with tabs[3]:
    metric = st.radio("Рейтинг по", ["Факт", "Выполнение", "₽/выход"], horizontal=True)
    rank = emp.sort_values(metric, ascending=False).reset_index(drop=True)
    rank.insert(0, "Место", range(1, len(rank)+1))
    show = rank[["Место","Сотрудник","Салон","Факт","Выполнение","₽/выход"]].copy()
    show["Факт"] = show["Факт"].map(money)
    show["Выполнение"] = show["Выполнение"].map(pct)
    show["₽/выход"] = show["₽/выход"].map(money)
    st.dataframe(show, use_container_width=True, hide_index=True)

with tabs[4]:
    red = emp[emp["Выполнение"] < 0.8].sort_values("Выполнение").copy()
    if red.empty:
        st.success("Сотрудников ниже 80% нет.")
    else:
        red["План"] = red["План"].map(money)
        red["Факт"] = red["Факт"].map(money)
        red["Выполнение"] = red["Выполнение"].map(pct)
        red["Gap"] = red["Gap"].map(money)
        st.dataframe(red[["Сотрудник","Салон","Должность","План","Факт","Выполнение","Gap"]],
                     use_container_width=True, hide_index=True)

with tabs[5]:
    if "Дата" not in f.columns or f["Дата"].isna().all():
        st.info("Для динамики добавьте в исходник колонку «Дата», «Дата среза» или «Дата отчёта».")
    else:
        dyn = f.dropna(subset=["Дата"]).groupby("Дата", as_index=False).agg(
            Факт=("Факт сотрудника","sum"),
            План=("План сотрудника","sum")
        )
        fig = px.line(dyn, x="Дата", y=["Факт","План"], markers=True)
        st.plotly_chart(fig, use_container_width=True)
