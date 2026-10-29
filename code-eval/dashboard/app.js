/* Read-only evaluation console. No network calls, no writes. */
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

  const state = { q: "", cat: "all", comp: "all" };
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
    if (n < 60) return `${n.toFixed(1)}s`;
    const m = Math.floor(n / 60);
    return `${m}m ${Math.round(n - m * 60)}s`;
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

  const VERDICT_LABEL = {
    pass: "PASS", failed: "FAILED", visible_tests_failed: "VISIBLE FAIL",
    scope_violation: "SCOPE", timeout: "TIMEOUT", blocked: "BLOCKED", error: "ERROR",
  };
  function verdictClass(v) {
    if (v === "pass") return "pass";
    if (v === "timeout" || v === "blocked" || v === "scope_violation") return "warn";
    return "fail";
  }
  function verdict(v) {
    return `<span class="status ${verdictClass(v)}">${esc(VERDICT_LABEL[v] || v || "—")}</span>`;
  }
  function statusDot(ok) {
    return `<span class="status ${ok ? "pass" : "fail"}">${ok ? "ok" : "fail"}</span>`;
  }
  function pill(text, cls = "") {
    return `<span class="pill ${cls}">${esc(text)}</span>`;
  }
  function tags(tags) {
    return (tags || []).map((t) => pill(t, "tag")).join(" ");
  }
  function catPill(cat) {
    return cat ? pill(cat, "cat") : "";
  }
  function compPill(comp) {
    if (!comp) return "";
    return pill(comp, comp === "advanced" ? "adv" : comp === "basic" ? "basic" : "");
  }
  function shortTool(name) {
    const s = String(name || "unknown");
    return s.length > 26 ? s.slice(0, 25) + "…" : s;
  }
  function shortRun(id) {
    return String(id || "").replace(/^\d{4}-\d{2}-\d{2}-/, "");
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
      <td><div class="id">${esc(r.task)}</div><div class="subline">${esc(r.title || tasksById.get(r.task)?.title || "")}</div></td>
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

    return `${head("LAB OVERVIEW", "评测控制台", "看任务、看运行、看每个结果是为什么过的；全部数据来自本地 runs/，页面只读。", `<span class="pill">${DATA.result_count} results</span>`)}
      <div class="kpis">
        <div class="kpi info"><div class="k">Tasks</div><div class="n">${DATA.task_count}</div><div class="d">${Object.keys(cats).length} 类 · ${DATA.tasks.filter((t) => t.complexity === "advanced").length} 个 advanced</div></div>
        <div class="kpi info"><div class="k">Runs</div><div class="n">${DATA.run_count}</div><div class="d">${new Set(DATA.runs.map((r) => r.tool)).size} 个工具配置</div></div>
        <div class="kpi good"><div class="k">Pass rate</div><div class="n">${rate}%</div><div class="d">${passed} / ${total} 次结果</div></div>
        <div class="kpi ${rate >= 90 ? "good" : "warn"}"><div class="k">Median time</div><div class="n">${fmtSec(median(allResults.map((r) => r.duration_s)))}</div><div class="d">中位耗时，不是上限</div></div>
      </div>

      <div class="grid-2">
        <div class="panel">
          <div class="panel-head"><h2>最近运行</h2><span class="hint">按日期倒序</span></div>
          <div class="tbl-wrap"><table>
            <thead><tr><th>运行</th><th>工具</th><th class="num">通过</th><th class="num">平均耗时</th><th class="num">token</th><th>进度</th></tr></thead>
            <tbody>${runRows || `<tr><td colspan="6">${empty("还没有 run", "先跑一次 code-eval，再重新生成 dashboard。")}</td></tr>`}</tbody>
          </table></div>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>任务分布</h2><span class="hint">${DATA.task_count} tasks</span></div>
          ${catRows || empty("没有任务", "tasks/*.json 为空。")}
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><h2>最近结果</h2><a class="dim mono" style="font-size:10px" href="${href("/runs")}">全部运行 →</a></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>判定</th><th>任务</th><th>工具</th><th class="num">耗时</th><th class="num">token</th></tr></thead>
          <tbody>${recent || `<tr><td colspan="5">${empty("还没有结果", "results/*.json 为空。")}</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  // ---------- tasks ----------
  function renderTasks() {
    const cats = ["all", ...Array.from(new Set(DATA.tasks.map((t) => t.category))).sort()];
    const comps = ["all", "basic", "intermediate", "advanced"];
    const q = state.q.toLowerCase();
    const list = DATA.tasks.filter((t) => {
      if (state.cat !== "all" && t.category !== state.cat) return false;
      if (state.comp !== "all" && t.complexity !== state.comp) return false;
      if (q) {
        const hay = `${t.id} ${t.title} ${t.category} ${t.complexity} ${(t.tags || []).join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const rows = list.map((t) => {
      const rs = taskResults(t.id);
      const s = statsOf(rs);
      const latest = rs[0];
      return `<tr class="click" data-go="${href(`/tasks/${enc(t.id)}`)}">
        <td class="num">L${esc(t.level)}</td>
        <td><div class="id">${esc(t.id)}</div><div class="subline">${esc(t.title)}</div></td>
        <td>${catPill(t.category)}</td>
        <td>${compPill(t.complexity)}</td>
        <td class="dim">${esc((t.tags || []).join(" · "))}</td>
        <td class="num">${s.passed}/${s.total}</td>
        <td>${latest ? verdict(latest.verdict) : `<span class="dim">未跑</span>`}</td>
      </tr>`;
    }).join("");

    const chips = cats.map((c) => `<button class="chip ${state.cat === c ? "on" : ""}" data-cat="${esc(c)}">${esc(c === "all" ? "全部" : c)}</button>`).join("");
    const opts = comps.map((c) => `<option value="${esc(c)}" ${state.comp === c ? "selected" : ""}>${esc(c === "all" ? "全部难度" : c)}</option>`).join("");

    return `${head("TASK CATALOG", "任务", "13 个任务的题面、需求映射和历史结果。点任意一行看细节。", `<span class="pill">${list.length} / ${DATA.tasks.length}</span>`)}
      <div class="panel">
        <div class="toolbar">
          <div class="left"><div class="chips">${chips}</div><select id="complexity">${opts}</select></div>
          <div class="right">按 level 排序</div>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr><th class="num">L</th><th>任务</th><th>分类</th><th>难度</th><th>标签</th><th class="num">通过</th><th>最近</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="7">${empty("没有匹配任务", "换个分类或清空搜索。")}</td></tr>`}</tbody>
        </table></div>
      </div>`;
  }

  function renderTask(id) {
    const t = tasksById.get(id);
    if (!t) return `${empty("找不到任务", id)}`;
    const rs = taskResults(id);
    const s = statsOf(rs);
    const attempts = rs.map((r) => `<tr class="click" data-go="${href(`/results/${enc(r.runId)}/${enc(r.task)}/${enc(r.rep)}`)}">
      <td class="id" title="${esc(r.runId)}">${esc(shortRun(r.runId))}</td>
      <td>${esc(shortTool(r.runTool))}</td>
      <td class="num">r${esc(r.rep)}</td>
      <td>${verdict(r.verdict)}</td>
      <td class="num">${fmtSec(r.duration_s)}</td>
    </tr>`).join("");

    const latest = rs[0];
    const reqs = (t.requirements || []).map((r) => {
      const met = latest ? (latest.requirements || []).find((y) => y.id === r.id)?.met : null;
      return `<div class="req-row">
        <div class="req-id">${esc(r.id)}</div>
        <div><div>${esc(r.text)}</div><div class="req-tests">${esc((r.tests || []).join(" · "))}</div></div>
        <div class="req-state">${met === true ? `<span class="status pass">met</span>` : met === false ? `<span class="status fail">missing</span>` : `<span class="dim">—</span>`}</div>
      </div>`;
    }).join("");

    return `${head("TASK", t.title, t.id, `<span class="pill">L${esc(t.level)}</span>`)}
      <a class="back" href="${href("/tasks")}">← 任务目录</a>
      <div class="meta">
        <div><div class="k">Level</div><div class="v">L${esc(t.level)}</div></div>
        <div><div class="k">Category</div><div class="v">${esc(t.category)}</div></div>
        <div><div class="k">Complexity</div><div class="v">${esc(t.complexity)}</div></div>
        <div><div class="k">Timebox</div><div class="v">${esc(t.timebox_s || "—")}s</div></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>题面</h2><div>${tags(t.tags)}</div></div><div class="prompt">${esc(t.prompt || "（题面文件为空）")}</div></div>
      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>需求映射</h2><span class="hint">${latest ? `最近 ${latest.runId} · r${latest.rep}` : `${(t.requirements || []).length} requirements`}</span></div>${reqs || `<div class="dim">没有 requirements。</div>`}</div>
        <div class="panel"><div class="panel-head"><h2>历史尝试</h2><span class="hint">${s.passed}/${s.total} pass</span></div>
          <div class="tbl-wrap"><table><thead><tr><th>运行</th><th>工具</th><th class="num">次</th><th>判定</th><th class="num">耗时</th></tr></thead>
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
    return `${head("RUNS", "运行", "每个 run 是一组任务 × 次数。点进去看逐条结果。", `<span class="pill">${list.length} runs</span>`)}
      <div class="panel">
        <div class="tbl-wrap"><table>
          <thead><tr><th>运行</th><th>日期</th><th>工具</th><th class="num">通过</th><th class="num">平均耗时</th><th class="num">token</th><th>进度</th></tr></thead>
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
        <td><div class="id">${esc(r.task)}</div><div class="subline">${esc(r.title || "")}</div></td>
        <td class="num">r${esc(r.rep)}</td>
        <td>${verdict(r.verdict)}</td>
        <td class="num">${met}/${reqs.length || "—"}</td>
        <td class="num">${r.accept?.passed ?? "—"}/${r.accept?.total ?? "—"}</td>
        <td class="num">${fmtSec(r.duration_s)}</td>
        <td class="num">${fmtTok((r.usage || {}).total_tokens)}</td>
      </tr>`;
    }).join("");
    return `${head("RUN", run.id, run.tool, `<span class="pill">${run.date || ""}</span>`)}
      <a class="back" href="${href("/runs")}">← 运行列表</a>
      <div class="kpis">
        <div class="kpi info"><div class="k">Results</div><div class="n">${s.total}</div><div class="d">${run.results.length} 个尝试</div></div>
        <div class="kpi good"><div class="k">Pass</div><div class="n">${s.passed}/${s.total}</div><div class="d">${s.rate}%</div></div>
        <div class="kpi info"><div class="k">Avg time</div><div class="n">${fmtSec(s.duration)}</div><div class="d">平均每次</div></div>
        <div class="kpi info"><div class="k">Tokens</div><div class="n">${fmtTok(s.tokens)}</div><div class="d">有记录时的平均</div></div>
      </div>
      <div class="panel"><div class="panel-head"><h2>逐条结果</h2><span class="hint">点行看 requirement / 隐藏验收 / diff</span></div>
        <div class="tbl-wrap"><table>
          <thead><tr><th class="num">L</th><th>任务</th><th class="num">次</th><th>判定</th><th class="num">需求</th><th class="num">隐藏</th><th class="num">耗时</th><th class="num">token</th></tr></thead>
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
        <div class="req-id">${esc(x.id)}</div>
        <div><div>${esc(x.text)}</div><div class="req-tests">${esc((x.tests || []).join(" · "))}${failed ? ` · failed: ${esc(failed)}` : ""}${missing ? ` · missing: ${esc(missing)}` : ""}</div></div>
        <div class="req-state">${x.met ? `<span class="status pass">met</span>` : `<span class="status fail">missing</span>`}</div>
      </div>`;
    }).join("");
    const acceptRows = (r.accept?.tests || []).map((t) => `<tr><td class="id">${esc(t.test)}</td><td>${statusDot(t.status === "passed")}</td></tr>`).join("");
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

    return `${head("RESULT", `${r.task} · r${r.rep}`, r.title || "", `<span class="pill">${esc(r.runTool)}</span>`)}
      <a class="back" href="${href(`/runs/${enc(runId)}`)}">← ${esc(runId)}</a>
      <div class="panel" style="border-left:3px solid var(--${verdictClass(r.verdict) === "pass" ? "green" : verdictClass(r.verdict) === "warn" ? "amber" : "red"})">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap">
          <div><div class="eyebrow">VERDICT</div><div style="font:600 22px var(--mono);margin:2px 0 5px">${verdict(r.verdict)}</div><div class="dim">${esc(r.reason || "")}</div></div>
          <div class="mono dim" style="font-size:10px;text-align:right">${esc(r.started || "")}<br>${esc(r.workdir_name || "")}</div>
        </div>
      </div>
      <div class="meta">
        <div><div class="k">Task</div><div class="v">${esc(r.task)}</div></div>
        <div><div class="k">Level</div><div class="v">L${esc(r.level)} · ${esc(r.rep)}</div></div>
        <div><div class="k">Duration</div><div class="v">${fmtSec(r.duration_s)}</div></div>
        <div><div class="k">Tokens</div><div class="v">${fmtTok((r.usage || {}).total_tokens)}</div></div>
      </div>

      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>需求</h2><span class="hint">${met}/${reqs.length} met</span></div>${reqHtml || `<div class="dim">没有 requirements 记录。</div>`}</div>
        <div class="panel"><div class="panel-head"><h2>验收与检查</h2><span class="hint">${testsOk ? "hidden all pass" : "hidden has failures"}</span></div>
          <div class="check-grid">
            ${checkCard("Hidden acceptance", testsOk, `${r.accept?.passed ?? "—"}/${r.accept?.total ?? "—"}`, `rc=${r.accept?.rc ?? "—"} · ${fmtSec(r.accept?.seconds)}`)}
            ${checkCard("Visible tests", visibleOk, visibleOk ? "rc=0" : `rc=${r.visible?.rc ?? "—"}`, `${fmtSec(r.visible?.seconds)}`)}
            ${checkCard("Clean clone", cloneOk, cloneOk ? "可复现" : "失败", r.deliverable?.failed?.length ? r.deliverable.failed.join(" · ") : "")}
            ${checkCard("Scope", scopeOk, scopeOk ? "干净" : "有越界", scopeIssues.length ? scopeIssues.join(" · ") : "forbidden / outside / tamper 均空")}
            ${checkCard("Usable", qualityOk, qualityOk ? "可直接用" : "有残留", qualityIssues.length ? qualityIssues.join(" · ") : "无多余文件 / 调试标记 / 未声明依赖")}
            ${checkCard("Claims", claimsHard.length === 0 ? (claimsSoft.length ? null : true) : false, claimsHard.length ? `${claimsHard.length} 处改未提到` : (claimsSoft.length ? `${claimsSoft.length} 处提到未改` : "对得上"), `提到未改 ${claimsSoft.length} · 改未提到 ${claimsHard.length}`)}
          </div>
          <div style="margin-top:12px" class="mono dim">changes: +${esc(changes.lines_added ?? 0)} / −${esc(changes.lines_removed ?? 0)} · files: ${esc((changes.modified || []).length + (changes.added || []).length)}</div>
          ${failures ? `<div style="margin-top:12px"><div class="k dim" style="font-size:9px;text-transform:uppercase">Hidden failures</div><ul class="list">${failures}</ul></div>` : ""}
        </div>
      </div>

      <div class="grid-2">
        <div class="panel"><div class="panel-head"><h2>隐藏验收</h2><span class="hint">${(r.accept?.tests || []).length} tests</span></div>
          <div class="tbl-wrap"><table><thead><tr><th>test</th><th>status</th></tr></thead><tbody>${acceptRows || `<tr><td colspan="2" class="dim">没有逐测试记录。</td></tr>`}</tbody></table></div>
        </div>
        <div class="panel"><div class="panel-head"><h2>改动与声明</h2><span class="hint">claims 对账</span></div>
          <div class="check-grid">
            ${checkCard("Mentioned, not changed", (claims.mentioned_not_changed || []).length === 0 ? true : null, (claims.mentioned_not_changed || []).join(" · ") || "无", "提到不等于改过，不单独判失败")}
            ${checkCard("Changed, not mentioned", (claims.changed_not_mentioned || []).length === 0, (claims.changed_not_mentioned || []).join(" · ") || "无", "")}
          </div>
          <div style="margin-top:12px"><div class="k dim" style="font-size:9px;text-transform:uppercase">Touched files</div>
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
      return `<tr><td class="task-cell"><a href="${href(`/tasks/${enc(t.id)}`)}"><span class="id">${esc(t.id)}</span><div class="subline">${esc(t.title)}</div></a></td>${cells}</tr>`;
    }).join("");
    const heads = tools.map((tool) => `<th title="${esc(tool)}">${esc(shortTool(tool))}</th>`).join("");
    return `${head("COMPARE", "工具 × 任务", "同一任务在不同工具配置下的通过次数。绿=全过，黄=部分，红=没过。", `<span class="pill">${tools.length} tools</span>`)}
      <div class="panel" style="overflow:auto">
        <table class="matrix"><thead><tr><th>任务</th>${heads}</tr></thead><tbody>${rows}</tbody></table>
      </div>
      <p class="dim mono" style="font-size:10px">单元格 = 通过次数 / 尝试次数；同一工具多次 run 会合并。不是统计显著性，只是当前样本。</p>`;
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
    } else if (page === "compare") {
      html = renderCompare();
      crumbs([{ label: "对比" }]);
    } else {
      html = renderOverview();
      crumbs([{ label: "总览" }]);
    }
    view.innerHTML = html;
    const title = page === "overview" ? "总览" : page === "tasks" ? "任务" : page === "runs" ? "运行" : page === "compare" ? "对比" : "结果";
    document.title = `${title} · Eval Console`;
    window.scrollTo(0, 0);
  }

  view.addEventListener("click", (event) => {
    const goEl = event.target.closest("[data-go]");
    if (goEl) { event.preventDefault(); go(goEl.dataset.go); return; }
    const cat = event.target.closest("[data-cat]");
    if (cat) { state.cat = cat.dataset.cat; render(); return; }
  });
  view.addEventListener("change", (event) => {
    if (event.target.id === "complexity") { state.comp = event.target.value; render(); }
  });
  search.addEventListener("input", (event) => {
    state.q = event.target.value.trim();
    render();
  });
  window.addEventListener("hashchange", render);
  if (!location.hash) location.hash = "#/overview";

  $("#built-at").textContent = DATA.generated_at ? `generated ${DATA.generated_at.slice(0, 16).replace("T", " ")}` : "no data";
  $("#foot-at").textContent = DATA.generated_at ? DATA.generated_at.slice(0, 16).replace("T", " ") : "—";
  render();
})();
