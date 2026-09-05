# 财经早/晚/周报 自动推送（GitHub Actions 版）

把「抓取财经行情 → 生成简报 → 推送微信」搬到 GitHub 云端定时跑，**不需要你的电脑开机**。

## 推送内容
- **工作日 09:00（北京）晨报**：隔夜美股 + 盘前要点
- **工作日 21:00（北京）晚报**：A股收盘 + 美股盘前
- **周日 21:00（北京）周报**：本周复盘 + 财报日历
- 周六不推送

覆盖：A股（上证/深证/创业板/沪深300）、港股（恒生/美团）、美股（道指/纳指/标普/NVDA/MU/GOOG/TSLA/ 拼多多）、商品（黄金/WTI）、持仓速览、未来 2–4 周财报日历。

行情数据源：新浪财经（A股/港股/美股/商品）、Yahoo（韩国标的兜底）。**纯数据版，不含 LLM 推理**，稳定免费。

## 部署步骤（一次性）
1. 在 GitHub 新建一个仓库（如 `finance-push`），把本目录（`main.py`、`.github/workflows/daily.yml`）推上去。
2. 仓库 → Settings → Secrets and variables → Actions → New repository secret：
   - Name：`PUSHPLUS_TOKEN`
   - Value：你的 PushPlus Token（从 https://www.pushplus.plus 「我的」→ 个人中心 复制）
3. 打开仓库 → Actions 页，确认 workflows 已启用（默认启用）。
4. 首次建议手动跑一次：Actions → 该 workflow → Run workflow → 选 `auto`，验证微信收到。

## 定时说明
GitHub Actions 的 cron 使用 **UTC**：
- `0 1 * * 1-5` → 北京 09:00（周一~周五 晨报）
- `0 13 * * 1-5` → 北京 21:00（周一~周五 晚报）
- `0 13 * * 0` → 北京 21:00（周日 周报）

脚本内部也按北京时间判断（周六自动跳过、周日走周报、工作日按上午/晚间区分），因此即使手动触发也安全。

## 本地调试
```bash
# 只看不发送（不需要 token）
python3 main.py auto

# 指定模式
python3 main.py morning
python3 main.py evening
python3 main.py weekly

# 真实发送
PUSHPLUS_TOKEN=你的token python3 main.py auto
```

## 注意事项
- 免费额度：GitHub Actions 每月 2000 分钟，本任务每次约 1–2 分钟，足够。
- 实时价以交易所为准；个别海外标的（如 SK 海力士）偶发数据源不通会显示「暂不可得」，次日自动重试。
- 如需「利好/利空推理 + 深度分析」，可在 `main.py` 中接入 LLM API（设置 `OPENAI_API_KEY` 等），默认未启用。
- 财报日期为公开一致预期 / 推算，标注「待官方确认」者以公司公告为准。
