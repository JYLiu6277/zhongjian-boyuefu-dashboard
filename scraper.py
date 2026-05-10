#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中建·泊悦府 房屋销售情况抓取脚本（CSV 版）
目标网页：http://www.360fc.cn/xinfang/xf_index.html?id=3060&mode=0

功能：
  1. 从销售页面提取所有楼栋 + 单元信息（含 buildId）
  2. 逐个请求 foorinfo.html，解析每间房屋的销售数据
  3. 输出为 CSV 文件（每行一间房屋）
  4. 可选：通过 Server酱 推送微信通知

用法：
  python scraper.py              # 仅抓取，生成 CSV
  python scraper.py --notify     # 抓取 + 微信推送
"""

import re
import time
import os
import argparse
from datetime import datetime

import requests
import pandas as pd
from bs4 import BeautifulSoup

# ─────────────────────────── 可配置区域 ───────────────────────────
ESTATE_ID = "3060"
ESTATE_NAME = "中建·泊悦府"
BASE_URL = "http://www.360fc.cn"
# 预售证号列表
PERMIT_NOS = "GX2025015,GX2025014,GX2025010,GX2025009,GX2025005,GX2025007"
# 数据输出目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
# 请求间隔（秒）
REQUEST_DELAY = 0.5
# Server酱 SendKey 列表（支持多人推送）
SEND_KEYS = [
    "SCT346705T2dGgrU81uHeTm7uax6axPlcH",
    "SCT346726TZaVghkOeXpWrwZw83KKVlKpy",
]
# ─────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": f"{BASE_URL}/xinfang/xf_index.html?id={ESTATE_ID}&mode=0",
}

STATUS_MAP = {
    "kesou": "可售",
    "yisou": "已售",
    "bukesou": "不可售",
    "buke": "不可售",
}


# ─────────────────────────── 工具函数 ───────────────────────────


def send_wechat_notify(send_keys: list, title: str, content: str):
    """通过 Server酱 向多个 SendKey 推送微信消息"""
    if not send_keys:
        print("  [推送] SEND_KEYS 未配置，跳过微信推送")
        return
    for idx, key in enumerate(send_keys, start=1):
        masked = key[:10] + "****"
        try:
            url = f"https://sctapi.ftqq.com/{key}.send"
            resp = requests.post(url, data={"title": title, "desp": content}, timeout=10)
            result = resp.json()
            if result.get("code") == 0:
                print(f"✅ 推送成功 [{idx}/{len(send_keys)}] {masked}")
            else:
                print(f"❌ 推送失败 [{idx}/{len(send_keys)}] {masked}：{result.get('message', result)}")
        except Exception as e:
            print(f"❌ 推送异常 [{idx}/{len(send_keys)}] {masked}：{e}")


def fetch_html(url: str, retries: int = 3) -> str:
    """GET 请求，带重试"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:
            if attempt < retries - 1:
                print(f"  [重试 {attempt+1}] {url} -> {e}")
                time.sleep(2)
            else:
                print(f"  [失败] {url} -> {e}")
                return ""


# ─────────────────────────── 解析逻辑 ───────────────────────────


def parse_building_units(permit_nos: str) -> list:
    """
    从 xf_sale.html 的左侧导航菜单解析所有楼栋和单元信息。
    返回: [{permitNo, louDong, buildId, units: [{permitNo, louDong, unitId, buildId}]}]
    """
    first_permit = permit_nos.split(",")[0].strip()
    url = (
        f"{BASE_URL}/xinfang/xf_sale.html"
        f"?mode=1&permitNos={permit_nos}&rightcertnum={first_permit}&sitbuildnum=1&housenum=1"
    )
    print(f"[Step 1] 获取楼栋/单元列表: {url}")
    html = fetch_html(url)
    if not html:
        raise RuntimeError("无法获取楼栋/单元列表页面")

    soup = BeautifulSoup(html, "html.parser")
    nav_items = soup.select(".navMenu > li")
    buildings = []

    pattern = re.compile(r"getrooms\('([^']+)','([^']+)','([^']+)','([^']*)'\)")

    for li in nav_items:
        main_link = li.select_one("a.afinve")
        if not main_link:
            continue
        href = main_link.get("href", "")
        m = pattern.search(href)
        if not m:
            continue

        permit_no = m.group(1)
        lou_dong = m.group(2).strip()
        build_id = m.group(4)

        units = []
        for unit_a in li.select(".sub-menu li a"):
            um = pattern.search(unit_a.get("href", ""))
            if um:
                units.append({
                    "permitNo": um.group(1),
                    "louDong": um.group(2).strip(),
                    "unitId": um.group(3),
                    "buildId": um.group(4),
                })

        buildings.append({
            "permitNo": permit_no,
            "louDong": lou_dong,
            "buildId": build_id,
            "units": units,
        })

    print(f"  → 共找到 {len(buildings)} 栋楼，单元总数 {sum(len(b['units']) for b in buildings)}")
    return buildings


def parse_unit_rooms(permit_no: str, lou_dong: str, unit_id: str, build_id: str) -> list:
    """
    从 foorinfo.html 解析某单元所有房屋信息。
    返回: [{floor, room_no, house_type, area, price, status}]
    """
    url = (
        f"{BASE_URL}/xinfang/foorinfo.html"
        f"?permitNo={permit_no}&loudong={lou_dong}&unitId={unit_id}&buildid={build_id}"
    )
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    rooms = []
    current_floor = ""

    for ul in soup.select("#navigation_horiz ul"):
        lis = ul.find_all("li", recursive=False)
        if not lis:
            continue

        floor_li = lis[0]
        floor_text = floor_li.get_text(strip=True)
        if floor_text:
            current_floor = floor_text

        for room_li in lis[1:]:
            cls = " ".join(room_li.get("class", []))
            status = "未知"
            for key, val in STATUS_MAP.items():
                if key in cls:
                    status = val
                    break

            dropdown = room_li.select_one(".dropdown")
            if not dropdown:
                continue

            data = {}
            for p in dropdown.find_all("p"):
                text = p.get_text(strip=True)
                if text.startswith("门牌号："):
                    data["room_no"] = text.replace("门牌号：", "").strip()
                elif text.startswith("户"):
                    data["house_type"] = re.sub(r"^户\s+型[：:]\s*", "", text).strip()
                elif text.startswith("房屋面积："):
                    data["area"] = text.replace("房屋面积：", "").strip()
                elif text.startswith("预售申报价："):
                    data["price"] = text.replace("预售申报价：", "").strip()

            if data:
                rooms.append({
                    "floor": current_floor,
                    "room_no": data.get("room_no", ""),
                    "house_type": data.get("house_type", ""),
                    "area": data.get("area", ""),
                    "price": data.get("price", ""),
                    "status": status,
                })

    return rooms


# ─────────────────────────── 主流程 ───────────────────────────


def scrape() -> tuple:
    """
    执行完整抓取流程。
    返回: (DataFrame, csv_path, timestamp)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 60)
    print(f"  {ESTATE_NAME} 房屋销售情况抓取")
    print("=" * 60)

    # Step 1: 获取楼栋和单元列表
    buildings = parse_building_units(PERMIT_NOS)

    # Step 2: 逐单元抓取房屋数据
    all_rows = []
    for b_idx, building in enumerate(buildings, start=1):
        lou_dong = building["louDong"]
        print(
            f"\n[{b_idx}/{len(buildings)}] {lou_dong}号楼 ({building['permitNo']}) "
            f"— {len(building['units'])} 个单元"
        )

        for unit in building["units"]:
            unit_id = unit["unitId"]
            build_id = unit["buildId"]
            permit_no = unit["permitNo"]
            print(f"  → 第{unit_id}单元 (buildId={build_id})...", end="", flush=True)
            rooms = parse_unit_rooms(permit_no, lou_dong, unit_id, build_id)
            for r in rooms:
                all_rows.append({
                    "抓取时间": timestamp,
                    "预售证号": permit_no,
                    "楼栋": f"{lou_dong}号楼",
                    "单元": f"第{unit_id}单元",
                    "楼层": r["floor"],
                    "门牌号": r["room_no"],
                    "户型": r["house_type"],
                    "面积": r["area"],
                    "预售申报价": r["price"],
                    "销售状态": r["status"],
                })
            print(f" {len(rooms)} 间")
            time.sleep(REQUEST_DELAY)

    print(f"\n共抓取房屋 {len(all_rows)} 间")

    # Step 3: 构建 DataFrame 并排序
    df = pd.DataFrame(all_rows)
    if not df.empty:
        # 提取楼栋数字用于排序
        df["_楼栋序号"] = df["楼栋"].str.extract(r"(\d+)").astype(int)
        df["_单元序号"] = df["单元"].str.extract(r"(\d+)").astype(int)
        df = df.sort_values(["_楼栋序号", "_单元序号", "楼层"]).drop(
            columns=["_楼栋序号", "_单元序号"]
        ).reset_index(drop=True)

    # Step 4: 保存 CSV
    os.makedirs(DATA_DIR, exist_ok=True)
    csv_filename = f"中建泊悦府_{timestamp}.csv"
    csv_path = os.path.join(DATA_DIR, csv_filename)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ CSV 已保存：{csv_path}")

    return df, csv_path, timestamp


def build_notify_content(df: pd.DataFrame, csv_path: str, timestamp: str) -> str:
    """根据 DataFrame 构建微信推送的 Markdown 内容"""
    total = len(df)
    status_count = df["销售状态"].value_counts().to_dict()
    status_lines = "\n".join(f"- **{s}**：{c} 间" for s, c in sorted(status_count.items()))

    # 逐栋楼构建明细表格
    building_sections = []
    for lou_dong, b_df in df.groupby("楼栋", sort=False):
        b_status = b_df["销售状态"].value_counts().to_dict()
        b_stat_str = "　".join(f"{s} {c} 间" for s, c in sorted(b_status.items()))

        unit_ids = b_df["单元"].unique().tolist()
        floors = b_df["楼层"].unique().tolist()

        header = "| 楼层 | " + " | ".join(unit_ids) + " |"
        sep = "| :--: | " + " | ".join(":--:" for _ in unit_ids) + " |"
        rows = []
        for floor in floors:
            cells = []
            for unit in unit_ids:
                mask = (b_df["楼层"] == floor) & (b_df["单元"] == unit)
                matched = b_df[mask]
                if matched.empty:
                    cells.append("—")
                else:
                    entries = [f"{r['门牌号']}({r['销售状态']})" for _, r in matched.iterrows()]
                    cells.append("<br>".join(entries))
            rows.append("| " + floor + " | " + " | ".join(cells) + " |")

        table = "\n".join([header, sep, *rows])
        section = f"### {lou_dong}　{b_stat_str}\n\n{table}"
        building_sections.append(section)

    content = "\n\n".join([
        "\n".join([
            f"**楼盘**：{ESTATE_NAME}",
            f"**抓取时间**：{timestamp}",
            f"**房屋总数**：{total} 间",
            f"**结果文件**：`{os.path.basename(csv_path)}`",
            "",
            "**全盘销售状态汇总**",
            status_lines,
        ]),
        *building_sections,
    ])
    return content


def main():
    parser = argparse.ArgumentParser(description=f"{ESTATE_NAME} 房屋销售情况抓取")
    parser.add_argument("--notify", action="store_true", help="抓取后通过 Server酱 推送微信通知")
    args = parser.parse_args()

    df, csv_path, timestamp = scrape()

    if df.empty:
        print("⚠️ 未抓取到任何数据，跳过后续步骤")
        return

    # 打印统计
    print("\n─── 销售状态统计 ───")
    for status, cnt in sorted(df["销售状态"].value_counts().items()):
        print(f"  {status}: {cnt} 间")

    # 微信推送
    if args.notify:
        print("\n─── 微信推送 ───")
        content = build_notify_content(df, csv_path, timestamp)
        send_wechat_notify(SEND_KEYS, f"{ESTATE_NAME} 房屋销售情况更新", content)
    else:
        print("\n（未启用微信推送，如需推送请添加 --notify 参数）")


if __name__ == "__main__":
    main()
