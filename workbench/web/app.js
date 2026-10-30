/*
 * Walkthrough Workbench — vanilla JS, no build step.
 *
 * The page is served with a per-process token in <meta name="wb-token">;
 * every write must send it back in X-WB-Token. The API key is write-only
 * from here: the server never returns it.
 */
"use strict";

const TOKEN = document.querySelector('meta[name="wb-token"]').content;
const view = document.getElementById("view");
const crumbs = document.getElementById("crumbs");
const toastEl = document.getElementById("toast");

let STATE = null;
let timer = null;
let beat = null;

/* ---------- helpers ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(message, bad) {
  toastEl.textContent = message;
  toastEl.classList.toggle("bad", !!bad);
  toastEl.classList.add("show");
  clearTimeout(toastEl._t);
  toastEl._t = setTimeout(() => toastEl.classList.remove("show"), 4200);
}

async function api(path, options = {}) {
  const opts = { headers: {}, ...options };
  if (options.body !== undefined) {
    opts.method = options.method || "POST";
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.body);
  }
  if (opts.method && opts.method !== "GET") opts.headers["X-WB-Token"] = TOKEN;
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function stopPolling() {
  if (timer) { clearInterval(timer); timer = null; }
}

function poll(fn, ms = 2000) {
  stopPolling();
  fn();
  timer = setInterval(fn, ms);
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function fmtDur(seconds) {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
}

function statusChip(status) {
  const label = {
    running: "运行中", finished: "已完成", failed: "失败",
    stopped: "已停止", interrupted: "中断",
  }[status] || status || "—";
  return `<span class="status ${esc(status)}">${esc(label)}</span>`;
}

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

/* ---------- boot ---------- */

async function loadState() {
  STATE = await api("/api/state");
  const cfg = STATE.config;
  const dot = document.getElementById("llm-dot");
  dot.className = cfg.configured ? "on" : "off";
  document.getElementById("llm-foot").textContent = cfg.configured
    ? `key 已配置 ${cfg.key_hint} · ${cfg.model}`
    : "未配置 key";
  document.getElementById("cfg-path").textContent = cfg.path;
  document.getElementById("foot-cfg").textContent = cfg.path;
}

/* ---------- settings ---------- */

function viewSettings() {
  const cfg = STATE.config;
  crumbs.textContent = "设置";
  const placeholder = cfg.configured ? `已保存 ${cfg.key_hint}（留空表示不修改）` : "sk-...";
  view.innerHTML = `
    <h1>模型接入</h1>
    <p class="sub">这一页写的是本地配置文件，权限 0600，不进仓库、不进运行目录。
      浏览器只会拿回“是否已配置”和末四位，拿不到 key 原文。</p>
    <div class="grid">
      <div class="card">
        <h2>OpenAI-compatible endpoint</h2>
        <p class="hint">任何兼容 <code>/chat/completions</code> 的网关都可以；走查操作员需要模型支持图片输入。</p>
        <label class="field"><span>Base URL <b>*</b></span>
          <input id="f-base" type="text" value="${esc(cfg.base_url)}" placeholder="https://api.openai.com/v1">
        </label>
        <div class="row">
          <label class="field"><span>模型 <b>*</b></span>
            <input id="f-model" type="text" value="${esc(cfg.model)}" placeholder="gpt-4o-mini">
          </label>
          <label class="field"><span>超时（秒）</span>
            <input id="f-timeout" type="number" min="1" step="1" value="${esc(cfg.timeout)}">
          </label>
        </div>
        <label class="field"><span>API key</span>
          <input id="f-key" type="password" autocomplete="off" spellcheck="false"
                 placeholder="${esc(placeholder)}">
        </label>
        <div class="actions">
          <button class="primary" id="save">保存到本地</button>
          <button id="test">测试连接</button>
          <span class="tiny" style="margin:0">测试只发一条 8 token 的 ping</span>
        </div>
        <div class="note">配置文件：<code>${esc(cfg.path)}</code><br>
          key 通过子进程环境变量传给 <code>wt.py agent</code>，不写在命令行、不写进 job 记录。</div>
      </div>
      <div class="card">
        <h2>当前状态</h2>
        <p class="hint">没配置时「走查」页会拒绝启动。</p>
        <table>
          <tr><th>endpoint</th><td class="mono">${esc(cfg.base_url)}</td></tr>
          <tr><th>模型</th><td class="mono">${esc(cfg.model)}</td></tr>
          <tr><th>key</th><td>${cfg.configured ? `已配置 <code>${esc(cfg.key_hint)}</code>` : "未配置"}</td></tr>
          <tr><th>文件</th><td class="mono">${esc(cfg.path)}</td></tr>
        </table>
        <div class="note warn">换机器或给别人用时，直接带走这个文件即可；不要把文件提交进 git。</div>
      </div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="log-head" style="margin-bottom:6px">
        <div><h2>环境自检</h2>
          <p class="hint" style="margin:0">跑之前先看这里：依赖、调试端口、桌面工具、key。</p></div>
        <div class="actions" style="margin:0">
          <button class="ghost" id="doctor-refresh">重新检查</button>
          <button class="primary" id="dep-install" style="display:none">安装依赖</button>
        </div>
      </div>
      <div id="doctor"><div class="empty">检查中…</div></div>
    </div>
    <div class="card" style="margin-top:18px">
      <div class="log-head" style="margin-bottom:6px">
        <div><h2>被测应用</h2>
          <p class="hint" style="margin:0">工作台可以带调试端口启动它们；重启会关掉当前窗口，先保存。</p></div>
      </div>
      <div id="apps"><div class="empty">检查中…</div></div>
    </div>`;

  document.getElementById("save").onclick = async () => {
    const body = {
      base_url: document.getElementById("f-base").value.trim(),
      model: document.getElementById("f-model").value.trim(),
      timeout: document.getElementById("f-timeout").value,
    };
    const key = document.getElementById("f-key").value.trim();
    if (key) body.api_key = key;
    try {
      await api("/api/config", { body });
      await loadState();
      route();
      toast("已保存");
    } catch (err) {
      toast(err.message, true);
    }
  };

  const loadDoctor = async () => {
    const box = document.getElementById("doctor");
    if (!box) return;
    box.innerHTML = `<div class="empty">检查中…</div>`;
    try {
      const data = await api("/api/doctor");
      box.innerHTML = data.checks.map((c) => `
        <div class="check-row">
          <span class="dot ${c.ok ? "on" : "off"}"></span>
          <div>
            <div>${esc(c.label)}</div>
            <div class="tiny">${esc(c.detail)}</div>
            ${c.fix ? `<div class="tiny mono">${esc(c.fix)}</div>` : ""}
          </div>
        </div>`).join("");
      const dep = data.checks.find((c) => c.id === "deps" && !c.ok);
      document.getElementById("dep-install").style.display = dep ? "" : "none";
      renderApps(data.apps);
    } catch (err) {
      box.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    }
  };
  const renderApps = (list) => {
    const box = document.getElementById("apps");
    if (!box) return;
    box.innerHTML = (list || []).map((a) => {
      let button;
      if (!a.installed) {
        button = `<button disabled>未安装</button>`;
      } else if (a.port_open) {
        button = `<button disabled>已就绪</button>`;
      } else if (a.running) {
        button = `<button class="danger" data-app="${esc(a.id)}" data-restart="1">重启并开端口</button>`;
      } else {
        button = `<button class="primary" data-app="${esc(a.id)}">启动</button>`;
      }
      const state = a.port_open ? "调试端口已监听"
        : a.running ? `运行中（PID ${a.pid}），没带调试端口`
        : "未运行";
      return `<div class="check-row">
        <span class="dot ${a.port_open ? "on" : "off"}"></span>
        <div style="flex:1">
          <div>${esc(a.label)} <span class="dim mono">:${a.port}</span></div>
          <div class="tiny">${esc(state)}${a.installed ? "" : " · 没找到可执行文件"}</div>
        </div>
        <div>${button}</div>
      </div>`;
    }).join("") || `<div class="empty">没有可管理的应用</div>`;

    box.querySelectorAll("button[data-app]").forEach((btn) => {
      btn.onclick = async () => {
        const restart = btn.dataset.restart === "1";
        if (restart && !confirm("会关闭当前窗口（未保存的内容可能丢失）。继续？")) return;
        btn.disabled = true;
        const label = btn.textContent;
        btn.textContent = "启动中…";
        try {
          await api(`/api/apps/${btn.dataset.app}/launch`, { body: { restart } });
          toast("调试端口已就绪");
        } catch (err) {
          toast(err.message, true);
          btn.textContent = label;
          btn.disabled = false;
        }
        await loadDoctor();
        await loadState();
      };
    });
  };

  document.getElementById("doctor-refresh").onclick = loadDoctor;
  document.getElementById("dep-install").onclick = async (event) => {
    const button = event.target;
    button.disabled = true;
    button.textContent = "安装中…（可能需要 1 分钟）";
    try {
      const res = await api("/api/deps/install", { body: {} });
      toast(res.ok ? "依赖已装到 workbench/.deps" : "安装失败，看下方输出", !res.ok);
      const box = document.getElementById("doctor");
      if (!res.ok && box) box.innerHTML = `<pre class="log">${esc(res.log || "no output")}</pre>`;
      await loadDoctor();
      await loadState();
    } catch (err) {
      toast(err.message, true);
    } finally {
      button.disabled = false;
      button.textContent = "安装依赖";
    }
  };
  loadDoctor();

  document.getElementById("test").onclick = async (event) => {
    const button = event.target;
    button.disabled = true;
    try {
      const key = document.getElementById("f-key").value.trim();
      const data = await api("/api/config/test", { body: key ? { api_key: key } : {} });
      toast(`连通：${data.model} · ${data.elapsed_s}s`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      button.disabled = false;
    }
  };
}

/* ---------- walkthrough ---------- */

function viewWalkthrough() {
  crumbs.textContent = "走查";
  const d = STATE.defaults;
  const cfg = STATE.config;
  const running = STATE.jobs.find((j) => j.status === "running");
  view.innerHTML = `
    <h1>发起一次走查</h1>
    <p class="sub">工作台只负责起进程、记日志、收产物；方法本身仍然按 <code>docs/METHOD.md</code> 走。
      操作员每步看截图决定下一个动作，所以需要模型支持图片输入。</p>
    ${cfg.configured ? "" : `<div class="note warn">还没配置 key，先去 <a href="#/settings"><u>设置</u></a>。</div>`}
    <div class="grid">
      <div class="card">
        <h2>目标</h2>
        <p class="hint">写成可验收的一句话：完成什么、记录什么异常。</p>
        <label class="field"><span>这次要走查什么 <b>*</b></span>
          <textarea id="w-goal" placeholder="例如：打开对话页，发送一条消息，检查生成失败时是否有可读的错误提示">完成一次完整走查：打开对话、发一条消息、记录异常</textarea>
        </label>
        <div class="row">
          <label class="field"><span>后端</span>
            <select id="w-backend">
              <option value="cdp">CDP（Chromium / Electron）</option>
              <option value="desktop">桌面（Linux X11）</option>
            </select>
          </label>
          <label class="field"><span>调试端口</span>
            <input id="w-port" type="number" min="1" max="65535" value="${d.port}">
          </label>
          <label class="field"><span>最多步数</span>
            <input id="w-steps" type="number" min="1" max="50" value="${d.max_steps}">
          </label>
        </div>
        <label class="field"><span>run id（可选）</span>
          <input id="w-runid" type="text" placeholder="留空自动生成，如 2026-10-29-myapp">
        </label>
        <label class="check"><input id="w-dry" type="checkbox"> 只观察不点击（dry-run，先验证连通性）</label>
        <div class="actions">
          <button class="primary" id="w-start" ${cfg.configured ? "" : "disabled"}>开始走查</button>
          <button class="ghost" id="w-hint">看准备条件</button>
        </div>
        <div class="note">CDP 后端需要被测应用已带 <code>--remote-debugging-port=${d.port}</code> 启动；
          桌面后端需要当前用户有可用的 X display。</div>
      </div>
      <div class="card">
        <h2>流程位置</h2>
        <p class="hint">这一步在 METHOD 的 Step 3–5；工作台不替你设计任务矩阵。</p>
        <table>
          <tr><th>0 调研</th><td><code>runs/&lt;run&gt;/tool-profile.md</code></td></tr>
          <tr><th>1 预检</th><td><code>wt.py preflight</code></td></tr>
          <tr><th>2 页面地图</th><td><code>wt.py coverage</code></td></tr>
          <tr><th>3 任务</th><td><code>task-plan.md</code></td></tr>
          <tr><th>4 执行</th><td>本页启动的 operator</td></tr>
          <tr><th>5 报告</th><td><code>wt.py report</code></td></tr>
          <tr><th>6 审计</th><td><code>wt.py audit</code></td></tr>
        </table>
        ${running ? `<div class="note warn">有一个 run 在跑：<a href="#/jobs/${esc(running.id)}"><u>${esc(running.id)}</u></a>；先停掉再开新的。</div>` : ""}
      </div>
    </div>`;

  document.getElementById("w-hint").onclick = () =>
    toast("1) 被测应用带调试端口启动 2) 配置 key 3) 先勾 dry-run 跑 2 步");

  document.getElementById("w-start").onclick = async (event) => {
    const button = event.target;
    button.disabled = true;
    try {
      const body = {
        kind: "walkthrough",
        goal: document.getElementById("w-goal").value.trim(),
        backend: document.getElementById("w-backend").value,
        port: Number(document.getElementById("w-port").value),
        max_steps: Number(document.getElementById("w-steps").value),
        dry_run: document.getElementById("w-dry").checked,
        run_id: document.getElementById("w-runid").value.trim() || undefined,
      };
      const data = await api("/api/jobs", { body });
      go(`#/jobs/${data.job.id}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      button.disabled = false;
    }
  };
}

/* ---------- eval ---------- */

function viewEval() {
  crumbs.textContent = "评测";
  const tasks = STATE.tasks;
  const drivers = STATE.drivers;
  const byCategory = {};
  for (const task of tasks) (byCategory[task.category || "other"] ||= []).push(task);

  view.innerHTML = `
    <h1>跑编码评测</h1>
    <p class="sub">选驱动器和任务，工作台调 <code>run_tool.py</code> 起一轮；
      判分仍在进程外由 <code>grade.py</code> 完成。这里的 key 只供走查操作员使用，
      外部 CLI 用自己的登录态。</p>
    <div class="grid">
      <div class="card">
        <h2>任务</h2>
        <p class="hint">${tasks.length} 个任务；不选就不会跑。</p>
        <div class="actions" style="margin:-4px 0 10px">
          <button class="ghost" id="e-all">全选</button>
          <button class="ghost" id="e-none">清空</button>
          <span class="tiny" id="e-count" style="margin:0">已选 0</span>
        </div>
        <div class="task-list" id="e-tasks">
          ${Object.keys(byCategory).map((cat) => `
            <div class="dim mono" style="padding:6px 8px 2px">${esc(cat)}</div>
            ${byCategory[cat].map((task) => `
              <label class="task">
                <input type="checkbox" value="${esc(task.id)}" data-cat="${esc(cat)}">
                <span><span class="t">${esc(task.title)}</span>
                  <span class="m">L${esc(task.level ?? "—")} · ${esc(task.complexity || "")} · ${esc(task.id)}</span></span>
              </label>`).join("")}
          `).join("")}
        </div>
      </div>
      <div class="card">
        <h2>怎么跑</h2>
        <label class="field"><span>驱动器</span>
          <select id="e-driver">
            ${drivers.map((d) => `<option value="${esc(d.id)}" ${d.available ? "" : "disabled"}
              data-why="${esc(d.why || "")}">${esc(d.label)}${d.available ? "" : "（不可用）"}</option>`).join("")}
          </select>
        </label>
        <div class="tiny" id="e-driver-hint" style="margin:-8px 0 12px"></div>
        <div class="row">
          <label class="field"><span>重复次数</span>
            <input id="e-reps" type="number" min="1" max="10" value="1">
          </label>
          <label class="field"><span>run id（可选）</span>
            <input id="e-runid" type="text" placeholder="自动生成">
          </label>
        </div>
        <label class="check"><input id="e-force" type="checkbox"> --force（覆盖已有产物）</label>
        <label class="check" id="e-skipws-wrap" style="display:none">
          <input id="e-skipws" type="checkbox"> 工作区已手动建好（Qoder：跳过建工作区）
        </label>
        <div class="actions" style="margin-bottom:6px">
          <button class="ghost" id="e-openws" type="button">重新在 Qoder 打开任务目录</button>
        </div>
        <div class="tiny" id="e-openws-hint" style="margin:-4px 0 10px">
          不用先点这个：开始评测时会自动建好目录并打开。这里只用于提前看一眼或重新打开。
        </div>
        <div class="actions"><button class="primary" id="e-start">开始评测</button></div>
        <div class="note">外部 CLI 的 key 不在这个页面配置：Codex 读 <code>~/.codex/</code>，
          TRAE / Cursor / Qoder 用各自登录态。</div>
      </div>
    </div>`;

  const driverSelect = document.getElementById("e-driver");
  const driverHint = document.getElementById("e-driver-hint");
  const firstUsable = Array.from(driverSelect.options).find((o) => !o.disabled);
  if (firstUsable) driverSelect.value = firstUsable.value;
  // 端口 / 类型 / 页面开关都来自 /api/state，这里不再抄一份工具清单。
  const driverById = (id) => drivers.find((d) => d.id === id);
  const hasFeature = (d, name) => Boolean(d && (d.features || []).includes(name));
  const syncHint = () => {
    const option = driverSelect.selectedOptions[0];
    const driver = driverById(driverSelect.value);
    if (option && option.disabled) {
      driverHint.textContent = `不可用：${option.dataset.why || "环境不满足"}`;
    } else {
      driverHint.textContent = driver && driver.kind === "gui"
        ? `需要被测应用先带 --remote-debugging-port=${driver.port} 启动；工作台在启动前会探测这个端口`
        : "走 CLI，用自己的登录态，不需要调试端口";
    }
    const skipWrap = document.getElementById("e-skipws-wrap");
    const skipBox = document.getElementById("e-skipws");
    const wantsSkip = hasFeature(driver, "skip_workspace");
    if (skipWrap) skipWrap.style.display = wantsSkip ? "" : "none";
    // 工作区由工作台在起跑前打开，所以默认勾上「跳过驱动自建工作区」。
    if (skipBox && wantsSkip) skipBox.checked = true;
    const openWs = document.getElementById("e-openws");
    const openWsHint = document.getElementById("e-openws-hint");
    const wantsOpen = hasFeature(driver, "open_workspace");
    if (openWs) openWs.style.display = wantsOpen ? "" : "none";
    if (openWsHint) openWsHint.style.display = wantsOpen ? "" : "none";
  };
  driverSelect.onchange = syncHint;
  syncHint();

  const boxes = () => Array.from(document.querySelectorAll("#e-tasks input[type=checkbox]"));
  const count = () => {
    const n = boxes().filter((b) => b.checked).length;
    document.getElementById("e-count").textContent = `已选 ${n}`;
    return n;
  };
  boxes().forEach((box) => box.addEventListener("change", count));
  document.getElementById("e-all").onclick = () => { boxes().forEach((b) => b.checked = true); count(); };
  document.getElementById("e-none").onclick = () => { boxes().forEach((b) => b.checked = false); count(); };

  document.getElementById("e-openws").onclick = async (event) => {
    const picked = boxes().filter((b) => b.checked).map((b) => b.value);
    if (picked.length !== 1) return toast("先选且只选一个任务：一次只能打开一个工作区", true);
    const button = event.target;
    button.disabled = true;
    try {
      const res = await api("/api/apps/workspace-open", {
        body: {
          task: picked[0],
          run_id: document.getElementById("e-runid").value.trim() || undefined,
        },
      });
      document.getElementById("e-runid").value = res.run_id;
      document.getElementById("e-skipws").checked = true;
      toast(`已在 Qoder 打开 ${res.path}；run id 已填好，直接点开始评测`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      button.disabled = false;
    }
  };

  document.getElementById("e-start").onclick = async (event) => {
    const picked = boxes().filter((b) => b.checked).map((b) => b.value);
    if (!picked.length) return toast("至少选一个任务", true);
    const button = event.target;
    button.disabled = true;
    try {
      const data = await api("/api/jobs", {
        body: {
          kind: "eval",
          driver: document.getElementById("e-driver").value,
          tasks: picked,
          reps: Number(document.getElementById("e-reps").value),
          force: document.getElementById("e-force").checked,
          driver_args: (hasFeature(driverById(document.getElementById("e-driver").value), "skip_workspace")
            && document.getElementById("e-skipws").checked) ? ["--skip-workspace"] : [],
          run_id: document.getElementById("e-runid").value.trim() || undefined,
        },
      });
      go(`#/jobs/${data.job.id}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      button.disabled = false;
    }
  };
}

/* ---------- jobs ---------- */

function viewJobs() {
  crumbs.textContent = "运行";
  const rows = STATE.jobs.map((job) => `
    <tr class="click" data-id="${esc(job.id)}">
      <td>${statusChip(job.status)}</td>
      <td class="mono">${esc(job.id)}</td>
      <td>${esc(job.kind === "walkthrough" ? "走查" : "评测")}</td>
      <td>${esc(job.title || "")}</td>
      <td class="mono dim">${esc(fmtTime(job.started_at))}</td>
      <td class="mono">${esc(fmtDur(job.duration_s))}</td>
    </tr>`).join("");

  view.innerHTML = `
    <h1>运行记录</h1>
    <p class="sub">每条记录对应 runs/ 下的一个目录；点进去看日志和产物。</p>
    <div class="card">
      ${STATE.jobs.length ? `
      <table>
        <thead><tr><th>状态</th><th>run</th><th>类型</th><th>标题</th><th>开始</th><th>耗时</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>` : `<div class="empty">还没有运行记录。去「走查」或「评测」发起一次。</div>`}
    </div>`;

  view.querySelectorAll("tr.click").forEach((tr) => {
    tr.onclick = () => go(`#/jobs/${tr.dataset.id}`);
  });
}

/* ---------- job detail ---------- */

function viewJob(id) {
  crumbs.innerHTML = `运行 / <span class="mono">${esc(id)}</span>`;
  view.innerHTML = `<div class="empty">加载中…</div>`;
  let tab = "log";
  let lastLog = "";

  const draw = (detail) => {
    const job = detail.job;
    const files = detail.files || [];
    const meta = job.meta || {};
    const dialogInfo = detail.dialogs || { handled: 0, blocked: 0, unknown: 0, items: [] };
    const dialogTotal = (dialogInfo.handled || 0) + (dialogInfo.blocked || 0) + (dialogInfo.unknown || 0);
    const metaBits = job.kind === "walkthrough"
      ? [`后端 ${meta.backend || "cdp"}`, `端口 ${meta.port ?? "—"}`,
         `最多 ${meta.max_steps ?? "—"} 步`, meta.dry_run ? "dry-run" : ""]
      : [`驱动器 ${meta.driver || "—"}`, `${(meta.tasks || []).length} 个任务`,
         `×${meta.reps ?? 1}`];
    const images = files.filter((f) => f.image);
    const docs = files.filter((f) => !f.image);
    view.innerHTML = `
      <div class="log-head">
        <div>
          <h1 style="margin-bottom:4px">${esc(job.title || job.id)} ${statusChip(job.status)}</h1>
          <div class="tiny mono" style="margin:0">${esc(job.run_dir || "")} · 开始 ${esc(fmtTime(job.started_at))} ·
            ${esc(fmtDur(job.duration_s))} ${job.returncode != null ? `· exit ${job.returncode}` : ""}</div>
          <div class="tiny" style="margin:4px 0 0">${metaBits.filter(Boolean).map((b) => `<span class="pill">${esc(b)}</span>`).join(" ")}
            ${dialogTotal ? `<span class="pill" title="${esc(dialogInfo.items.map((i) => i.detail).join(" / "))}">弹窗 自动 ${dialogInfo.handled} · 需人工 ${dialogInfo.blocked + dialogInfo.unknown}</span>` : ""}</div>
        </div>
        <div class="actions" style="margin:0">
          ${job.status === "running" ? `<button class="danger" id="stop">停止</button>` : ""}
          <button class="ghost" id="back">返回列表</button>
        </div>
      </div>
      <div class="tabs">
        <button data-tab="log" class="${tab === "log" ? "on" : ""}">日志</button>
        <button data-tab="files" class="${tab === "files" ? "on" : ""}">产物 ${files.length}</button>
      </div>
      <div id="panel"></div>`;

    const panel = document.getElementById("panel");
    if (tab === "log") {
      panel.innerHTML = `<pre class="log" id="logbox">${esc(lastLog || "（暂无输出）")}</pre>`;
      const box = document.getElementById("logbox");
      box.scrollTop = box.scrollHeight;
    } else {
      panel.innerHTML = `
        ${images.length ? `<div class="card" style="margin-bottom:14px">
          <h2>截图</h2><p class="hint">点击看原图。</p>
          <div class="thumbs">${images.map((f) => `
            <figure>
              <a href="/api/jobs/file?path=${encodeURIComponent(f.path)}" target="_blank" rel="noopener">
                <img loading="lazy" src="/api/jobs/file?path=${encodeURIComponent(f.path)}" alt="${esc(f.name)}">
              </a>
              <figcaption>${esc(f.name)}</figcaption>
            </figure>`).join("")}</div>
        </div>` : ""}
        <div class="card">
          <h2>文件</h2>
          <p class="hint">只列出本次 run 目录下的文件。</p>
          <div class="files">
            ${docs.length ? docs.map((f) => `
              <a href="/api/jobs/file?path=${encodeURIComponent(f.path)}" target="_blank" rel="noopener">
                <span class="mono">${esc(f.path.replace(job.run_dir + "/", ""))}</span>
                <span class="dim mono">${Math.max(1, Math.round(f.size / 1024))} KB</span>
              </a>`).join("") : `<div class="empty">还没有产物</div>`}
          </div>
        </div>`;
    }

    view.querySelectorAll("[data-tab]").forEach((button) => {
      button.onclick = () => { tab = button.dataset.tab; draw(detail); };
    });
    const stopButton = document.getElementById("stop");
    if (stopButton) {
      stopButton.onclick = async () => {
        try {
          await api(`/api/jobs/${encodeURIComponent(job.id)}/stop`, { body: {} });
          toast("已发送停止信号");
        } catch (err) {
          toast(err.message, true);
        }
      };
    }
    document.getElementById("back").onclick = () => go("#/jobs");
  };

  const tick = async () => {
    try {
      const [detail, log] = await Promise.all([
        api(`/api/jobs/${encodeURIComponent(id)}`),
        api(`/api/jobs/${encodeURIComponent(id)}/log?lines=400`),
      ]);
      lastLog = log.log;
      draw(detail);
      if (detail.job.status !== "running") {
        stopPolling();
        loadState().catch(() => {});
      }
    } catch (err) {
      view.innerHTML = `<div class="card"><h2>读不到这个 run</h2>
        <p class="hint">${esc(err.message)}</p>
        <button class="ghost" onclick="location.hash='#/jobs'">返回列表</button></div>`;
      stopPolling();
    }
  };
  poll(tick, 2000);
}

/* ---------- router ---------- */

function route() {
  const raw = location.hash.replace(/^#\/?/, "").replace(/\/$/, "");
  const [head, id] = raw.split("/");
  const page = head || "settings";
  document.querySelectorAll("#nav a").forEach((a) => {
    const key = a.dataset.route;
    const active = key === page || (page === "jobs" && key === "jobs");
    a.classList.toggle("active", active);
  });
  stopPolling();
  if (page === "settings") return viewSettings();
  if (page === "walkthrough") return viewWalkthrough();
  if (page === "eval") return viewEval();
  if (page === "jobs") return id ? viewJob(id) : viewJobs();
  return viewSettings();
}

window.addEventListener("hashchange", route);
document.getElementById("refresh").onclick = async () => {
  try { await loadState(); route(); toast("已刷新"); }
  catch (err) { toast(err.message, true); }
};

(async () => {
  try {
    await loadState();
  } catch (err) {
    view.innerHTML = `<div class="card"><h2>连不上工作台服务</h2>
      <p class="hint">${esc(err.message)}</p></div>`;
    return;
  }
  if (!location.hash) location.hash = "#/settings";
  route();
  // keep the job list fresh on list-like pages
  beat = setInterval(async () => {
    try {
      await loadState();
      const raw = location.hash.replace(/^#\/?/, "");
      if (raw === "" || raw === "jobs") viewJobs();
    } catch (_) { /* ignore transient errors */ }
  }, 5000);
})();
