# 财经买方研究日报 自动推送（GitHub Actions 版）

把「联网搜索 → 买方框架研究 → 生成报告 → 推送微信」搬到 GitHub 云端定时跑，**不需要你的电脑开机**。

## 推送内容
- **工作日 09:00（北京）晨报**：隔夜美股 + 盘前要点
- **工作日 21:00（北京）晚报**：A股收盘 + 美股盘前（完整买方研究框架）
- **周日 21:00（北京）周报**：本周复盘 + 财报日历
- 周六不推送

报告由 **Tavily 联网搜索 + Google Gemini** 按买方投资研究框架生成（降噪、持仓影响、风险/机会/操作判断、财报日历），再以 Markdown 推送至微信（PushPlus）。

**为什么用 Gemini**：你的报告 prompt 很长 + 搜索素材多 + 要生成 1000–2500 字，单次请求很大。硅基流动的免费额度有**单次上限**，长报告会返回 `402 Payment Required`；GitHub Models 的免费层限输入 8K/输出 4K，且其推理端点 `models.inference.ai.azure.com` 已失效（DNS 无法解析），已弃用。Gemini 免费版 **100 万 token 上下文**、GitHub Actions 美国服务器可直连、无需付费，是本项目当前主方案。

## 部署步骤（一次性）
1. 在 GitHub 新建一个仓库（如 `finance-push`），把本目录（`main.py`、`PROMPT_EVENING.md`、`.github/workflows/daily.yml`）推上去。
2. 仓库 → Settings → Secrets and variables → Actions → **New repository secret**，添加 3 个：
   - `PUSHPLUS_TOKEN`：你的 PushPlus Token（https://www.pushplus.plus 「我的」→ 个人中心 复制）
   - `TAVILY_API_KEY`：Tavily 搜索 API Key（https://tavily.com 注册，免费额度 1000 次/月）
   - `GEMINI_API_KEY`：Google Gemini API Key（https://aistudio.google.com/apikey 免费生成，无需付费）
3. 打开仓库 → Actions 页，确认 **财经推送** workflow 已启用。
4. 首次建议手动跑一次验证：Actions → 该 workflow → Run workflow → 选 `evening`（绕开周六跳过），看微信是否收到。

## 定时说明
GitHub Actions 的 cron 使用 **UTC**：
- `0 1 * * 1-5` → 北京 09:00（周一~周五 晨报）
- `0 13 * * 1-5` → 北京 21:00（周一~周五 晚报）
- `0 13 * * 0` → 北京 21:00（周日 周报）

脚本内部也按北京时间判断（周六自动跳过、周日走周报、工作日按上午/晚间区分）。

## 本地调试
```bash
# 需要三个环境变量
export TAVILY_API_KEY=xxx
export GEMINI_API_KEY=xxx
export PUSHPLUS_TOKEN=xxx

python3 main.py auto
python3 main.py morning
python3 main.py evening
python3 main.py weekly
```

## 注意事项
- 免费额度：GitHub Actions 每月 2000 分钟；Tavily 免费 1000 次/月（每日约 16 次搜索）；Gemini 免费档（约 15 次/分钟，每天推 2 次足够），1M token 上下文。
- 切换模型：改 `main.py` 里 `call_gemini()` 的 `model` 参数（如 `gemini-2.5-flash`）；或设 `LLM_PROVIDER=siliconflow` 走 DeepSeek-V3.2（需充值，否则长报告 402）。
- 买方研究框架（含你的持仓、筛选规则、10 段输出结构）保存在 `PROMPT_EVENING.md`，可随时修改。
- 财报日期为公开一致预期 / 推算，标注「待官方确认」者以公司公告为准。
