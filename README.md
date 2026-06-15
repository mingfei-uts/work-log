<div align="center">

# 📋 Work Log

**一个纯本地、注重隐私、带 AI 自动总结的每日工作日志。**
任务管理 · 时间追踪 · Markdown 笔记 · AI 总结 · 周报 · Claude Code 会话导入

宋体标题、暖纸配色、朱砂点睛 —— 像一本电子手帐，而不是又一个 SaaS 后台。

</div>

---

## ✨ 特点

- **🔒 纯本地** —— 数据存在你自己电脑的一个 JSON 文件里，不上传任何服务器。AI 总结也只把当天数据发给你自己配置的模型 API。
- **📝 自然语言录入任务** —— 直接打 `修复登录bug 2h ✓ 后端`，自动解析出任务名、时长、完成状态、项目。
- **⏱ 时间追踪** —— 每个任务一个计时点，点一下开始/停止，同时只跑一个。
- **🤖 AI 自动总结** —— 综合「任务 + Git 提交/diff + Claude Code 对话」生成一份要点总结，每天定时自动刷新（可手动触发）。
- **📊 周报** —— 一键（或每周五自动）按项目汇总，生成结构化周报。
- **📥 Claude Code 集成** —— 自动从 Claude Code 对话记录提取「今天做了什么」并建成任务，幂等去重不重复。
- **🗂 项目维度** —— 任务按项目归类，侧栏一键筛选，周报按项目统计工时。
- **🧾 Markdown 渲染** —— 笔记/总结/周报前端直接渲染成排版，支持预览/编辑切换。
- **📚 HTML 空间** —— 可选集成 [htmlspace](https://github.com/mingfei-uts/htmlspace)，在「空间」标签收藏任意 HTML 页面。
- **⌨️ 键盘友好** —— `⌘S` 保存、`⌘I` 生成总结、`⌘←/→` 切换日期、`⌘1/2` 切换视图。

---

## 🚀 快速开始

### 1. 环境

只需 **Python 3.8+** 和一个**现代浏览器**（Chrome / Edge / Safari）。无需 pip 安装任何依赖（纯标准库）。

### 2. 获取代码

```bash
git clone https://github.com/mingfei-uts/work-log.git
cd work-log
```

### 3. 配置 AI（可选但推荐）

```bash
cp .work-log.env.example .work-log.env
```

编辑 `.work-log.env`，填入你的 API key。推荐 **DeepSeek**（中文好、便宜、注册送额度）：

> 去 [platform.deepseek.com](https://platform.deepseek.com) → API Keys 创建一个，填进 `DEEPSEEK_API_KEY=`。
> 也支持 OpenAI 或任意兼容 OpenAI 的服务，见 `.work-log.env.example` 里的方案 B。

> 不配 key 也能用 —— 任务、计时、笔记、导出照常，只是 🤖 总结 / 周报 / CC 导入会提示需要 key。

### 4. 启动

```bash
./start-work-log.sh
```

脚本会启动本地服务器并自动打开浏览器。就这样，开始记录。

> 想手动启动：`python3 work-log-server.py` 然后浏览器打开 `daily-work-log.html`（建议用 `python3 -m http.server` 起个静态服务以 http 方式访问，AI 功能更稳定）。

---

## 🧭 用法

### 任务（支持自然语言）

在输入框直接写，回车添加。系统会自动解析：

| 你输入 | 解析结果 |
|---|---|
| `修复登录 bug 2h ✓` | 任务「修复登录 bug」· 已完成 · 2 小时 |
| `跑实验 3h` | 任务「跑实验」· 进行中 · 3 小时 |
| `写周报 30m` | 任务「写周报」· 30 分钟 |

右侧「项目」框可填项目名（带自动补全），任务会打上彩色项目标签。

### 时间追踪

任务右侧的小圆点：点一下开始计时（变陶土红呼吸），再点停止。同一时间只有一个任务在计时。

### 笔记（Markdown）

默认**预览模式**渲染 Markdown，点「编辑」改源码。AI 总结/周报也写进这里。

### AI 总结 / 周报 / CC 导入

顶部三个按钮：

- **🤖 总结** —— 综合今天的任务、Git 提交、Claude Code 对话，生成一份要点总结写入笔记。重复点只刷新同一份，不堆叠。
- **📊 周报** —— 按本周（周一~周五）汇总，分项目 + 关键 commit + 下周建议。
- **📥 CC** —— 从最近的 Claude Code 对话提取任务自动建条目，去重幂等。

### 键盘快捷键

| 键 | 功能 |
|---|---|
| `⌘/Ctrl + S` | 保存 |
| `⌘/Ctrl + I` | 生成 AI 总结 |
| `⌘/Ctrl + E` | 导出当天为 Markdown |
| `⌘/Ctrl + ← / →` | 前一天 / 后一天 |
| `⌘/Ctrl + 1 / 2` | 切换 日志 / 空间 视图 |

---

## ⚙️ 配置项

全部通过 `.work-log.env`（或环境变量）配置，详见 `.work-log.env.example`：

| 变量 | 说明 | 默认 |
|---|---|---|
| `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | AI 总结用的 key | 无（AI 功能禁用） |
| `WORK_LOG_AI_BASE` | API base URL | `https://api.deepseek.com` |
| `WORK_LOG_AI_MODEL` | 模型名 | `deepseek-chat` |
| `WORK_LOG_SCHEDULE` | 每日自动总结时间 HH:MM | `18:00` |
| `WORK_LOG_REPOS_DIR` | 扫描 git 提交的目录 | 脚本所在目录 |
| `WORK_LOG_CC_DIR` | Claude Code 会话目录 | 按 REPOS_DIR 自动推导 |
| `WORK_LOG_PORT` | 服务端口 | `19878` |
| `WORK_LOG_FILE` | 数据文件路径 | 脚本目录/`work-log-data.json` |

---

## 🏗 架构

```
浏览器 (daily-work-log.html)
   │  fetch  ▲ 渲染
   ▼         │
work-log-server.py  ── localhost:19878
   │  • 任务/笔记/工具的读写 (原子写, 多 tab 安全)
   │  • 扫描 git log / diff
   │  • 调 LLM 生成总结/周报
   │  • 定时调度 (每天 18:00)
   ▼
work-log-data.json   ← 唯一数据源, 你的本地文件

work-log-cli.py      ← 命令行入口 (today / summary / stats / gitlog ...)
```

数据模型（`work-log-data.json`）：

```jsonc
{
  "log": {
    "2026-06-15": {
      "tasks": [{ "text": "...", "done": true, "seconds": 7200, "project": "..." }],
      "notes": "Markdown 文本, 含 AI 总结块"
    }
  },
  "tools": []
}
```

---

## 🔌 Claude Code 集成（可选）

让每次 Claude Code 对话结束后自动把工作内容导入日志。在 `~/.claude/settings.json` 加一个 Stop hook：

```json
{
  "hooks": {
    "Stop": [{ "matcher": "", "hooks": [
      { "type": "command", "command": "curl -s -X POST http://127.0.0.1:19878/cc-import -H 'Content-Type: application/json' -d '{\"limit\":3}' >/dev/null 2>&1 || true" }
    ]}]
  }
}
```

服务器会读取 `~/.claude/projects/<你的项目路径>` 下的会话记录（可用 `WORK_LOG_CC_DIR` 覆盖）。

---

## 📚 HTML 空间集成（可选）

「空间」标签内嵌 [htmlspace](https://github.com/mingfei-uts/htmlspace) —— 把任意 HTML 页面收藏成永不腐烂的单文件。若未安装，该标签会提示如何启动；不影响日志功能。

---

## 🔐 隐私

- 所有数据存在本地 `work-log-data.json`，**不联网、不上传**。
- 仅当你主动点「总结/周报」或开启定时，才会把**当天的任务/笔记/Git 摘要**发送给**你自己配置的** AI API。不配 key 则完全离线。

---

## 🎨 自定义

- **配色 / 字体**：改 `daily-work-log.html` 顶部 `:root` 里的 CSS 变量（`--paper` 纸色、`--seal` 印章红、`--serif` 标题字体…）。
- **总结频率**：改 `.work-log.env` 的 `WORK_LOG_SCHEDULE`。
- **总结风格**：改 `work-log-server.py` 里 `generate_ai_summary` 的 prompt。

---

## 📄 License

**PolyForm Noncommercial 1.0.0** — 见 [LICENSE](LICENSE)。
