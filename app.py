#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中建·泊悦府 销售情况看板
Streamlit 应用主程序

启动方式：
  streamlit run app.py
"""

import os
import glob

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────── 页面配置 ───────────────────────────

st.set_page_config(
    page_title="中建·泊悦府 销售看板",
    page_icon="🏠",
    layout="wide",
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

# 状态对应颜色
STATUS_COLORS = {
    "可售": "#4CAF50",
    "已售": "#F44336",
    "不可售": "#9E9E9E",
    "未知": "#FF9800",
}


# ─────────────────────────── 数据加载 ───────────────────────────


@st.cache_data
def load_csv(filepath: str) -> pd.DataFrame:
    """读取 CSV 并返回 DataFrame"""
    df = pd.read_csv(filepath, dtype=str)
    # 字符串列空值统一填充，避免后续排序/筛选报错
    str_cols = ["预售证号", "楼栋", "单元", "楼层", "门牌号", "户型", "面积", "预售申报价", "销售状态"]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].fillna("未知")
    # 将面积转为数值（去掉 m² 后缀，空值安全处理）
    if "面积" in df.columns:
        df["面积_数值"] = pd.to_numeric(df["面积"].str.replace(r"[^\d.]", "", regex=True), errors="coerce")
    # 将价格转为数值（去掉 元/㎡ 后缀，空值安全处理）
    if "预售申报价" in df.columns:
        df["价格_数值"] = pd.to_numeric(df["预售申报价"].str.replace(r"[^\d.]", "", regex=True), errors="coerce")
    return df


def get_csv_files() -> list:
    """获取 data/ 目录下所有 CSV 文件，按修改时间倒序"""
    pattern = os.path.join(DATA_DIR, "*.csv")
    files = glob.glob(pattern)
    files.sort(key=os.path.getmtime, reverse=True)
    return files


# ─────────────────────────── 侧边栏 ───────────────────────────


def render_sidebar(df: pd.DataFrame) -> pd.DataFrame:
    """渲染侧边栏筛选器，返回筛选后的 DataFrame"""
    st.sidebar.header("🔍 数据筛选")

    # 楼栋筛选
    buildings = sorted(df["楼栋"].unique(), key=lambda x: int("".join(filter(str.isdigit, x)) or 0))
    selected_buildings = st.sidebar.multiselect("楼栋", buildings, default=buildings)

    # 根据楼栋筛选后的数据来确定可用单元
    filtered = df[df["楼栋"].isin(selected_buildings)]

    # 单元筛选
    units = sorted(filtered["单元"].unique(), key=lambda x: int("".join(filter(str.isdigit, x)) or 0))
    selected_units = st.sidebar.multiselect("单元", units, default=units)

    # 销售状态筛选
    statuses = sorted(df["销售状态"].unique())
    selected_statuses = st.sidebar.multiselect("销售状态", statuses, default=statuses)

    # 户型筛选（fillna 避免 NaN 与 str 排序报错）
    house_types = sorted(df["户型"].fillna("未知").unique())
    selected_types = st.sidebar.multiselect("户型", house_types, default=house_types)

    # 面积范围筛选
    if "面积_数值" in df.columns and not df["面积_数值"].isna().all():
        min_area = float(df["面积_数值"].min())
        max_area = float(df["面积_数值"].max())
        area_range = st.sidebar.slider(
            "面积范围 (m²)",
            min_value=min_area,
            max_value=max_area,
            value=(min_area, max_area),
            step=1.0,
        )
    else:
        area_range = None

    # 应用筛选
    mask = (
        df["楼栋"].isin(selected_buildings)
        & df["单元"].isin(selected_units)
        & df["销售状态"].isin(selected_statuses)
        & df["户型"].isin(selected_types)
    )
    if area_range is not None:
        mask = mask & df["面积_数值"].between(area_range[0], area_range[1])

    return df[mask]


# ─────────────────────────── 概览卡片 ───────────────────────────


def render_overview(df: pd.DataFrame, filtered_df: pd.DataFrame):
    """渲染顶部概览指标卡片"""
    st.markdown("---")
    total = len(filtered_df)
    sold = len(filtered_df[filtered_df["销售状态"] == "已售"])
    available = len(filtered_df[filtered_df["销售状态"] == "可售"])
    unavailable = len(filtered_df[filtered_df["销售状态"] == "不可售"])
    unknown = total - sold - available - unavailable

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("🏠 总房屋数", f"{total} 间")
    col2.metric("✅ 可售", f"{available} 间", delta=f"{available/total*100:.1f}%" if total else "0%")
    col3.metric("🔴 已售", f"{sold} 间", delta=f"{sold/total*100:.1f}%" if total else "0%")
    col4.metric("⬜ 不可售", f"{unavailable} 间")
    if unknown > 0:
        col5.metric("❓ 未知", f"{unknown} 间")
    else:
        # 显示已售率
        sold_rate = sold / (sold + available) * 100 if (sold + available) > 0 else 0
        col5.metric("📊 去化率", f"{sold_rate:.1f}%")


# ─────────────────────────── 图表区域 ───────────────────────────


def render_charts(filtered_df: pd.DataFrame):
    """渲染统计图表"""
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        st.subheader("各楼栋销售状态分布")
        if filtered_df.empty:
            st.info("暂无数据")
            return

        # 按楼栋和销售状态统计
        building_status = (
            filtered_df.groupby(["楼栋", "销售状态"])
            .size()
            .reset_index(name="数量")
        )
        # 楼栋排序
        building_order = sorted(
            building_status["楼栋"].unique(),
            key=lambda x: int("".join(filter(str.isdigit, x)) or 0),
        )
        fig_bar = px.bar(
            building_status,
            x="楼栋",
            y="数量",
            color="销售状态",
            color_discrete_map=STATUS_COLORS,
            category_orders={"楼栋": building_order},
            barmode="stack",
        )
        fig_bar.update_layout(
            xaxis_title="",
            yaxis_title="房屋数量",
            legend_title="销售状态",
            height=420,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with chart_col2:
        st.subheader("全盘销售状态占比")
        status_count = filtered_df["销售状态"].value_counts().reset_index()
        status_count.columns = ["销售状态", "数量"]
        fig_pie = px.pie(
            status_count,
            values="数量",
            names="销售状态",
            color="销售状态",
            color_discrete_map=STATUS_COLORS,
            hole=0.4,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label+value")
        fig_pie.update_layout(height=420)
        st.plotly_chart(fig_pie, use_container_width=True)


# ─────────────────────────── 销控表视图 ───────────────────────────


def render_sales_control_table(filtered_df: pd.DataFrame):
    """渲染类似售楼处销控表的楼栋-楼层矩阵视图"""
    st.subheader("🏢 销控表视图")
    if filtered_df.empty:
        st.info("暂无数据")
        return

    # 选择查看的楼栋
    buildings = sorted(
        filtered_df["楼栋"].unique(),
        key=lambda x: int("".join(filter(str.isdigit, x)) or 0),
    )
    selected_building = st.selectbox("选择楼栋查看销控表", buildings)
    b_df = filtered_df[filtered_df["楼栋"] == selected_building]

    # 获取所有单元和楼层
    unit_order = sorted(b_df["单元"].unique(), key=lambda x: int("".join(filter(str.isdigit, x)) or 0))
    floor_order = sorted(b_df["楼层"].unique(), key=lambda x: int("".join(filter(str.isdigit, x)) or 0), reverse=True)

    # 构建状态映射颜色的 HTML 表格
    # 状态 -> 背景色
    bg_map = {
        "可售": "#C8E6C9",
        "已售": "#FFCDD2",
        "不可售": "#E0E0E0",
        "未知": "#FFE0B2",
    }

    html_parts = [
        '<table style="border-collapse:collapse; width:100%; font-size:13px; text-align:center;">',
        "<tr><th style='border:1px solid #ccc; padding:6px; background:#f5f5f5;'>楼层</th>",
    ]
    for unit in unit_order:
        html_parts.append(f"<th style='border:1px solid #ccc; padding:6px; background:#f5f5f5;'>{unit}</th>")
    html_parts.append("</tr>")

    for floor in floor_order:
        html_parts.append(f"<tr><td style='border:1px solid #ccc; padding:6px; font-weight:bold;'>{floor}</td>")
        for unit in unit_order:
            mask = (b_df["楼层"] == floor) & (b_df["单元"] == unit)
            rooms = b_df[mask]
            if rooms.empty:
                html_parts.append("<td style='border:1px solid #ccc; padding:4px;'>—</td>")
            else:
                cell_items = []
                for _, r in rooms.iterrows():
                    bg = bg_map.get(r["销售状态"], "#fff")
                    cell_items.append(
                        f"<div style='background:{bg}; border-radius:4px; padding:2px 4px; margin:1px;'>"
                        f"{r['门牌号']}<br><small>{r['销售状态']}</small></div>"
                    )
                html_parts.append(f"<td style='border:1px solid #ccc; padding:2px;'>{''.join(cell_items)}</td>")
        html_parts.append("</tr>")

    html_parts.append("</table>")

    # 图例
    legend_html = "<div style='margin:10px 0; font-size:13px;'>"
    for status, color in bg_map.items():
        legend_html += f"<span style='display:inline-block; width:16px; height:16px; background:{color}; border:1px solid #ccc; border-radius:3px; vertical-align:middle; margin-right:4px;'></span>{status}&emsp;"
    legend_html += "</div>"

    st.markdown(legend_html, unsafe_allow_html=True)
    st.markdown("".join(html_parts), unsafe_allow_html=True)


# ─────────────────────────── 数据明细 ───────────────────────────


def render_data_table(filtered_df: pd.DataFrame):
    """渲染数据明细表格"""
    st.subheader("📋 数据明细")
    if filtered_df.empty:
        st.info("暂无数据")
        return

    # 展示列（去掉辅助列）
    display_cols = ["预售证号", "楼栋", "单元", "楼层", "门牌号", "户型", "面积", "预售申报价", "销售状态"]
    display_df = filtered_df[display_cols].reset_index(drop=True)

    st.dataframe(
        display_df,
        use_container_width=True,
        height=500,
        column_config={
            "销售状态": st.column_config.TextColumn("销售状态", width="small"),
            "面积": st.column_config.TextColumn("面积", width="small"),
            "预售申报价": st.column_config.TextColumn("预售申报价", width="medium"),
        },
    )

    # 下载按钮
    csv_data = display_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="📥 下载当前筛选结果 (CSV)",
        data=csv_data,
        file_name="中建泊悦府_筛选结果.csv",
        mime="text/csv",
    )


# ─────────────────────────── 主程序 ───────────────────────────


def main():
    st.title("🏠 中建·泊悦府 销售情况看板")

    # 获取数据文件列表
    csv_files = get_csv_files()
    if not csv_files:
        st.error("⚠️ 暂无数据文件，请先运行 `python scraper.py` 抓取数据。")
        st.code("cd boyuefu-dashboard && python scraper.py", language="bash")
        return

    # 数据文件选择
    file_names = [os.path.basename(f) for f in csv_files]
    selected_file = st.selectbox(
        "📂 选择数据文件（默认最新）",
        options=file_names,
        index=0,
    )
    selected_path = csv_files[file_names.index(selected_file)]

    # 加载数据
    df = load_csv(selected_path)
    st.caption(f"数据来源：`{selected_file}`　|　共 {len(df)} 条记录　|　抓取时间：{df['抓取时间'].iloc[0] if not df.empty else '未知'}")

    # 侧边栏筛选
    filtered_df = render_sidebar(df)

    # 概览卡片
    render_overview(df, filtered_df)

    # 图表区域
    render_charts(filtered_df)

    # 销控表视图
    render_sales_control_table(filtered_df)

    # 数据明细表格
    st.markdown("---")
    render_data_table(filtered_df)


if __name__ == "__main__":
    main()
