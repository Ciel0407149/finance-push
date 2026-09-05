#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财经早/晚/周报推送脚本（纯数据版，无 LLM）
- 数据源：新浪财经（A股/港股/美股/商品）、Yahoo（韩国标的兜底）
- 推送：PushPlus（微信公众号）
- 运行：GitHub Actions 定时调度，无需个人电脑开机
- 用法：python main.py [morning|evening|weekly|auto]
"""
import os
import sys
import json
import urllib.request
import urllib.parse
import datetime

UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"}

# 新浪代码 -> (中文名, 类别)
SINA = {
    "sh000001": ("上证指数", "A股"),
    "sz399001": ("深证成指", "A股"),
    "sz399006": ("创业板指", "A股"),
    "sh000300": ("沪深300", "A股"),
    "sh600600": ("青岛啤酒", "A股"),
    "sh600438": ("通威股份", "A股"),
    "hkHSI":    ("恒生指数", "港股"),
    "hk03690":  ("美团", "港股"),
    "gb_dji":   ("道琼斯", "美股"),
    "gb_ixic":   ("纳斯达克", "美股"),
    "gb_inx":    ("标普500", "美股"),
    "gb_nvda":   ("英伟达", "美股"),
    "gb_mu":     ("美光", "美股"),
    "gb_goog":   ("谷歌", "美股"),
    "gb_tsla":   ("特斯拉", "美股"),
    "gb_pdd":    ("拼多多", "美股"),
    "hf_GC":     ("黄金", "商品"),
    "hf_CL":     ("WTI原油", "商品"),
}

# 韩国上市标的，Yahoo 兜底（GitHub 美东节点通常可访问）
YAHOO = {"000660.KS": "SK海力士"}

# 持仓：key -> (新浪代码或 None, 名称, 核心逻辑)
PORTFOLIO = [
    ("NVDA",  "gb_nvda", "英伟达",   "AI算力/GPU/数据中心"),
    ("MU",    "gb_mu",   "美光",     "存储HBM"),
    ("SKH",   "000660.KS", "SK海力士", "存储HBM"),
    ("TSLA",  "gb_tsla", "特斯拉",   "EV+FSD+Robotaxi"),
    ("GOOG",  "gb_goog", "谷歌",     "搜索/云/AI"),
    ("PDD",   "gb_pdd",  "拼多多",   "电商/Temu"),
    ("3690",  "hk03690", "美团",     "本地生活/外卖"),
    ("600600","sh600600","青岛啤酒", "消费/高端化"),
    ("300ETF","sh000300","沪深300ETF","A股大盘"),
    ("AU",    "hf_GC",   "黄金",     "避险/央行购金"),
    ("600438","sh600438","通威股份", "光伏硅料"),
]

# 财报日历（近期，标注来源/待确认）
EARNINGS = [
    ("英伟达 NVDA", "2026-08-26 盘后", "预期营收~$91.7B / EPS~$2.07 / 毛利~75%",
     "AI链定调；关注数据中心收入、Blackwell/Rubin、云厂CapEx", "来源:一致预期"),
    ("拼多多 PDD", "2026-08-28(部分源8/31待确认)", "预期营收~$17.1B / EPS~$2.74",
     "关注利润率/Temu/关税；已连两季EPS miss", "来源:一致预期"),
    ("青岛啤酒 600600", "2026-08-27 半年报", "预告未发",
     "关注吨价、毛利率、高端化", "待官方确认"),
    ("通威股份 600438", "2026-08-27 半年报", "预告亏损48-54亿",
     "关注硅料价(3.1万→4.5万)、产能出清、现金流", "业绩预告已发"),
    ("美团 3690", "预计2026-08月底(待确认)", "Q1超预期，核心亏损收窄",
     "关注外卖UE、补贴、京东/阿里竞争", "待官方确认"),
    ("美光 MU", "约2026-09下旬(下次Q4)", "—", "关注DRAM/HBM/毛利率", "推算"),
    ("SK海力士/ASML/谷歌", "约2026-10(Q3)", "—", "关注HBM/订单/云CapEx", "推算"),
    ("特斯拉 TSLA", "约2026-10-21(Q3)", "—", "关注交付/汽车毛利/FSD", "推算"),
]


def parse_sina(code, raw):
    """解析新浪返回的单行。返回 (price, pct) 或 None。"""
    import re
    m = re.search(r'="(.*?)"', raw)
    if not m:
        return None
    p = m.group(1).split(",")
    try:
        if code.startswith("gb_"):
            return float(p[1]), float(p[2])
        if code.startswith("hf_"):
            price = float(p[0]); prev = float(p[5])
            return price, (price - prev) / prev * 100
        if code.startswith("hk"):
            return float(p[2]), float(p[8])
        # sh / sz A股：名称,今开,昨收,现价,...
        price = float(p[3]); prev = float(p[2])
        return price, (price - prev) / prev * 100
    except Exception:
        return None


def parse_yahoo(code):
    try:
        u = f"https://query1.finance.yahoo.com/v8/finance/chart/{code}?interval=1d&range=1d"
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            d = json.loads(r.read())
        res = d["chart"]["result"][0]
        price = res["meta"]["regularMarketPrice"]
        prev = res["meta"]["previousClose"]
        return price, (price - prev) / prev * 100
    except Exception:
        return None


def fetch_all():
    codes = list(SINA.keys())
    url = "https://hq.sinajs.cn/list=" + ",".join(codes)
    out = {}
    try:
        req = urllib.request.Request(url, headers=UA)
        raw = urllib.request.urlopen(req, timeout=20).read().decode("gbk", "ignore")
        for code in codes:
            line = [l for l in raw.split("\n") if f"hq_str_{code}=" in l]
            if line:
                out[code] = parse_sina(code, line[0])
    except Exception as e:
        out["__fetch_err__"] = str(e)
    for code, name in YAHOO.items():
        out[code] = parse_yahoo(code)
    return out


def arrow(pct):
    # 中国习惯：涨=红，跌=绿
    return "🔴" if pct >= 0 else "🟢"


def fmt_val(val):
    if val is None:
        return "实时价暂不可得"
    price, pct = val
    return f"{price:.2f}　{arrow(pct)} {abs(pct):.2f}%"


def build_report(mode, data, bj):
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][bj.weekday()]
    tag = {"morning": "晨", "evening": "晚", "weekly": "周报"}[mode]
    date_str = bj.strftime("%Y-%m-%d")

    lead = {
        "morning": "隔夜海外市场与今日盘前要点。",
        "evening": "A股收盘与美股盘前要点。",
        "weekly": "本周复盘与下周红点事项。",
    }[mode]

    lines = []
    lines.append(f"# 📊 投资情报 · {date_str}（{weekday_cn}）{tag}")
    lines.append("")
    lines.append(f"> {lead}")
    lines.append("")
    lines.append("【数据速览】")
    for code, (name, cat) in SINA.items():
        if code in ("sh600600", "sh600438"):  # 个股在持仓里单列
            continue
        lines.append(f"- {name}：{fmt_val(data.get(code))}")
    lines.append("")

    lines.append("【持仓速览】")
    for key, code, name, logic in PORTFOLIO:
        if code in SINA:
            val = data.get(code)
        else:
            val = data.get(code)  # Yahoo
        lines.append(f"- {name}（{logic}）：{fmt_val(val)}")
    lines.append("")

    lines.append("【财报日历 · 未来2-4周】")
    for name, dt, exp, focus, src in EARNINGS:
        lines.append(f"- {name}｜{dt}｜预期：{exp}｜关注：{focus}（{src}）")
    lines.append("")

    if mode == "weekly":
        lines.append("【本周复盘提示】")
        lines.append("- 仅展示数据快照；深度基本面/预期差分析请结合买方框架人工研判。")
        lines.append("- 组合风险：半导体（NVDA/MU/SKH/ASML）权重偏高，关注FOMC与关税两个宏观开关。")
        lines.append("")
        lines.append("【我的投资逻辑审视】")
        lines.append("- 财报前不因单日波动主动加仓；仅在基本面/预期/风险收益比明确时行动。")
        lines.append("")

    lines.append("【风险提示】")
    lines.append("- 本推送为数据速览，不构成投资建议；实时价取自公开行情，以交易所为准。")
    lines.append("- 海力士等海外标的若显示“暂不可得”，多为数据源临时不通，次日重试。")
    return "\n".join(lines)


def push(token, title, content):
    body = urllib.parse.urlencode({
        "token": token,
        "title": title,
        "content": content,
        "template": "markdown",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8", "ignore")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    bj = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=8)
    wd = bj.weekday()
    if mode == "auto":
        if wd == 5:  # 周六
            print("周六，跳过推送")
            return
        mode = "weekly" if wd == 6 else ("morning" if 8 <= bj.hour < 12 else "evening")

    data = fetch_all()
    content = build_report(mode, data, bj)
    token = os.environ.get("PUSHPLUS_TOKEN")
    if not token:
        # 本地调试：打印不推送
        print("PUSHPLUS_TOKEN 未设置，仅打印：\n")
        print(content)
        return
    title = f"📊 投资情报 · {bj.strftime('%Y-%m-%d')}（{['周一','周二','周三','周四','周五','周六','周日'][wd]}）{ {'morning':'晨','evening':'晚','weekly':'周报'}[mode] }"
    resp = push(token, title, content)
    print("PushPlus 返回:", resp)


if __name__ == "__main__":
    main()
