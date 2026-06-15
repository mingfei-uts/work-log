#!/usr/bin/env python3
"""
Work Log Server v2 — 本地 HTTP 数据中枢
=========================================
Features:
  - 多 session 并发数据管理
  - Git diff --stat 深度分析
  - NL 任务解析 (DeepSeek)
  - 每日 AI 总结 + 定时调度
  - 周报自动生成
  - 项目维度统计

启动: python3 work-log-server.py --port 19878 [--schedule 18:00]
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ---- Load .env ----
_ENV_FILE = Path(__file__).resolve().parent / '.work-log.env'
if _ENV_FILE.exists():
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

# ---- Config (portable: 默认基于脚本位置, 环境变量可覆盖) ----
SCRIPT_DIR = Path(__file__).resolve().parent

# 数据文件: 默认放脚本同目录
DATA_FILE = Path(os.environ.get("WORK_LOG_FILE", str(SCRIPT_DIR / "work-log-data.json"))).resolve()
PORT = int(os.environ.get("WORK_LOG_PORT", 19878))

# 扫描 git 提交的目录: 默认脚本所在目录, 可用 WORK_LOG_REPOS_DIR 指向你的项目根目录
RESEARCH_DIR = Path(os.path.expanduser(os.environ.get("WORK_LOG_REPOS_DIR", str(SCRIPT_DIR))))

# Claude Code 会话记录目录: 默认按 RESEARCH_DIR 自动推导 (~/.claude/projects/<路径转-连字符>)
def _default_cc_dir():
    sanitized = str(RESEARCH_DIR).replace('/', '-')
    return os.path.expanduser(f"~/.claude/projects/{sanitized}")
CC_SESSIONS_DIR = Path(os.path.expanduser(os.environ.get("WORK_LOG_CC_DIR", _default_cc_dir())))

# AI config
AI_KEY  = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("WORK_LOG_AI_KEY", "")
AI_BASE = os.environ.get("WORK_LOG_AI_BASE", "https://api.deepseek.com")
AI_MODEL = os.environ.get("WORK_LOG_AI_MODEL", "deepseek-chat")

# ---- Locks ----
file_lock = threading.Lock()


# ============================================================
#  Data I/O (atomic)
# ============================================================
def load_state():
    if not DATA_FILE.exists():
        return {"version": 2, "updatedAt": "", "log": {}, "tools": [], "projects": {}}
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            data.setdefault('projects', {})
            return data
    except:
        return {"version": 2, "updatedAt": "", "log": {}, "tools": [], "projects": {}}

def save_state(data):
    data['updatedAt'] = datetime.now().isoformat()
    data.setdefault('projects', {})
    with file_lock:
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=str(DATA_FILE.parent), prefix='.' + DATA_FILE.name + '.', suffix='.tmp')
            try:
                with os.fdopen(tmp_fd, 'w') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, str(DATA_FILE))
            except:
                os.unlink(tmp_path); raise
        except Exception as e:
            print(f"[server] Write error: {e}", file=sys.stderr); raise


# ============================================================
#  Notes: managed AI blocks (upsert — replace same kind, keep rest)
# ============================================================
import re as _re

# 所有 AI 生成块以 "### 🤖 {kind} (时间)" 标记; 同 kind 覆盖, 其余保留
AI_BLOCK_KINDS = ["AI 总结", "CC 会话总结", "周报", "本周周报", "自动总结"]

def write_ai_block(notes, kind, content):
    """删除 notes 中所有同 kind 的 🤖 块, 再在末尾追加新块。保留用户笔记 + 其他 kind 的块。"""
    notes = notes or ""
    ts = datetime.now().strftime('%H:%M')
    # 匹配 "### 🤖 {kind}..." 到下一个 "### 🤖 " 或文末 (DOTALL)
    pattern = _re.compile(
        r'\n*### 🤖 ' + _re.escape(kind) + r'\b.*?(?=\n### 🤖 |\Z)',
        _re.S
    )
    cleaned = pattern.sub('', notes).rstrip()
    block = f"### 🤖 {kind} ({ts})\n{content}"
    return (cleaned + "\n\n" + block).strip() if cleaned else block


# ============================================================
#  Git operations (enhanced with diff --stat)
# ============================================================
def discover_repos():
    repos = []
    if not RESEARCH_DIR.exists(): return repos
    for d in RESEARCH_DIR.iterdir():
        if d.is_dir() and (d / ".git").exists(): repos.append(str(d))
    for d in RESEARCH_DIR.iterdir():
        if d.is_dir() and not (d / ".git").exists():
            for sd in d.iterdir():
                if sd.is_dir() and (sd / ".git").exists() and str(sd) not in repos:
                    repos.append(str(sd))
    return sorted(repos)

def get_git_log(date_str, repos=None):
    """Get commits for a date. Returns {repo_name: [{hash, msg}, ...]}"""
    if repos is None: repos = discover_repos()
    all_commits = {}
    for repo in repos:
        try:
            result = subprocess.run(
                ['git', '-C', repo, 'log',
                 '--since', f'{date_str} 00:00:00', '--until', f'{date_str} 23:59:59',
                 '--pretty=format:%h %s', '--all', '--no-merges'],
                capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
                if lines: all_commits[os.path.basename(repo)] = lines
        except: pass
    return all_commits

def get_git_diff(date_str, repos=None):
    """Get git diff --stat for a date. Returns {repo_name: diff_text}"""
    if repos is None: repos = discover_repos()
    diffs = {}
    for repo in repos:
        try:
            since = f'{date_str} 00:00:00'
            until = f'{date_str} 23:59:59'
            # Get commits on this date
            hashes = subprocess.run(
                ['git', '-C', repo, 'log', '--since', since, '--until', until,
                 '--pretty=format:%H', '--all', '--no-merges'],
                capture_output=True, text=True, timeout=5)
            hash_list = [h for h in hashes.stdout.strip().split('\n') if h]
            if not hash_list: continue
            # diff between first and last commit of the day
            if len(hash_list) >= 2:
                diff = subprocess.run(
                    ['git', '-C', repo, 'diff', '--stat', f'{hash_list[-1]}~1', hash_list[0]],
                    capture_output=True, text=True, timeout=10)
            else:
                diff = subprocess.run(
                    ['git', '-C', repo, 'diff', '--stat', f'{hash_list[0]}~1', hash_list[0]],
                    capture_output=True, text=True, timeout=10)
            text = diff.stdout.strip()
            if text and len(text) < 3000:
                diffs[os.path.basename(repo)] = text
        except: pass
    return diffs


# ============================================================
#  LLM helper (shared)
# ============================================================
def call_llm(system_prompt, user_prompt, max_tokens=800, temperature=0.5):
    """Call LLM API, return response text or None."""
    if not AI_KEY: return None
    try:
        body = json.dumps({
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temperature, "max_tokens": max_tokens
        }).encode('utf-8')
        base = AI_BASE.rstrip('/')
        if 'deepseek' in base: url = f"{base}/v1/chat/completions"
        elif '/v1' in base: url = f"{base}/chat/completions"
        else: url = f"{base}/v1/chat/completions"
        req = urllib.request.Request(url, data=body, headers={
            'Content-Type': 'application/json', 'Authorization': f'Bearer {AI_KEY}'}, method='POST')
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
            return result['choices'][0]['message']['content'].strip()
    except: return None


# ============================================================
#  NL Task Parsing
# ============================================================
def parse_task_nl(text):
    """Parse natural language task description into structured task.
    Falls back to regex if LLM unavailable; uses LLM for complex cases."""
    if not text or not text.strip(): return None

    # Fast path: regex for common patterns
    import re
    text = text.strip()
    result = {"text": text, "done": False, "seconds": 0, "project": None}

    # Detect completion markers
    done_markers = ['✓', '√', 'done', '完成', '搞完', '做完了', '✅']
    for m in done_markers:
        if text.endswith(m) or text.startswith(m):
            result['done'] = True
            text = text.replace(m, '').strip()
            result['text'] = text

    # Detect duration
    dur_patterns = [
        (r'(\d+)\s*h\s*(\d+)\s*m', lambda h,m: int(h)*3600+int(m)*60),
        (r'(\d+)\s*小时?\s*(\d+)\s*分钟?', lambda h,m: int(h)*3600+int(m)*60),
        (r'(\d+)\s*h\b', lambda h: int(h)*3600),
        (r'(\d+)\s*小时?\b', lambda h: int(h)*3600),
        (r'(\d+)\s*m\b', lambda m: int(m)*60),
        (r'(\d+)\s*分钟?\b', lambda m: int(m)*60),
    ]
    for pat, fn in dur_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                result['seconds'] = fn(*m.groups())
            except: pass
            text = re.sub(pat, '', text, flags=re.IGNORECASE).strip()
            result['text'] = text
            break

    # If the text is short and simple after regex, return as-is
    if len(result['text']) < 50 and not any(kw in result['text'] for kw in ['重构','改成','迁移','部署','review']):
        return result

    # LLM path for complex parsing
    if AI_KEY:
        prompt = f"""解析这条工作记录，返回 JSON:
"{text}"
返回格式: {{"text": "清理后的任务描述", "done": true/false, "seconds": 秒数, "project": "项目名或null"}}
只返回 JSON，不要解释。"""
        try:
            resp = call_llm("你是任务解析器。只返回 JSON。", prompt, max_tokens=200, temperature=0)
            if resp:
                parsed = json.loads(resp)
                result['text'] = parsed.get('text', result['text'])
                result['done'] = parsed.get('done', result['done'])
                result['seconds'] = parsed.get('seconds', result['seconds'])
                result['project'] = parsed.get('project')
        except: pass

    return result


# ============================================================
#  AI Summary (enhanced with git diff)
# ============================================================
def generate_ai_summary(date_str, save_to_notes=True):
    if not AI_KEY:
        return {"error": "未配置 API key。设置 DEEPSEEK_API_KEY 环境变量"}

    state = load_state()
    day = state.get('log', {}).get(date_str, {})
    tasks = day.get('tasks', [])
    notes = day.get('notes', '')

    # 喂给 LLM 的笔记: 去掉所有 AI 块, 只保留用户手写内容
    clean_notes = notes.split('### 🤖')[0].strip() if '### 🤖' in notes else notes
    done = [t for t in tasks if t.get('done')]
    pending = [t for t in tasks if not t.get('done')]
    total_sec = sum(t.get('seconds', 0) for t in tasks)
    h, m = total_sec // 3600, (total_sec % 3600) // 60

    all_commits = get_git_log(date_str)
    all_diffs = get_git_diff(date_str)

    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        wd = ['一','二','三','四','五','六','日'][d.weekday()]
    except: wd = '?'

    # Build enhanced prompt
    task_lines = []
    for t in done:
        sec = t.get('seconds', 0)
        ts = f' ({sec//3600}h{(sec%3600)//60}m)' if sec > 0 else ''
        proj = f' [{t["project"]}]' if t.get('project') else ''
        task_lines.append(f"  ✓ {t['text']}{proj}{ts}")
    for t in pending:
        sec = t.get('seconds', 0)
        ts = f' ({sec//3600}h{(sec%3600)//60}m)' if sec > 0 else ''
        proj = f' [{t["project"]}]' if t.get('project') else ''
        task_lines.append(f"  ○ {t['text']}{proj}{ts}")

    git_lines = []
    for repo, commits in all_commits.items():
        git_lines.append(f"  📁 {repo}:")
        for c in commits[:8]: git_lines.append(f"     {c}")
        if repo in all_diffs:
            diff_lines = all_diffs[repo].split('\n')[:5]
            for dl in diff_lines: git_lines.append(f"     Δ {dl.strip()}")

    # 综合总结: 把 Claude Code 对话记录也作为输入源 (含技术细节/决策背景)
    cc_text = extract_cc_session_text(limit=3, date_str=date_str) or extract_cc_session_text(limit=2)
    cc_block = cc_text[:2500] if cc_text else "(无对话记录)"

    prompt = f"""你是一个简洁的工作日志助手。综合以下三类数据 — 任务、Git、Claude Code 对话 — 生成一份统一的中文总结 (4-6 条要点)。

日期: {date_str} 星期{wd}
总耗时: {h}小时{m}分钟

【任务】({len(done)}/{len(tasks)} 完成):
{chr(10).join(task_lines) if task_lines else '  (无任务)'}

【Git】({sum(len(v) for v in all_commits.values())} commits):
{chr(10).join(git_lines) if git_lines else '  (无提交)'}

【Claude Code 对话记录】(用于补充技术细节和决策背景):
{cc_block}

【用户笔记】: {clean_notes[:300] if clean_notes else '(无笔记)'}

规则:
- 4-6 条中文要点，每条不超过 2 行
- 融合三类数据: 任务/git 提供"做了什么和量化数据", 对话记录补充"为什么做、技术细节"
- 量化信息优先用任务和 git 的真实数据 (时长、commit、文件名)
- 同一件事不要重复成多条
- 语调: 客观、简洁、不啰嗦, 直接动词开头, 不要用"今天"开头"""

    summary = call_llm("你是工作日志助手。输出只有要点，无问候语客套。", prompt, max_tokens=600)
    if not summary:
        return {"error": "LLM 调用失败"}

    if save_to_notes and summary:
        day['notes'] = write_ai_block(day.get('notes', ''), "AI 总结", summary)
        save_state(state)

    return {"date": date_str, "summary": summary, "saved": save_to_notes, "model": AI_MODEL}


# ============================================================
#  Weekly Report
# ============================================================
def generate_weekly_report(end_date_str=None):
    """Generate a weekly report for Mon-Fri ending on end_date."""
    if not AI_KEY:
        return {"error": "未配置 API key"}

    if end_date_str is None:
        today = datetime.now()
    else:
        today = datetime.strptime(end_date_str, '%Y-%m-%d')

    # Find Monday
    monday = today - timedelta(days=today.weekday())
    week_dates = [(monday + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(5)]

    state = load_state()
    log = state.get('log', {})

    # Collect week data
    week_data = []
    total_sec = 0; total_tasks = 0; total_done = 0
    project_hours = {}
    all_git = {}

    for ds in week_dates:
        day = log.get(ds, {})
        tasks = day.get('tasks', [])
        if not tasks and not day.get('notes', '').strip(): continue
        sec = sum(t.get('seconds', 0) for t in tasks)
        done_n = sum(1 for t in tasks if t.get('done'))
        total_sec += sec; total_tasks += len(tasks); total_done += done_n

        # Project hours
        for t in tasks:
            proj = t.get('project', '未分类')
            project_hours[proj] = project_hours.get(proj, 0) + t.get('seconds', 0)

        # Git
        commits = get_git_log(ds)
        for repo, cs in commits.items():
            all_git.setdefault(repo, []).extend(cs)

        week_data.append({
            "date": ds,
            "weekday": ['一','二','三','四','五'][week_dates.index(ds)],
            "tasks": tasks,
            "notes": day.get('notes', ''),
            "done": done_n, "total": len(tasks), "seconds": sec
        })

    h, m = total_sec // 3600, (total_sec % 3600) // 60

    # Build prompt
    days_text = []
    for wd in week_data:
        if not wd['tasks']: continue
        days_text.append(f"\n星期{wd['weekday']} ({wd['date']}):")
        for t in wd['tasks']:
            s = '✓' if t.get('done') else '○'
            sec = t.get('seconds', 0)
            ts = f' ({sec//3600}h{(sec%3600)//60}m)' if sec > 0 else ''
            proj = f' [{t["project"]}]' if t.get('project') else ''
            days_text.append(f"  {s} {t['text']}{proj}{ts}")

    proj_text = '\n'.join([f"  {p}: {s//3600}h{(s%3600)//60}m" for p,s in sorted(project_hours.items(), key=lambda x:-x[1])])

    git_total = sum(len(v) for v in all_git.values())

    prompt = f"""你是一个周报助手。根据以下本周工作数据，生成一份结构化周报。

本周 ({week_dates[0]} ~ {week_dates[-1]}):
总耗时: {h}小时{m}分钟 | 任务: {total_done}/{total_tasks} 完成 | Git: {git_total} commits

按天:
{chr(10).join(days_text) if days_text else '(无记录)'}

项目时间分配:
{proj_text if proj_text else '(无)'}

格式要求 (用 Markdown):
- 标题层级最多用到 ### (三级), 不要用 #### 四级标题
- 四个部分用 ## 二级标题: ## 本周概览 / ## 分项目总结 / ## 关键 Git 提交 / ## 下周建议
- 列表用 - , 不要用缩进嵌套列表
- 直接输出周报内容, 不要任何前言/客套话/结束语 (如"好的"、"以下是")"""

    report = call_llm("你是周报助手。直接输出 Markdown 周报正文, 第一个字符就是 ## 标题, 禁止任何前言客套。", prompt, max_tokens=1200)
    if not report: return {"error": "LLM 调用失败"}
    # 安全网: 剥掉开头的客套话, 从第一个 markdown 标题/分隔线开始
    _m = _re.search(r'^(#{1,6}\s|\*\*|---|\d+\.\s|[-*]\s)', report, _re.M)
    if _m and _m.start() > 0:
        report = report[_m.start():].strip()

    return {
        "week": f"{week_dates[0]} ~ {week_dates[-1]}",
        "report": report,
        "stats": {"total_hours": h, "total_minutes": m, "tasks_completed": total_done,
                  "total_tasks": total_tasks, "git_commits": git_total, "project_hours": project_hours}
    }


# ============================================================
#  Claude Code session analysis
# ============================================================
def extract_cc_session_text(limit=3, date_str=None):
    """读取最近的 Claude Code 会话 transcript, 返回对话摘录字符串 (不调用 LLM)。
    date_str 给定时, 只取该天修改过的会话文件。"""
    if not CC_SESSIONS_DIR.exists():
        return None
    files = [p for p in CC_SESSIONS_DIR.glob("*.jsonl") if not p.is_symlink()]
    if date_str:
        try:
            d0 = datetime.strptime(date_str, '%Y-%m-%d').date()
            files = [p for p in files if datetime.fromtimestamp(p.stat().st_mtime).date() == d0]
        except: pass
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    recent = files[:limit]
    sessions_text = []
    for f in recent:
        try:
            lines = []
            with open(f) as fh:
                for line in fh:
                    try:
                        entry = json.loads(line)
                        etype = entry.get('type', '')
                        if etype == 'user':
                            msg = entry.get('message', {})
                            content = msg.get('content', '')
                            if isinstance(content, list):
                                texts = []
                                for block in content:
                                    if isinstance(block, dict):
                                        if block.get('type') != 'tool_result':
                                            texts.append(str(block.get('text', block.get('content', ''))))
                                    else:
                                        texts.append(str(block))
                                content = ' '.join(texts)
                            if isinstance(content, str) and len(content) > 10:
                                lines.append(f"  user: {content[:200]}")
                        elif etype == 'assistant':
                            for block in (entry.get('message', {}).get('content', []) or []):
                                if not isinstance(block, dict): continue
                                btype = block.get('type', '')
                                if btype == 'text':
                                    txt = block.get('text', '')
                                    if txt and len(txt) > 20:
                                        lines.append(f"  assistant: {txt[:200]}")
                                elif btype == 'tool_use':
                                    name = block.get('name', ''); inp = block.get('input', {}); desc = ''
                                    if name in ('Edit', 'Write'):
                                        desc = inp.get('file_path', '') or inp.get('description', '')
                                    elif name == 'Bash':
                                        desc = inp.get('description', '') or inp.get('command', '')
                                    elif name in ('Read', 'Grep', 'Glob', 'WebSearch', 'WebFetch'):
                                        desc = inp.get('description', '') or str(inp.get('file_path', '')) or str(inp.get('query', ''))
                                    if desc:
                                        lines.append(f"  tool[{name}]: {str(desc)[:150]}")
                    except: pass
            if lines:
                sessions_text.append(f"Session {f.stem[-12:]}:\n" + '\n'.join(lines[:20]))
        except: pass
    if not sessions_text:
        return None
    return '\n'.join(sessions_text)[:5000]


def analyze_cc_session(limit=3):
    """读 CC 会话, 用 LLM 提取任务列表 (供 cc-import 自动建任务)。不再产出 notes 块。"""
    if not CC_SESSIONS_DIR.exists():
        return {"sessions": 0, "summary": "未找到 CC 会话记录目录"}
    text = extract_cc_session_text(limit)
    if not text:
        return {"sessions": 0, "summary": "(无法解析会话内容 — 可能需要更多对话记录)"}
    if not AI_KEY:
        return {"sessions": limit, "sessions_text": text, "summary": "(需要 AI key)"}

    prompt = f"""分析以下 Claude Code 会话记录，提取今天做了什么工作:

{text}

输出格式 (JSON):
{{"tasks": [{{"text": "任务描述", "done": true/false, "seconds": 估算秒数(默认0), "project": "项目名或null"}}]}}
要求:
- 任务描述用稳定、简洁的动宾短语 (如"构建工作日志系统"), 同一件事固定用同一种表述
- 合并同类工作为一条, 不要拆成多条近似任务
只返回 JSON，不要解释。"""
    # temperature=0 → 同一对话每次产出一致文本, 配合去重实现幂等导入
    resp = call_llm("你是会话分析器。只返回 JSON。", prompt, max_tokens=600, temperature=0)
    if resp:
        try:
            return {"sessions": limit, "parsed": json.loads(resp)}
        except:
            return {"sessions": limit, "raw": resp}
    return {"sessions": limit, "summary": "LLM 调用失败"}


# ============================================================
#  HTTP Handler
# ============================================================
class WorkLogHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _json(self, code, data):
        self.send_response(code); self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _ok(self, data=None): self._json(200, data or {"ok": True})
    def _err(self, code, msg): self._json(code, {"error": msg})
    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        if n == 0: return None
        return json.loads(self.rfile.read(n).decode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path); path = parsed.path.rstrip('/'); qs = parse_qs(parsed.query)
        try:
            if path == '/ping':
                return self._ok({"ok": True, "file": str(DATA_FILE), "ai": bool(AI_KEY)})

            elif path == '/state':
                return self._ok(load_state())

            elif path.startswith('/summary/'):
                ds = path.split('/summary/')[1]
                state = load_state()
                day = state.get('log', {}).get(ds, {})
                tasks = day.get('tasks', [])
                done_n = sum(1 for t in tasks if t.get('done'))
                total_sec = sum(t.get('seconds', 0) for t in tasks)
                h, m = total_sec // 3600, (total_sec % 3600) // 60
                commits = get_git_log(ds)
                diffs = get_git_diff(ds)
                try:
                    d = datetime.strptime(ds, '%Y-%m-%d')
                    wd = ['一','二','三','四','五','六','日'][d.weekday()]
                except: wd = '?'
                return self._ok({
                    "date": ds, "weekday": wd, "tasks": tasks, "notes": day.get('notes', ''),
                    "stats": {"total_seconds": total_sec, "total_hours": h, "total_minutes": m,
                              "done_count": done_n, "total_count": len(tasks),
                              "pending_count": len(tasks)-done_n},
                    "git_commits": commits, "git_diffs": diffs,
                    "git_total": sum(len(v) for v in commits.values()),
                    "repos_scanned": discover_repos()
                })

            elif path == '/stats':
                m = int(qs.get('month', [datetime.now().month])[0])
                y = int(qs.get('year', [datetime.now().year])[0])
                state = load_state(); log = state.get('log', {})
                days = sec = done_n = total_n = 0
                proj_h = {}
                for ds, day in log.items():
                    try: d = datetime.strptime(ds, '%Y-%m-%d')
                    except: continue
                    if d.year == y and d.month == m:
                        tasks = day.get('tasks', [])
                        if tasks or day.get('notes','').strip(): days += 1
                        total_n += len(tasks); done_n += sum(1 for t in tasks if t.get('done'))
                        s = sum(t.get('seconds',0) for t in tasks); sec += s
                        for t in tasks:
                            p = t.get('project', '未分类')
                            proj_h[p] = proj_h.get(p,0) + t.get('seconds',0)
                h, mi = sec//3600, (sec%3600)//60
                return self._ok({"year":y,"month":m,"days":days,"total_tasks":total_n,"done":done_n,
                                 "total_seconds":sec,"hours":h,"minutes":mi,"project_hours":proj_h})

            elif path == '/weekly-report':
                ds = qs.get('date', [None])[0]
                report = generate_weekly_report(ds)
                return self._ok(report)

            elif path == '/cc-sessions':
                limit = int(qs.get('limit', [3])[0])
                result = analyze_cc_session(limit)
                return self._ok(result)

            else:
                return self._err(404, f"Not found: {path}")
        except Exception as e:
            return self._err(500, str(e))

    def do_POST(self):
        parsed = urlparse(self.path); path = parsed.path.rstrip('/')
        try:
            if path == '/state':
                body = self._body()
                if body is None: return self._err(400, "Missing body")
                save_state(body); return self._ok({"saved": True})

            elif path.startswith('/generate-summary/'):
                ds = path.split('/generate-summary/')[1]
                body = self._body() or {}
                result = generate_ai_summary(ds, save_to_notes=body.get('save', True))
                if result.get('error'): return self._err(500, result['error'])
                return self._ok(result)

            elif path.startswith('/summary/'):
                ds = path.split('/summary/')[1]
                body = self._body()
                if not body or 'text' not in body: return self._err(400, "Missing text")
                state = load_state()
                state.setdefault('log',{}).setdefault(ds,{'tasks':[],'notes':''})
                day = state['log'][ds]
                if body.get('mode') == 'replace':
                    day['notes'] = body['text']
                else:
                    day['notes'] = write_ai_block(day.get('notes',''), "自动总结", body['text'])
                save_state(state)
                return self._ok({"saved":True,"date":ds})

            elif path == '/parse-task':
                body = self._body()
                if not body or 'text' not in body: return self._err(400, "Missing text")
                result = parse_task_nl(body['text'])
                return self._ok(result or {"text": body['text'], "done": False, "seconds": 0, "project": None})

            elif path == '/cc-import':
                body = self._body() or {}
                limit = body.get('limit', 3)
                today = datetime.now().strftime('%Y-%m-%d')
                result = analyze_cc_session(limit)
                if result.get('parsed'):
                    parsed = result['parsed']
                    state = load_state()
                    state.setdefault('log',{}).setdefault(today,{'tasks':[],'notes':''})
                    day = state['log'][today]
                    # 去重: 跳过当天已存在的同名任务 (大小写/空格归一化), 只加真正新的
                    def _norm(s): return ''.join((s or '').split()).lower()
                    existing = {_norm(t.get('text','')) for t in day['tasks']}
                    imported = 0; skipped = 0
                    for t in parsed.get('tasks', []):
                        key = _norm(t.get('text',''))
                        if not key or key in existing:
                            skipped += 1; continue
                        existing.add(key)
                        day['tasks'].append({
                            'id': int(time.time()*1000) + len(day['tasks']),
                            'text': t.get('text',''), 'done': t.get('done', False),
                            'seconds': t.get('seconds', 0), 'running': False,
                            'startedAt': None, 'project': t.get('project')
                        })
                        imported += 1
                    # 只加任务, 不再单独写 CC 会话总结块 (已合并进 AI 总结)
                    save_state(state)
                    return self._ok({"imported": imported, "skipped": skipped, "date": today})
                return self._ok({"imported": 0, "raw": result})

            elif path == '/weekly-report':
                body = self._body() or {}
                ds = body.get('date', datetime.now().strftime('%Y-%m-%d'))
                save = body.get('save', False)
                report = generate_weekly_report(ds)
                if report.get('error'): return self._err(500, report['error'])
                if save:
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    state = load_state()
                    state.setdefault('log',{}).setdefault(today_str,{'tasks':[],'notes':''})
                    state['log'][today_str]['notes'] = write_ai_block(state['log'][today_str].get('notes',''), "周报", report['report'])
                    save_state(state)
                    report['saved'] = True
                return self._ok(report)

            else:
                return self._err(404, f"Not found: {path}")
        except Exception as e:
            return self._err(500, str(e))


# ============================================================
#  Startup
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description='Work Log Server v2')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--file', type=str, default=None)
    parser.add_argument('--schedule', type=str, default=os.environ.get('WORK_LOG_SCHEDULE'))
    args = parser.parse_args()
    port = args.port

    if args.file:
        global DATA_FILE; DATA_FILE = Path(args.file).resolve()
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    repos = discover_repos()
    ai_s = "✅" if AI_KEY else "⚠ not configured"

    # Scheduler
    schedule = args.schedule
    if schedule:
        def scheduler():
            print(f"[scheduler] Daily auto-summary at {schedule}")
            while True:
                now = datetime.now()
                if now.strftime('%H:%M') == schedule:
                    today = now.strftime('%Y-%m-%d')
                    state = load_state()
                    day = state.get('log',{}).get(today,{})
                    if day.get('tasks'):
                        print(f"[scheduler] Generating summary for {today}...")
                        try:
                            r = generate_ai_summary(today, save_to_notes=True)
                            if r.get('summary'): print(f"[scheduler] ✅ Done ({len(r['summary'])} chars)")
                        except Exception as e:
                            print(f"[scheduler] ❌ {e}")
                    # If Friday, also generate weekly report
                    if now.weekday() == 4:
                        print(f"[scheduler] Friday! Generating weekly report...")
                        try:
                            r = generate_weekly_report(today)
                            if r.get('report'):
                                state = load_state()
                                state.setdefault('log',{}).setdefault(today,{'tasks':[],'notes':''})
                                state['log'][today]['notes'] = write_ai_block(state['log'][today].get('notes',''), "周报", r['report'])
                                save_state(state)
                                print(f"[scheduler] ✅ Weekly report saved")
                        except Exception as e:
                            print(f"[scheduler] ❌ Weekly: {e}")
                    time.sleep(70)
                time.sleep(30)
        threading.Thread(target=scheduler, daemon=True).start()

    server = HTTPServer(('127.0.0.1', port), WorkLogHandler)
    print(f"""
╔══════════════════════════════════════════════════════╗
║      📋  Work Log Server v2                          ║
╠══════════════════════════════════════════════════════╣
║  http://localhost:{port}                              ║
║  Data:  {str(DATA_FILE)}
║  AI:    {ai_s} ({AI_MODEL})
║  Repos: {len(repos)} found
║  Auto:  {schedule or 'off'}
║                                                      ║
║  New in v2:                                          ║
║    POST /parse-task       NL → 结构化任务             ║
║    POST /cc-import        从 CC 会话导入任务          ║
║    GET  /cc-sessions      查看 CC 会话分析            ║
║    GET  /weekly-report    生成周报                   ║
║    Git diff --stat        AI 总结更详细              ║
║                                                      ║
║  Ctrl+C to stop                                      ║
╚══════════════════════════════════════════════════════╝
""".strip())
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n[server] Stopped."); server.shutdown()

if __name__ == '__main__':
    main()
