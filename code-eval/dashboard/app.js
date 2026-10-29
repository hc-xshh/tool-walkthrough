/*
 * Evaluation console.
 * Static mode: reads the generated data.js only (no writes).
 * Control mode (serve_dashboard.py): probeApi() enables the #/launch page,
 * which posts to the local API to start a whitelisted run_tool.py.
 */
(() => {
  "use strict";

  const DATA = window.__EVAL_DATA__ || { tasks: [], runs: [], task_count: 0, run_count: 0, result_count: 0 };
  const tasksById = new Map(DATA.tasks.map((t) => [t.id, t]));
  const runsById = new Map(DATA.runs.map((r) => [r.id, r]));
  const allResults = [];
  for (const run of DATA.runs) {
    for (const result of run.results) {
      allResults.push({ ...result, runId: run.id, runTool: run.tool, runDate: run.date });
    }
  }
  allResults.sort((a, b) => String(b.started || "").localeCompare(String(a.started || "")));

  const state = {
    q: "", cat: "all", comp: "all", status: "all",
    api: null, options: null, apiRuns: [],
    selected: new Set(), driver: "drive_codex.py", reps: 1, force: false,
    runId: "", launchRun: null, pollTimer: null,
  };
  const $ = (sel) => document.querySelector(sel);
  const view = $("#view");
  const search = $("#search");

  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
  const enc = (value) => encodeURIComponent(String(value ?? ""));
  const dec = (value) => decodeURIComponent(String(value ?? ""));

  const fmtInt = (n) => (typeof n === "number" && Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "—");
  const fmtSec = (n) => {
    if (typeof n !== "number" || !Number.isFinite(n)) return "—";
    if (n < 60) return `${n.toFixed(1)} 秒`;
    const m = Math.floor(n / 60);
    return `${m} 分 ${Math.round(n - m * 60)} 秒`;
  };
  const fmtTok = (n) => {
    if (typeof n !== "number" || !Number.isFinite(n) || !n) return "—";
    if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
    return String(Math.round(n));
  };
  const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0);
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
  const mean = (xs) => {
    const ys = xs.filter((x) => typeof x === "number" && Number.isFinite(x));
    return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
  };
  const median = (xs) => {
    const ys = xs.filter((x) => typeof x === "number" && Number.isFinite(x)).sort((a, b) => a - b);
    if (!ys.length) return null;
    const m = Math.floor(ys.length / 2);
    return ys.length % 2 ? ys[m] : (ys[m - 1] + ys[m]) / 2;
  };

  const CATEGORY_LABEL = {
    cli: "命令行", data: "数据处理", domain: "业务规则", files: "文件与同步",
    refactor: "代码重构", service: "服务接口", library: "第三方库",
    performance: "性能优化", async: "异步并发", web: "Web 全栈",
  };
  const COMPLEXITY_LABEL = { basic: "基础", intermediate: "进阶", advanced: "高级" };
  const TAG_LABEL = {
    parsing: "解析", money: "金额", cli: "命令行", dates: "日期", csv: "CSV",
    aggregation: "汇总", ledger: "账本", rounding: "取整", ambiguity: "需求模糊",
    sync: "同步", conflict: "冲突", filesystem: "文件系统", migration: "迁移",
    "soft-delete": "软删除", "multi-file": "多文件", compatibility: "兼容性",
    idempotency: "幂等", retry: "重试", concurrency: "并发", "real-repo": "真实仓库",
    i18n: "国际化", library: "库", http: "HTTP", persistence: "持久化",
    performance: "性能", indexing: "索引", node: "Node.js", async: "异步",
    multimodule: "多模块", sqlite: "SQLite", migration: "迁移", "backward-compat": "向后兼容",
    greenfield: "从零开发", web: "Web", frontend: "前端", "full-stack": "全栈",
  };
  const VERDICT_LABEL = {
    pass: "通过", failed: "未通过", visible_tests_failed: "可见测试未通过",
    scope_violation: "越界", timeout: "超时", blocked: "被阻塞", error: "执行出错",
    interrupted: "已中断",
  };
  const RUN_STATUS_LABEL = {
    running: "运行中", stopping: "停止中", finished: "已完成",
    failed: "失败", interrupted: "已中断",
  };
  const categoryLabel = (c) => CATEGORY_LABEL[c] || c || "—";
  const complexityLabel = (c) => COMPLEXITY_LABEL[c] || c || "—";
  const tagLabel = (t) => TAG_LABEL[t] || t;
  const statusLabel = (s) => RUN_STATUS_LABEL[s] || s || "—";
  function verdictClass(v) {
    if (v === "pass") return "pass";
    if (v === "timeout" || v === "blocked" || v === "scope_violation") return "warn";
    return "fail";
  }
  function verdict(v) {
    return `<span class="status ${verdictClass(v)}">${esc(VERDICT_LABEL[v] || v || "—")}</span>`;
  }
  function statusDot(ok) {
    return `<span class="status ${ok ? "pass" : "fail"}">${ok ? "通过" : "失败"}</span>`;
  }
  function pill(text, cls = "") {
    return `<span class="pill ${cls}">${esc(text)}</span>`;
  }
  function tags(tags) {
    return (tags || []).map((t) => pill(tagLabel(t), "tag")).join(" ");
  }
  function catPill(cat) {
    return cat ? pill(categoryLabel(cat), "cat") : "";
  }
  function compPill(comp) {
    if (!comp) return "";
    return pill(complexityLabel(comp), comp === "advanced" ? "adv" : comp === "basic" ? "basic" : "");
  }
  function fmtTimebox(seconds) {
    const n = Number(seconds);
    if (!Number.isFinite(n) || n <= 0) return "—";
    return n % 60 === 0 ? `${n / 60} 分钟` : `${n} 秒`;
  }
  function shortTool(name) {
    const s = String(name || "unknown");
    return s.length > 26 ? s.slice(0, 25) + "…" : s;
  }
  function shortRun(id) {
    return String(id || "").replace(/^\d{4}-\d{2}-\d{2}-/, "");
  }
  function testLabel(name) {
    return String(name || "").split(".").pop();
  }

  function statsOf(results) {
    const total = results.length;
    const passed = results.filter((r) => r.verdict === "pass").length;
    return {
      total, passed, rate: pct(passed, total),
      duration: mean(results.map((r) => r.duration_s)),
      tokens: mean(results.map((r) => (r.usage || {}).total_tokens)),
    };
  }
  function runStats(run) { return statsOf(run.results); }
  function taskResults(id) { return allResults.filter((r) => r.task === id); }
  function taskStatus(id) {
    const latest = taskResults(id)[0];
    if (!latest) return "unrun";
    return latest.verdict === "pass" ? "pass" : "fail";
  }

  function bar(rate, klass = "") {
    return `<div class="bar ${klass}"><i style="width:${clamp(rate, 0, 100)}%"></i></div>`;
  }
  function rateClass(rate) {
    if (rate >= 90) return "pass";
    if (rate >= 50) return "mid";
    return "fail";
  }

  function parseHash() {
    const raw = location.hash.replace(/^#\/?/, "");
    const parts = raw.split("/").filter(Boolean).map(dec);
    return { page: parts[0] || "overview", parts: parts.slice(1) };
  }
  function href(path) { return `#${path}`; }
  function go(path) {
    const target = String(path).startsWith("#") ? path : `#${path}`;
    if (location.hash === target) render();
    else location.hash = target;
  }

  async function api(path, options = {}) {
    const res = await fetch(path, { cache: "no-store", ...options });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  }

  let toastTimer = null;
  function toast(text) {
    const el = document.querySelector("#toast");
    if (!el) return;
    el.textContent = text;
    el.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("on"), 2400);
  }

  function selectedTaskIds() {
    return [...state.selected].filter((id) => tasksById.has(id));
  }
  function driverLabel(id) {
    const d = (state.options?.drivers || []).find((x) => x.id === id);
    return d ? d.label : id.replace(/^drive_/, "").replace(/\.py$/, "");
  }
  function commandPreview() {
    const ids = selectedTaskIds();
    const run = state.runId.trim() || "<自动生成>";
    return `python3 code-eval/tools/run_tool.py --driver ${state.driver} --tasks ${ids.join(",") || "<选择任务>"} --reps ${state.reps} --run runs/${run}${state.force ? " --force" : ""}`;
  }
  function updateModePill() {
    const el = document.querySelector("#mode-pill");
    const foot = document.querySelector("#mode-foot");
    const hint = document.querySelector("#mode-hint");
    if (!el) return;
    if (state.api === true) {
      el.textContent = "控制模式";
      el.style.color = "var(--amber)";
      el.style.borderColor = "rgba(227,179,65,.35)";
      el.style.background = "rgba(227,179,65,.07)";
      if (foot) foot.textContent = "本地控制";
      if (hint) hint.textContent = "可在“新建”页启动运行";
    } else if (state.api === false) {
      el.textContent = "只读";
      el.style.color = "";
      el.style.borderColor = "";
      el.style.background = "";
      if (foot) foot.textContent = "本地只读";
      if (hint) hint.textContent = "只能看结果 · 不写 runs/";
    } else {
      el.textContent = "检测中";
      if (foot) foot.textContent = "正在检测";
    }
  }
  function updatePickedSummary() {
    const count = selectedTaskIds().length;
    const c = document.querySelector("#selected-count");
    if (c) c.textContent = `已选 ${count} / ${DATA.tasks.length}`;
    const cmd = document.querySelector("#cmd-preview");
    if (cmd) cmd.textContent = commandPreview();
    const start = document.querySelector("[data-action=start]");
    if (start) start.disabled = !state.api || !count || !!activeRun();
  }
  function activeRun() {
    if (state.launchRun && state.launchRun.status === "running") return state.launchRun;
    return (state.apiRuns || []).find((r) => r.status === "running") || null;
  }

  async function probeApi() {
    try {
      const health = await api("/api/health");
      if (!health?.ok) throw new Error("not control mode");
      state.api = true;
      state.options = await api("/api/options");
      const runs = await api("/api/runs");
      state.apiRuns = runs.runs || [];
      if (!state.selected.size) {
        // Do not pick tasks silently; leave it empty and make the user choose.
      }
      updateModePill();
      if (parseHash().page === "launch") render();
    } catch {
      state.api = false;
      updateModePill();
      if (parseHash().page === "launch") render();
    }
  }

  async function refreshApiRuns() {
    if (!state.api) return;
    try {
      const { runs } = await api("/api/runs");
      state.apiRuns = runs || [];
      if (parseHash().page === "launch") render();
    } catch {
      // Keep the last list; the launch panel will show its own errors.
    }
  }

  function crumbs(items) {
    const bits = [];
    items.forEach((item, i) => {
      if (i) bits.push(`<span class="sep">/</span>`);
      if (item.href) bits.push(`<a href="${esc(item.href)}">${esc(item.label)}</a>`);
      else bits.push(`<span class="here">${esc(item.label)}</span>`);
    });
    $("#crumbs").innerHTML = bits.join("");
  }

  function activeNav(page) {
    const navPage = page === "results" ? "runs" : page;
    document.querySelectorAll("[data-route]").forEach((el) => {
      el.classList.toggle("active", el.dataset.route === navPage);
    });
  }

  function head(eyebrow, title, sub, extra = "") {
    return `<div class="page-head">
      <div><div class="eyebrow">${esc(eyebrow)}</div><h1>${esc(title)}</h1>${sub ? `<p class="sub">${esc(sub)}</p>` : ""}</div>
      ${extra}
    </div>`;
  }

  function empty(title, detail) {
    return `<div class="empty"><strong>${esc(title)}</strong>${esc(detail || "")}</div>`;
  }

  // ---------- overview ----------
  function renderOverview() {
    const total = allResults.length;
    const passed = allResults.filter((r) => r.verdict === "pass").length;
    const rate = pct(passed, total);
    const runRows = DATA.runs.map((run) => {
      const s = runStats(run);
      return `<tr class="click" data-go="${href(`/runs/${enc(run.id)}`)}">
        <td class="id">${esc(run.id)}</td>
        <td>${esc(shortTool(run.tool))}<div class="subline">${esc(run.date || "")}</div></td>
        <td class="num">${s.passed}/${s.total}</td>
        <td class="num">${fmtSec(s.duration)}</td>
        <td class="num">${fmtTok(s.tokens)}</td>
        <td style="width:140px"><div style="display:flex;align-items:center;gap:8px">${bar(s.rate, s.rate >= 90 ? "" : s.rate >= 50 ? "mid" : "fail")}<span class="dim mono" style="font-size:10px">${s.rate}%</span></div></td>
      </tr>`;
    }).join("");

    const recent = allResults.slice(0, 6).map((r) => `<tr class="click" data-go="${href(`/results/${enc(r.runId)}/${enc(r.task)}/${enc(r.rep)}`)}">
      <td>${verdict(r.verdict)}</td>
      <td><div class="task-name">${esc(r.title || tasksById.get(r.task)?.title || r.task)}</div><div class="subline mono">${esc(r.task)}</div></td>
      <td>${esc(shortTool(r.runTool))}</td>
      <td class="num">${fmtSec(r.duration_s)}</td>
      <td class="num">${fmtTok((r.usage || {}).total_tokens)}</td>
    </tr>`).join("");

    const cats = DATA.tasks.reduce((acc, t) => {
      acc[t.category] = (acc[t.category] || 0) + 1;
      return acc;
    }, {});
    const catRows = Object.entries(cats).sort((a, b) => b[1] - a[1]).map(([cat, n]) => `
      <div style="display:flex;align-items:center;gap:8px;margin:7px 0">
        ${catPill(cat)}<div class="bar" style="flex:1"><i style="width:${pct(n, DATA.tasks.length)}%;background:var(--blue)"></i></div>
        <span class="dim mono" style="font-size:10px">${n}</span>
      </div>`).join("");

    return `${head("总览", "评测控制台", "先看任务和最近结果；每一行都能点进去看它为什么通过、为什么没通过。", `<span class="pill">${DATA.result_count} 条结果</span>`)}
      <div class="kpis">
        <div class="kpi info"><div class="k">任务</div><div class="n">${DATA.task_count}</div><div class="d">${Object.keys(cats).length} 类 · ${DATA.tasks.filter((t) => t.complexity === "advanced").length} 个高级任务</div></div>
        <div class="kpi info"><div class="k">运行</div><div class="n">${DATA.run_count}</div><div class="d">${new Set(DATA.runs.map((r) => r.tool)).size} 个工具配置</div></div>
        <div class="kpi good"><div class="k">通过率</div><div class="n">${rate}%</div><div class="d">${passed} / ${total} 次结果</div></div>
        <div class="kpi ${rate >= 90 ? "good" : "warn"}"><div class="k">中位耗时</div><div class="n">${fmtSec(median(allResults.map((r) => r.duration_s)))}</div><div class="d">一半尝试比这更快，不是上限</div></div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h2>最近运行</h2><span class="hint">按日期倒序</span></div>
          <div class="tbl-wrap"><table>
            <thead><tr><th>运行</th><th>工具</th><th class="num">通过/尝试</th><th class="num">平均耗时</th><th class="num">消耗</th><th>进度</th></tr></thead>
            <tbody>${runRows || `<tr><td colspan="6">${empty("还没有运行记录", "先跑一次评测，再重新生成页面。")}</td></tr>`}</tbody>
          </table></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>任务分布</h2><span class="hint">共 ${DATA.task_count} 个任务</span></div>
          ${catRows || empty("没有任务", "tasks/*.json 为空。")}
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>最近结果</h2><a class="dim mono" style="font-size:10px" href="${href("/runs")}">全部运行 →</a></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>结果</th><th>任务</th><th>工具</th><th class="num">耗时</th><th class="num">消耗</th></tr></thead>
          <tbody>${recent || `<tr><td colspan="5">${empty("还没有结果", "results/*.json 为空。")}</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  // ---------- tasks ----------
  function renderTasks() {
    const cats = ["all", ...Array.from(new Set(DATA.tasks.map((t) => t.category))).sort()];
    const comps = ["all", "basic", "intermediate", "advanced"];
    const statuses = [["all", "全部状态"], ["unrun", "未跑"], ["pass", "已通过"], ["fail", "未通过"]];
    const q = state.q.toLowerCase();
    const list = DATA.tasks.filter((t) => {
      if (state.cat !== "all" && t.category !== state.cat) return false;
      if (state.comp !== "all" && t.complexity !== state.comp) return false;
      if (state.status !== "all" && taskStatus(t.id) !== state.status) return false;
      if (q) {
        const hay = `${t.id} ${t.title} ${t.category} ${categoryLabel(t.category)} ${t.complexity} ${complexityLabel(t.complexity)} ${(t.tags || []).map(tagLabel).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const rows = list.map((t) => {
      const rs = taskResults(t.id);
      const s = statsOf(rs);
      const latest = rs[0];
      const tagText = (t.tags || []).map(tagLabel).join(" · ");
      return `<tr class="click" data-go="${href(`/tasks/${enc(t.id)}`)}">
        <td class="num"><span class="level-badge">L${esc(t.level)}</span></td>
        <td><div class="task-name" title="${esc(t.title)}">${esc(t.title)}</div><div class="subline mono">${esc(t.id)}</div></td>
        <td>${catPill(t.category)}</td>
        <td>${compPill(t.complexity)}</td>
        <td class="dim">${esc(tagText || "—")}</td>
        <td class="num">${s.total ? `${s.passed}/${s.total}` : "—"}</td>
        <td>${latest ? verdict(latest.verdict) : `<span class="dim">未跑</span>`}</td>
      </tr>`;
    }).join("");

    const chips = cats.map((c) => `<button class="chip ${state.cat === c ? "on" : ""}" data-cat="${esc(c)}">${esc(c === "all" ? "全部" : categoryLabel(c))}</button>`).join("");
    const opts = comps.map((c) => `<option value="${esc(c)}" ${state.comp === c ? "selected" : ""}>${esc(c === "all" ? "全部难度" : complexityLabel(c))}</option>`).join("");
    const statusOpts = statuses.map(([v, label]) => `<option value="${v}" ${state.status === v ? "selected" : ""}>${label}</option>`).join("");

    return `${head("任务目录", "任务", "中文标题是任务本身，下面小字是技术代号。点一行看要求、验收和历史。", `<span class="pill">${list.length === DATA.tasks.length ? `${list.length} 个任务` : `筛选出 ${list.length} / ${DATA.tasks.length}`}</span>`)}
      <div class="panel">
        <div class="toolbar">
          <div class="left"><div class="chips">${chips}</div><select id="complexity">${opts}</select><select id="status">${statusOpts}</select></div>
          <div class="right">按级别排序</div>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr><th class="num">级别</th><th>任务</th><th>类型</th><th>难度</th><th>标签</th><th class="num">通过/尝试</th><th>最近结果</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="7">${empty("没有匹配任务", "换个分类、难度，或清空搜索。")}</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  function renderTask(id) {
    const t = tasksById.get(id);
    if (!t) return `${empty("找不到任务", id)}`;
    const rs = taskResults(id);
    const s = statsOf(rs);
    const latest = rs[0];
    const latestLink = latest ? href(`/results/${enc(latest.runId)}/${enc(latest.task)}/${enc(latest.rep)}`) : null;
    const attempts = rs.map((r) => `<tr class="click" data-go="${href(`/results/${enc(r.runId)}/${enc(r.task)}/${enc(r.rep)}`)}">
      <td class="id" title="${esc(r.runId)}">${esc(shortRun(r.runId))}</td>
      <td>${esc(shortTool(r.runTool))}</td>
      <td class="num">第 ${esc(r.rep)} 次</td>
      <td>${verdict(r.verdict)}</td>
      <td class="num">${fmtSec(r.duration_s)}</td>
    </tr>`).join("");

    const reqs = (t.requirements || []).map((r) => {
      const met = latest ? (latest.requirements || []).find((y) => y.id === r.id)?.met : null;
      const testText = (r.tests || []).map(testLabel).join(" · ");
      return `<div class="req-row">
        <div class="req-id">需求 ${esc(String(r.id).replace(/^R/, ""))}</div>
        <div><div>${esc(r.text)}</div>${testText ? `<div class="req-tests">对应测试：${esc(testText)}</div>` : ""}</div>
        <div class="req-state">${met === true ? `<span class="status pass">已满足</span>` : met === false ? `<span class="status fail">未满足</span>` : `<span class="dim">未验证</span>`}</div>
      </div>`;
    }).join("");

    return `${head("任务详情", t.title, `任务编号 ${t.id}`, `<span class="pill">L${esc(t.level)}</span>`)}
      <div class="toolbar" style="margin-bottom:12px"><a class="back" href="${href("/tasks")}">← 返回任务目录</a><a class="btn primary" href="${href("/launch")}" data-preset-task="${esc(t.id)}">用这个任务去运行</a></div>
      <div class="meta">
        <div><div class="k">级别</div><div class="v">L${esc(t.level)}</div></div>
        <div><div class="k">类型</div><div class="v">${esc(categoryLabel(t.category))}</div></div>
        <div><div class="k">难度</div><div class="v">${esc(complexityLabel(t.complexity))}</div></div>
        <div><div class="k">限时</div><div class="v">${esc(fmtTimebox(t.timebox_s))}</div></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>任务要求</h2><div>${tags(t.tags)}</div></div>
        <div class="hint" style="margin-bottom:10px">这是交给被测 agent 的原始任务书。</div>
        <div class="prompt">${esc(t.prompt || "（题面文件为空）")}</div>
      </div>
      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>验收要求</h2><span class="hint">${latest ? `<a href="${latestLink}">最近一次：${esc(shortTool(latest.runTool))} · 第 ${esc(latest.rep)} 次</a> · ${(latest.requirements || []).filter((x) => x.met).length}/${(t.requirements || []).length} 已满足` : `共 ${(t.requirements || []).length} 条`}</span></div>${reqs || `<div class="dim">没有验收要求记录。</div>`}</div>
        <div class="panel"><div class="panel-head"><h2>跑过几次</h2><span class="hint">${s.total ? `${s.total} 次尝试 · ${s.passed} 次通过` : "还没跑过"}</span></div>
          <div class="tbl-wrap"><table><thead><tr><th>运行</th><th>工具</th><th class="num">轮次</th><th>结果</th><th class="num">耗时</th></tr></thead>
          <tbody>${attempts || `<tr><td colspan="5" class="dim">这个任务还没跑过。</td></tr>`}</tbody></table></div>
        </div>
      </div>`;
  }

  // ---------- runs ----------
  function renderRuns() {
    const q = state.q.toLowerCase();
    const list = DATA.runs.filter((run) => {
      if (!q) return true;
      return `${run.id} ${run.tool} ${run.date}`.toLowerCase().includes(q);
    });
    const rows = list.map((run) => {
      const s = runStats(run);
      return `<tr class="click" data-go="${href(`/runs/${enc(run.id)}`)}">
        <td class="id">${esc(run.id)}</td>
        <td>${esc(run.date || "—")}</td>
        <td>${esc(run.tool)}</td>
        <td class="num">${s.passed}/${s.total}</td>
        <td class="num">${fmtSec(s.duration)}</td>
        <td class="num">${fmtTok(s.tokens)}</td>
        <td style="width:140px"><div style="display:flex;align-items:center;gap:8px">${bar(s.rate, s.rate >= 90 ? "" : s.rate >= 50 ? "mid" : "fail")}<span class="dim mono" style="font-size:10px">${s.rate}%</span></div></td>
      </tr>`;
    }).join("");
    return `${head("运行记录", "运行", "一次运行 = 一组任务 × 重复次数。点进去看每个任务的逐条结果。", `<span class="pill">${list.length} 次运行</span>`)}
      <div class="panel">
        <div class="tbl-wrap"><table>
          <thead><tr><th>运行</th><th>日期</th><th>工具</th><th class="num">通过/尝试</th><th class="num">平均耗时</th><th class="num">消耗</th><th>进度</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="7">${empty("没有匹配运行", "清空搜索或先跑一次评测。")}</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  function renderRun(id) {
    const run = runsById.get(id);
    if (!run) return empty("找不到运行", id);
    const s = runStats(run);
    const rows = run.results.map((r) => {
      const reqs = r.requirements || [];
      const met = reqs.filter((x) => x.met).length;
      return `<tr class="click" data-go="${href(`/results/${enc(run.id)}/${enc(r.task)}/${enc(r.rep)}`)}">
        <td class="num">L${esc(r.level)}</td>
        <td><div class="task-name">${esc(r.title || r.task)}</div><div class="subline mono">${esc(r.task)}</div></td>
        <td class="num">第 ${esc(r.rep)} 次</td>
        <td>${verdict(r.verdict)}</td>
        <td class="num">${met}/${reqs.length || "—"}</td>
        <td class="num">${r.accept?.passed ?? "—"}/${r.accept?.total ?? "—"}</td>
        <td class="num">${fmtSec(r.duration_s)}</td>
        <td class="num">${fmtTok((r.usage || {}).total_tokens)}</td>
      </tr>`;
    }).join("");
    return `${head("运行详情", run.id, run.tool, `<span class="pill">${run.date || ""}</span>`)}
      <a class="back" href="${href("/runs")}">← 运行列表</a>
      <div class="kpis">
        <div class="kpi info"><div class="k">结果</div><div class="n">${s.total}</div><div class="d">共 ${run.results.length} 次尝试</div></div>
        <div class="kpi good"><div class="k">通过</div><div class="n">${s.passed}/${s.total}</div><div class="d">${s.rate}%</div></div>
        <div class="kpi info"><div class="k">平均耗时</div><div class="n">${fmtSec(s.duration)}</div><div class="d">每次尝试</div></div>
        <div class="kpi info"><div class="k">平均消耗</div><div class="n">${fmtTok(s.tokens)}</div><div class="d">有记录时</div></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>逐条结果</h2><span class="hint">点一行看验收要求、隐藏测试和改动 diff</span></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th class="num">级别</th><th>任务</th><th class="num">轮次</th><th>结果</th><th class="num">需求</th><th class="num">隐藏</th><th class="num">耗时</th><th class="num">消耗</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="8" class="dim">没有结果。</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  // ---------- result ----------
  function checkCard(label, ok, value, sub = "") {
    const cls = ok === true ? "good" : ok === false ? "bad" : "warn";
    return `<div class="check ${cls}"><div class="k">${esc(label)}</div><div class="v">${esc(value)}</div>${sub ? `<div class="s">${esc(sub)}</div>` : ""}</div>`;
  }

  function diffHtml(text) {
    return String(text || "").split("\n").map((line) => {
      const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
        : line.startsWith("-") && !line.startsWith("---") ? "del"
        : line.startsWith("@@") ? "hunk" : "";
      return cls ? `<span class="${cls}">${esc(line)}</span>` : esc(line);
    }).join("\n");
  }

  function renderResult(runId, taskId, rep) {
    const run = runsById.get(runId);
    const r = run?.results.find((x) => x.task === taskId && String(x.rep) === String(rep));
    if (!r) return empty("找不到结果", `${runId} / ${taskId} / r${rep}`);
    const reqs = r.requirements || [];
    const met = reqs.filter((x) => x.met).length;
    const reqHtml = reqs.map((x) => {
      const failed = (x.failed || []).join(" · ");
      const missing = (x.missing || []).join(" · ");
      return `<div class="req-row">
        <div class="req-id">需求 ${esc(String(x.id).replace(/^R/, ""))}</div>
        <div><div>${esc(x.text)}</div><div class="req-tests">${esc((x.tests || []).map(testLabel).join(" · "))}${failed ? ` · 未通过：${esc(failed)}` : ""}${missing ? ` · 缺少：${esc(missing)}` : ""}</div></div>
        <div class="req-state">${x.met ? `<span class="status pass">已满足</span>` : `<span class="status fail">未满足</span>`}</div>
      </div>`;
    }).join("");
    const acceptRows = (r.accept?.tests || []).map((t) => `<tr><td class="id">${esc(testLabel(t.test))}</td><td>${statusDot(t.status === "passed")}</td></tr>`).join("");
    const failures = (r.accept?.failures || []).map((f) => `<li>${esc(f)}</li>`).join("");
    const scope = r.scope || {};
    const quality = r.quality || {};
    const claims = r.claims || {};
    const changes = r.changes || {};
    const scopeIssues = [...(scope.forbidden_hits || []), ...(scope.outside_allowed || []), ...(scope.harness_tamper || [])];
    const qualityIssues = [...(quality.extra_files || []), ...(quality.debug_markers || []), ...(quality.undeclared_imports || [])];
    const claimsHard = (claims.changed_not_mentioned || []);
    const claimsSoft = (claims.mentioned_not_changed || []);
    const cloneOk = r.deliverable?.ok === true;
    const visibleOk = r.visible?.rc === 0;
    const scopeOk = scopeIssues.length === 0;
    const qualityOk = quality.usable === true && qualityIssues.length === 0;
    const testsOk = (r.accept?.passed ?? 0) === (r.accept?.total ?? 0) && (r.accept?.total ?? 0) > 0;

    return `${head("结果详情", `${r.title || r.task} · 第 ${r.rep} 次`, `任务编号 ${r.task}`, `<span class="pill">${esc(r.runTool)}</span>`)}
      <a class="back" href="${href(`/runs/${enc(runId)}`)}">← ${esc(runId)}</a>
      <div class="panel" style="border-left:3px solid var(--${verdictClass(r.verdict) === "pass" ? "green" : verdictClass(r.verdict) === "warn" ? "amber" : "red"})">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
          <div><div class="eyebrow">判定</div><div style="font:600 22px var(--mono);margin:2px 0 5px">${verdict(r.verdict)}</div><div class="dim">${esc(r.reason || "")}</div></div>
          <div class="mono dim" style="font-size:10px;text-align:right">${esc(r.started || "")}<br>工作副本</div>
        </div>
      </div>
      <div class="meta">
        <div><div class="k">任务</div><div class="v">${esc(r.title || r.task)}</div></div>
        <div><div class="k">级别</div><div class="v">L${esc(r.level)} · 第 ${esc(r.rep)} 次</div></div>
        <div><div class="k">耗时</div><div class="v">${fmtSec(r.duration_s)}</div></div>
        <div><div class="k">消耗</div><div class="v">${fmtTok((r.usage || {}).total_tokens)}</div></div>
      </div>

      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>验收要求</h2><span class="hint">${met}/${reqs.length} 已满足</span></div>${reqHtml || `<div class="dim">没有验收要求记录。</div>`}</div>
        <div class="panel"><div class="panel-head"><h2>验收与检查</h2><span class="hint">${testsOk ? "隐藏验收全部通过" : "隐藏验收有失败"}</span></div>
          <div class="check-grid">
            ${checkCard("隐藏验收", testsOk, `${r.accept?.passed ?? "—"}/${r.accept?.total ?? "—"}`, `返回码 ${r.accept?.rc ?? "—"} · ${fmtSec(r.accept?.seconds)}`)}
            ${checkCard("可见测试", visibleOk, visibleOk ? "通过" : `返回码 ${r.visible?.rc ?? "—"}`, `${fmtSec(r.visible?.seconds)}`)}
            ${checkCard("干净复现", cloneOk, cloneOk ? "可复现" : "失败", r.deliverable?.failed?.length ? r.deliverable.failed.join(" · ") : "")}
            ${checkCard("改动范围", scopeOk, scopeOk ? "没有越界" : "有越界", scopeIssues.length ? scopeIssues.join(" · ") : "禁区 / 允许范围 / 测试装置均未碰")}
            ${checkCard("可用性", qualityOk, qualityOk ? "可直接用" : "有残留", qualityIssues.length ? qualityIssues.join(" · ") : "无多余文件 / 调试标记 / 未声明依赖")}
            ${checkCard("改动声明", claimsHard.length === 0 ? (claimsSoft.length ? null : true) : false, claimsHard.length ? `${claimsHard.length} 处改了没说` : (claimsSoft.length ? `${claimsSoft.length} 处说了没改` : "对得上"), `说了没改 ${claimsSoft.length} · 改了没说 ${claimsHard.length}`)}
          </div>
          <div style="margin-top:12px" class="mono dim">改动 ${esc(changes.lines_added ?? 0)} 行新增 / ${esc(changes.lines_removed ?? 0)} 行删除 · ${esc((changes.modified || []).length + (changes.added || []).length)} 个文件</div>
          ${failures ? `<div style="margin-top:12px"><div class="k dim" style="font-size:9px">隐藏验收失败</div><ul class="list">${failures}</ul></div>` : ""}
        </div>
      </div>

      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>隐藏验收</h2><span class="hint">${(r.accept?.tests || []).length} 条测试</span></div>
          <div class="tbl-wrap"><table><thead><tr><th>测试</th><th>结果</th></tr></thead><tbody>${acceptRows || `<tr><td colspan="2" class="dim">没有逐测试记录。</td></tr>`}</tbody></table></div>
        </div>
        <div class="panel"><div class="panel-head"><h2>改动与声明</h2><span class="hint">核对“说到的”和“改到的”</span></div>
          <div class="check-grid">
            ${checkCard("说了没改", (claims.mentioned_not_changed || []).length === 0 ? true : null, (claims.mentioned_not_changed || []).join(" · ") || "无", "提到不等于改过，不单独判失败")}
            ${checkCard("改了没说", (claims.changed_not_mentioned || []).length === 0, (claims.changed_not_mentioned || []).join(" · ") || "无", "")}
          </div>
          <div style="margin-top:12px"><div class="k dim" style="font-size:9px">改动文件</div>
            <div class="mono dim" style="font-size:10px;margin-top:4px">${esc([...(changes.added || []), ...(changes.modified || []), ...(changes.deleted || [])].join(" · ") || "—")}</div>
          </div>
        </div>
      </div>

      <div class="panel"><details><summary>查看 diff${r.patch_truncated ? "（已截断）" : ""}</summary><pre class="diff">${diffHtml(r.patch || "（没有 patch 记录）")}</pre></details></div>`;
  }

  // ---------- compare ----------
  function renderCompare() {
    const tools = Array.from(new Set(DATA.runs.map((r) => r.tool))).sort();
    const rows = DATA.tasks.map((t) => {
      const cells = tools.map((tool) => {
        const rs = allResults.filter((r) => r.task === t.id && r.runTool === tool);
        const s = statsOf(rs);
        if (!s.total) return `<td><span class="cell">—</span></td>`;
        const klass = rateClass(s.rate);
        return `<td><span class="cell ${klass}" title="${esc(tool)} · ${s.passed}/${s.total}">${s.passed}/${s.total}</span></td>`;
      }).join("");
      return `<tr><td class="task-cell"><a href="${href(`/tasks/${enc(t.id)}`)}"><span class="task-name">${esc(t.title)}</span><div class="subline mono">${esc(t.id)}</div></a></td>${cells}</tr>`;
    }).join("");
    const heads = tools.map((tool) => `<th title="${esc(tool)}">${esc(shortTool(tool))}</th>`).join("");
    return `${head("工具对比", "工具 × 任务", "同一任务在不同工具下的通过次数。绿色=全过，黄色=部分通过，红色=没过。", `<span class="pill">${tools.length} 个工具</span>`)}
      <div class="panel" style="overflow:auto">
        <table class="matrix"><thead><tr><th>任务</th>${heads}</tr></thead><tbody>${rows}</tbody></table>
      </div>
      <p class="dim mono" style="font-size:10px">单元格 = 通过次数 / 尝试次数；同一工具多次 run 会合并。不是统计显著性，只是当前样本。</p>`;
  }


  // ---------- launch (control mode only) ----------
  function syncPicks() {
    document.querySelectorAll("[data-task]").forEach((el) => {
      el.checked = state.selected.has(el.dataset.task);
    });
    updatePickedSummary();
  }

  function renderLaunch() {
    const apiState = state.api;
    const active = activeRun() || (state.apiRuns || []).find((r) => r.status === "running");
    const recent = (state.apiRuns || []).slice(0, 8).map((r) => {
      const status = r.status === "finished" ? "pass" : r.status === "running" || r.status === "stopping" ? "warn" : "fail";
      return `<tr>
        <td class="id">${esc(r.id)}</td>
        <td>${esc(r.driver_label || driverLabel(r.driver || ""))}</td>
        <td class="num">${esc((r.tasks || []).length)} 个 × ${esc(r.reps || 1)} 次</td>
        <td><span class="status ${status}">${esc(statusLabel(r.status))}</span></td>
        <td class="num">${fmtSec(r.duration_s)}</td>
        <td class="num"><a href="${href(`/runs/${enc(r.id)}`)}" class="dim">查看</a></td>
      </tr>`;
    }).join("");

    if (apiState === null) {
      return `${head("新建运行", "新建运行", "正在检测本地控制服务…")}<div class="panel dim">连接 /api/health…</div>`;
    }
    if (apiState === false) {
      return `${head("新建运行", "新建运行", "当前是静态只读模式。要在这里启动运行，需要用本地控制服务打开。")}
        <div class="panel">
          <div class="panel-head"><h2>启动控制服务</h2><span class="pill">仅本机</span></div>
          <pre class="prompt">cd ~/workspace/tool-walkthrough
python3 code-eval/tools/serve_dashboard.py
# 然后打开 http://127.0.0.1:8787/#/launch</pre>
          <p class="dim" style="margin-bottom:0">静态模式（<code>python -m http.server</code>）只能看结果，不能启动任务。</p>
        </div>`;
    }

    const selected = selectedTaskIds();
    const options = state.options?.drivers || [];
    const catOptions = ["all", ...Array.from(new Set(DATA.tasks.map((t) => t.category))).sort()];
    const compOptions = ["all", "basic", "intermediate", "advanced"];
    const picks = DATA.tasks.map((t) => `<label class="pick">
      <input type="checkbox" data-task="${esc(t.id)}" ${state.selected.has(t.id) ? "checked" : ""}>
      <span><b>L${esc(t.level)}</b> ${esc(t.title)}<em>${esc(categoryLabel(t.category))} · ${esc(complexityLabel(t.complexity))} · ${esc(t.id)}</em></span>
    </label>`).join("");
    const driverOptions = options.map((d) => `<option value="${esc(d.id)}" ${state.driver === d.id ? "selected" : ""}>${esc(d.label)}</option>`).join("");
    const log = state.launchRun?.log ? esc(state.launchRun.log) : "（尚无日志）";
    const runPanel = state.launchRun ? `<div class="panel" id="active-run">
      <div class="panel-head"><h2>当前运行</h2><span class="status ${state.launchRun.status === "running" ? "warn" : state.launchRun.status === "finished" ? "pass" : "fail"}">${esc(statusLabel(state.launchRun.status))}</span></div>
      <div class="meta" style="margin-bottom:12px">
        <div><div class="k">运行编号</div><div class="v">${esc(state.launchRun.id)}</div></div>
        <div><div class="k">驱动器</div><div class="v">${esc(state.launchRun.driver_label || state.launchRun.driver)}</div></div>
        <div><div class="k">任务</div><div class="v">${esc((state.launchRun.tasks || []).length)} 个 × ${esc(state.launchRun.reps || 1)} 次</div></div>
        <div><div class="k">耗时</div><div class="v">${fmtSec(state.launchRun.duration_s)}</div></div>
      </div>
      <pre class="prompt log">${log}</pre>
      ${state.launchRun.status === "running" || state.launchRun.status === "stopping" ? `<button class="btn danger" data-action="stop">停止</button>` : ""}
      ${state.launchRun.status === "finished" && state.launchRun.data_built ? `<span class="dim" style="font-size:10px;margin-left:10px">数据已重建，页面稍后自动刷新</span>` : ""}
    </div>` : "";

    return `${head("新建运行", "新建运行", "选择任务和驱动器，在本地启动一次评测。只允许预先配置的驱动器与任务；同一时间只跑一个。", `<span class="pill">控制模式</span>`)}
      ${runPanel}
      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h2>任务</h2><span class="hint" id="selected-count">已选 ${selected.length} / ${DATA.tasks.length}</span></div>
          <div class="toolbar"><div class="left">
            <select data-filter="cat">${catOptions.map((c) => `<option value="${esc(c)}">${esc(c === "all" ? "全部分类" : categoryLabel(c))}</option>`).join("")}</select>
            <select data-filter="comp">${compOptions.map((c) => `<option value="${esc(c)}">${esc(c === "all" ? "全部难度" : complexityLabel(c))}</option>`).join("")}</select>
            <button class="chip" data-action="apply-filter">按筛选选中</button>
            <button class="chip" data-action="hardest">只选最复杂 1 个</button>
            <button class="chip" data-action="clear">清空</button>
          </div></div>
          <div class="pick-list">${picks}</div>
        </div>
        <div>
          <div class="panel">
            <div class="panel-head"><h2>启动参数</h2><span class="hint">仅限预置项</span></div>
            <label class="field"><span>驱动器</span><select data-input="driver">${driverOptions}</select></label>
            <label class="field"><span>重复次数</span><input data-input="reps" type="number" min="1" max="10" value="${esc(state.reps)}"></label>
            <label class="field"><span>运行编号</span><input data-input="run-id" type="text" placeholder="留空自动生成" value="${esc(state.runId)}"></label>
            <label class="field check"><input data-input="force" type="checkbox" ${state.force ? "checked" : ""}><span>覆盖同一次运行里的旧结果</span></label>
            <pre class="command" id="cmd-preview">${esc(commandPreview())}</pre>
            <button class="btn primary" data-action="start" ${!selected.length || active ? "disabled" : ""}>开始运行</button>
            <div class="hint" style="margin-top:8px">${active ? `已有运行进行中：${esc(active.id)}` : "启动后在这里看日志；完成后会自动刷新数据。"}</div>
          </div>
          <div class="panel">
            <div class="panel-head"><h2>控制运行</h2><button class="chip" data-action="refresh">刷新</button></div>
            <div class="tbl-wrap"><table><thead><tr><th>运行</th><th>驱动器</th><th class="num">任务</th><th>状态</th><th class="num">耗时</th><th></th></tr></thead>
            <tbody>${recent || `<tr><td colspan="6" class="dim">还没有控制台启动的运行。</td></tr>`}</tbody></table></div>
          </div>
        </div>
      </div>`;
  }

  async function startSelectedRun() {
    const tasks = selectedTaskIds();
    if (!tasks.length) return toast("先选至少一个任务");
    try {
      const body = {
        driver: state.driver, tasks, reps: Number(state.reps) || 1,
        force: state.force, run_id: state.runId.trim() || undefined,
      };
      const { run } = await api("/api/runs", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      state.launchRun = run;
      state.apiRuns = [run, ...(state.apiRuns || [])];
      render();
      toast(`已启动 ${run.id}`);
      pollRun(run.id);
    } catch (err) {
      toast(err.message);
    }
  }

  async function stopLaunchRun() {
    if (!state.launchRun) return;
    try {
      const { run } = await api(`/api/runs/${enc(state.launchRun.id)}/stop`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
      state.launchRun = { ...state.launchRun, ...run };
      render();
      toast("已发送停止信号");
    } catch (err) { toast(err.message); }
  }

  async function pollRun(id) {
    clearTimeout(state.pollTimer);
    try {
      const { run } = await api(`/api/runs/${enc(id)}`);
      state.launchRun = run;
      if (parseHash().page === "launch") render();
      if (run.status === "running" || run.status === "stopping") {
        state.pollTimer = setTimeout(() => pollRun(id), 1200);
      } else {
        await refreshApiRuns();
        if (run.status === "finished" && run.data_built) setTimeout(() => location.reload(), 1000);
        else toast(`运行 ${run.status}${run.build_error ? " · 数据重建失败" : ""}`);
      }
    } catch (err) {
      state.pollTimer = setTimeout(() => pollRun(id), 2000);
    }
  }

  // ---------- router ----------
  function render() {
    const { page, parts } = parseHash();
    activeNav(page);
    let html = "";
    if (page === "tasks") {
      if (parts[0]) {
        html = renderTask(parts[0]);
        crumbs([{ label: "任务", href: href("/tasks") }, { label: parts[0] }]);
      } else {
        html = renderTasks();
        crumbs([{ label: "任务" }]);
      }
    } else if (page === "runs") {
      if (parts[0]) {
        html = renderRun(parts[0]);
        crumbs([{ label: "运行", href: href("/runs") }, { label: parts[0] }]);
      } else {
        html = renderRuns();
        crumbs([{ label: "运行" }]);
      }
    } else if (page === "results") {
      html = renderResult(parts[0], parts[1], parts[2]);
      crumbs([
        { label: "运行", href: href("/runs") },
        { label: parts[0] || "", href: href(`/runs/${enc(parts[0] || "")}`) },
        { label: `${parts[1] || ""} · r${parts[2] || ""}` },
      ]);
    } else if (page === "launch") {
      html = renderLaunch();
      crumbs([{ label: "新建运行" }]);
    } else if (page === "compare") {
      html = renderCompare();
      crumbs([{ label: "对比" }]);
    } else {
      html = renderOverview();
      crumbs([{ label: "总览" }]);
    }
    view.innerHTML = html;
    const title = page === "overview" ? "总览" : page === "tasks" ? "任务" : page === "runs" ? "运行" : page === "launch" ? "新建运行" : page === "compare" ? "对比" : "结果";
    document.title = `${title} · Eval Console`;
    window.scrollTo(0, 0);
  }

  view.addEventListener("click", (event) => {
    const goEl = event.target.closest("[data-go]");
    if (goEl) { event.preventDefault(); go(goEl.dataset.go); return; }
    const cat = event.target.closest("[data-cat]");
    if (cat) { state.cat = cat.dataset.cat; render(); return; }
    const preset = event.target.closest("[data-preset-task]");
    if (preset) {
      event.preventDefault();
      state.selected = new Set([preset.dataset.presetTask]);
      go("/launch");
      return;
    }
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (action === "clear") { state.selected.clear(); syncPicks(); return; }
    if (action === "hardest") {
      const hardest = DATA.tasks.filter((t) => t.complexity === "advanced")
        .sort((a, b) => (b.level || 0) - (a.level || 0))[0];
      state.selected = new Set(hardest ? [hardest.id] : []);
      syncPicks(); return;
    }
    if (action === "apply-filter") {
      const catSel = view.querySelector('[data-filter="cat"]');
      const compSel = view.querySelector('[data-filter="comp"]');
      const cat = catSel ? catSel.value : "all";
      const comp = compSel ? compSel.value : "all";
      state.selected = new Set(DATA.tasks.filter((t) =>
        (cat === "all" || t.category === cat) && (comp === "all" || t.complexity === comp)
      ).map((t) => t.id));
      syncPicks(); return;
    }
    if (action === "start") { startSelectedRun(); return; }
    if (action === "stop") { stopLaunchRun(); return; }
    if (action === "refresh") { refreshApiRuns(); return; }
  });
  view.addEventListener("change", (event) => {
    const t = event.target;
    if (t.id === "complexity") { state.comp = t.value; render(); return; }
    if (t.id === "status") { state.status = t.value; render(); return; }
    if (t.matches("[data-task]")) {
      if (t.checked) state.selected.add(t.dataset.task); else state.selected.delete(t.dataset.task);
      updatePickedSummary(); return;
    }
    if (t.matches('[data-input="driver"]')) { state.driver = t.value; updatePickedSummary(); return; }
    if (t.matches('[data-input="reps"]')) { state.reps = Math.max(1, Math.min(10, Number(t.value) || 1)); updatePickedSummary(); return; }
    if (t.matches('[data-input="force"]')) { state.force = t.checked; updatePickedSummary(); return; }
  });
  view.addEventListener("input", (event) => {
    const t = event.target;
    if (t.matches('[data-input="run-id"]')) { state.runId = t.value; updatePickedSummary(); }
    if (t.matches('[data-input="reps"]')) { state.reps = Math.max(1, Math.min(10, Number(t.value) || 1)); updatePickedSummary(); }
  });
  search.addEventListener("input", (event) => {
    state.q = event.target.value.trim();
    render();
  });
  window.addEventListener("hashchange", render);
  if (!location.hash) location.hash = "#/overview";

  $("#built-at").textContent = DATA.generated_at ? `生成于 ${DATA.generated_at.slice(0, 16).replace("T", " ")}` : "暂无数据";
  $("#foot-at").textContent = DATA.generated_at ? DATA.generated_at.slice(0, 16).replace("T", " ") : "—";
  render();
  probeApi();
})();
