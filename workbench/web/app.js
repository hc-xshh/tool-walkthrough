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
const dialogEl = document.getElementById("dialog");
const toastStack = document.getElementById("toast-stack");

const DRAFT_KEY = "wb:drafts:v1";
const STATUS_LABEL = {
  running: "运行中", finished: "已完成", failed: "失败",
  stopped: "已停止", interrupted: "中断",
};
const KIND_LABEL = { discover: "接入", survey: "采集" };
const FEATURE_LABEL = { open_workspace: "打开任务目录", skip_workspace: "跳过建工作区" };
const FORM_LABEL = { cli: "CLI", ide: "IDE", plugin: "插件", cloud: "云", desktop: "桌面", work: "工作台", agent: "Agent", web: "Web" };
const MODEL_PRESETS = [
  { id: "deepseek", label: "DeepSeek", base: "https://api.deepseek.com", model: "deepseek-v4-flash", keyUrl: "https://platform.deepseek.com/api_keys" },
  { id: "openai", label: "OpenAI", base: "https://api.openai.com/v1", model: "gpt-4o-mini", keyUrl: "https://platform.openai.com/api-keys" },
  { id: "custom", label: "自定义（OpenAI-compatible）", base: "", model: "", keyUrl: "" },
];
const TOAST_PATH = {
  ok: '<path d="m5 12 4 4 10-9"/>',
  bad: '<path d="M12 8v5M12 17h.01"/><circle cx="12" cy="12" r="9"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
};

let STATE = null;
let current = { page: "config", id: "" };
let jobTimer = null;
let settingsDirty = false;
let jobsUI = { filter: "all", q: "" };
let detailState = null;
let DRAFT = readDrafts();

/* ---------- helpers ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function icon(path, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
}

function autoRunId(kind) {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}-${kind}`;
}

function toast(message, kind = "info") {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.innerHTML = `<span class="ic">${icon(TOAST_PATH[kind] || TOAST_PATH.info)}</span><span>${esc(message)}</span>`;
  toastStack.appendChild(node);
  setTimeout(() => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 180);
  }, 4200);
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

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("已复制到剪贴板", "ok");
  } catch (_) {
    const input = document.createElement("textarea");
    input.value = text;
    input.style.position = "fixed";
    input.style.opacity = "0";
    document.body.appendChild(input);
    input.select();
    try { document.execCommand("copy"); toast("已复制到剪贴板", "ok"); }
    catch (err) { toast("复制失败：" + err.message, "bad"); }
    finally { input.remove(); }
  }
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", { hour12: false });
}

function fmtShortTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}

function fmtRelative(iso) {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return "刚刚";
  if (s < 3600) return `${Math.floor(s / 60)} 分钟前`;
  if (s < 86400) return `${Math.floor(s / 3600)} 小时前`;
  return `${Math.floor(s / 86400)} 天前`;
}

function fmtDur(seconds) {
  if (seconds == null || Number.isNaN(Number(seconds))) return "—";
  const s = Math.max(0, Math.round(Number(seconds)));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

function fmtBytes(size) {
  const n = Number(size) || 0;
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function elapsed(job) {
  if (!job) return null;
  if (job.duration_s != null) return job.duration_s;
  if (job.status === "running" && job.started_at) {
    const t = new Date(job.started_at).getTime();
    if (!Number.isNaN(t)) return Math.max(0, (Date.now() - t) / 1000);
  }
  return null;
}

function statusChip(status) {
  const key = status || "pending";
  return `<span class="status ${esc(key)}">${esc(STATUS_LABEL[status] || status || "—")}</span>`;
}

function providerIdForBase(base) {
  const text = String(base || "").replace(/\/+$/, "");
  const hit = MODEL_PRESETS.find((p) => p.id !== "custom" && p.base
    && text.startsWith(p.base.replace(/\/+$/, "")));
  return hit ? hit.id : "custom";
}

function featureLabel(name) {
  return FEATURE_LABEL[name] || name;
}

function kindName(kind) {
  return KIND_LABEL[kind] || kind || "任务";
}

function runningJobs() {
  return (STATE?.jobs || []).filter((j) => j.status === "running");
}

function jobTitle(job) {
  if (!job) return "—";
  return job.title || job.id;
}

function jobSub(job) {
  const bits = [kindName(job.kind)];
  if (job.kind === "survey") {
    if (job.meta?.product?.name) bits.push(job.meta.product.name);
    if (job.meta?.scenario_id) bits.push(job.meta.scenario_id);
    if ((job.meta?.products || []).length) bits.push(`${job.meta.products.length} 个产品`);
  } else if (job.kind === "discover" && job.meta?.query) {
    bits.push(job.meta.query);
  }
  if (job.returncode != null && job.returncode !== 0) bits.push(`exit ${job.returncode}`);
  return bits.filter(Boolean);
}

function pageHead({ eyebrow, title, desc, actions = "" }) {
  return `<div class="page-head">
    <div>
      ${eyebrow ? `<p class="eyebrow">${esc(eyebrow)}</p>` : ""}
      <h1>${title}</h1>
      ${desc ? `<p>${desc}</p>` : ""}
    </div>
    ${actions ? `<div class="page-actions">${actions}</div>` : ""}
  </div>`;
}

function emptyState(text, sub = "", actions = "") {
  return `<div class="empty-box"><div class="empty"><strong>${esc(text)}</strong>
    ${sub ? `<span>${esc(sub)}</span>` : ""}
    ${actions ? `<div class="actions">${actions}</div>` : ""}
  </div></div>`;
}

function skeletonCard() {
  return `<div class="card">
    <span class="skeleton line w40"></span>
    <span class="skeleton line w80"></span>
    <span class="skeleton line w60"></span>
  </div>`;
}

function prettyPath(path) {
  const text = String(path || "");
  const home = text.match(/^\/home\/[^/]+/)?.[0];
  return home ? "~" + text.slice(home.length) : text;
}

function pathHtml(path) {
  return esc(prettyPath(path)).replace(/[\\/]/g, (sep) => sep + "<wbr>");
}

function absRunPath(job) {
  const path = String(job?.run_dir || "");
  if (!path) return "";
  if (/^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(path)) return path;
  return STATE?.repo?.root ? `${STATE.repo.root}/${path}` : path;
}

function relPath(job, file) {
  if (!file) return "";
  const path = String(file.path || "").replace(/\\/g, "/");
  const prefix = job?.run_dir ? String(job.run_dir).replace(/\\/g, "/").replace(/\/$/, "") + "/" : "";
  return prefix && path.startsWith(prefix) ? path.slice(prefix.length) : path;
}

function fileUrl(path) {
  return `/api/jobs/file?path=${encodeURIComponent(path)}`;
}

function isWorkspaceFile(file) {
  const p = String(file?.path || "").replace(/\\/g, "/");
  return /(^|\/)work\//.test(p) || /(^|\/)\.git\//.test(p)
    || /\.before\.json$/.test(p) || /\.meta\.json$/.test(p)
    || /(^|\/)\.workspace\.json$/.test(p);
}

const TEXT_EXT = new Set([
  "md", "json", "jsonl", "txt", "log", "py", "js", "mjs", "cjs", "ts", "tsx", "jsx",
  "css", "html", "yml", "yaml", "toml", "sh", "ini", "cfg", "csv", "xml", "sql",
]);

function isTextFile(file) {
  if (file?.text) return true;
  const name = String(file?.name || "").toLowerCase();
  return TEXT_EXT.has(name.includes(".") ? name.split(".").pop() : "");
}

function isImageFile(file) {
  return Boolean(file?.image);
}

function setCrumbs(html) {
  crumbs.innerHTML = html;
}

function setConn(ok) {
  const el = document.getElementById("conn");
  if (!el) return;
  el.classList.toggle("bad", !ok);
  el.querySelector("span").textContent = ok ? "已连接" : "连接中断";
}

function readDrafts() {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    const data = raw ? JSON.parse(raw) : {};
    return data && typeof data === "object" ? data : {};
  } catch (_) {
    return {};
  }
}

function persistDrafts() {
  try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(DRAFT)); } catch (_) { /* ignore */ }
}

/* ---------- modal ---------- */

function openModal(html, { narrow = false } = {}) {
  dialogEl.className = "modal" + (narrow ? " narrow" : "");
  dialogEl.innerHTML = html;
  dialogEl.setAttribute("tabindex", "-1");
  if (!dialogEl.open) dialogEl.showModal();
  dialogEl.focus();
}

function closeModal() {
  if (dialogEl.open) dialogEl.close();
}

function confirmAction({ title, message, confirmText = "确认", danger = false, onConfirm }) {
  openModal(`
    <div class="modal-head"><div><h2 id="dlg-title">${esc(title)}</h2></div></div>
    <div class="modal-body"><p>${esc(message)}</p></div>
    <div class="modal-foot">
      <button type="button" id="dlg-cancel">取消</button>
      <button type="button" id="dlg-ok" class="${danger ? "danger" : "primary"}">${esc(confirmText)}</button>
    </div>`, { narrow: true });
  const cancel = document.getElementById("dlg-cancel");
  const ok = document.getElementById("dlg-ok");
  cancel.onclick = closeModal;
  ok.onclick = () => { closeModal(); onConfirm(); };
  cancel.focus();
}

dialogEl.addEventListener("click", (event) => {
  if (event.target.closest?.("[data-close]")) { closeModal(); return; }
  if (event.target === dialogEl) closeModal();
});
dialogEl.addEventListener("close", () => { dialogEl.innerHTML = ""; });

function filePreviewModal(file, title, body, footnote = "") {
  openModal(`
    <div class="modal-head">
      <div><h2 id="dlg-title">${esc(title)}</h2><div class="sub">${pathHtml(file?.path || "")}</div></div>
      <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">${icon('<path d="M6 6l12 12M18 6 6 18"/>')}</button>
    </div>
    <div class="modal-body">${footnote ? `<p class="file-preview-note">${footnote}</p>` : ""}${body}</div>
    <div class="modal-foot">
      <button type="button" id="dlg-close">关闭</button>
      <button type="button" class="primary" id="dlg-open">新窗口打开</button>
    </div>`);
  document.getElementById("dlg-close").onclick = closeModal;
  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
  document.getElementById("dlg-open").onclick = () => {
    if (file?.path) window.open(fileUrl(file.path), "_blank", "noopener");
  };
}

async function openTextPreview(file) {
  if (!isTextFile(file)) {
    window.open(fileUrl(file.path), "_blank", "noopener");
    return;
  }
  if (Number(file.size) > 512 * 1024) {
    toast("文件较大，已用新窗口打开", "info");
    window.open(fileUrl(file.path), "_blank", "noopener");
    return;
  }
  filePreviewModal(file, file.name,
    `<pre class="modal-pre" id="preview-pre"><span class="spinner"></span></pre>`,
    "只读预览；文件不会上传到任何地方。");
  try {
    const res = await fetch(fileUrl(file.path));
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    let text = await res.text();
    if (file.name.endsWith(".json")) {
      try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (_) { /* keep raw */ }
    }
    const pre = document.getElementById("preview-pre");
    if (pre) pre.textContent = text || "（空文件）";
  } catch (err) {
    const pre = document.getElementById("preview-pre");
    if (pre) pre.textContent = `读取失败：${err.message}`;
  }
}

function openLightbox(files, index) {
  const list = files.filter((f) => isImageFile(f));
  if (!list.length) return;
  let at = index < 0 ? 0 : Math.max(0, Math.min(index, list.length - 1));
  const image = list[at];
  const nav = list.length > 1
    ? `<button type="button" class="ghost" id="img-prev" ${at === 0 ? "disabled" : ""}>上一张</button>
       <button type="button" class="ghost" id="img-next" ${at === list.length - 1 ? "disabled" : ""}>下一张</button>`
    : "";
  openModal(`
    <div class="modal-head">
      <div><h2 id="dlg-title">${esc(image.name)}</h2><div class="sub">${pathHtml(image.path)}</div></div>
      <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">${icon('<path d="M6 6l12 12M18 6 6 18"/>')}</button>
    </div>
    <div class="modal-body">
      <div class="image-view">
        <img id="lightbox-img" src="${esc(fileUrl(image.path))}" alt="${esc(image.name)}">
        <div class="image-meta">
          <span class="mono">${esc(relPath(detailState?.detail?.job || null, image) || image.path)}</span>
          <span>${at + 1} / ${list.length}</span>
        </div>
      </div>
    </div>
    <div class="modal-foot">${nav}<button type="button" class="primary" id="dlg-open">新窗口打开</button></div>`);
  document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
  document.getElementById("dlg-open").onclick = () => window.open(fileUrl(image.path), "_blank", "noopener");
  const show = (next) => { at = next; openLightbox(list, at); };
  const prev = document.getElementById("img-prev");
  const next = document.getElementById("img-next");
  if (prev) prev.onclick = () => show(at - 1);
  if (next) next.onclick = () => show(at + 1);
}

/* ---------- state / shell ---------- */

async function loadState() {
  const data = await api("/api/state");
  STATE = data;
  paintShell();
  return data;
}

function paintShell() {
  if (!STATE) return;
  setConn(true);
  const cfg = STATE.config;
  const dot = document.getElementById("llm-dot");
  if (dot) dot.className = cfg.configured ? "on" : "off";
  const foot = document.getElementById("llm-foot");
  if (foot) {
    foot.textContent = cfg.configured
      ? `${cfg.key_hint} · ${cfg.model}`
      : "未配置 key";
    foot.title = cfg.configured ? `已配置 ${cfg.key_hint} · ${cfg.model}` : "未配置 key";
  }

  const running = runningJobs();
  const badge = document.getElementById("nav-running");
  if (badge) {
    badge.textContent = String(running.length);
    badge.hidden = running.length === 0;
  }
  const pill = document.getElementById("running-pill");
  const count = document.getElementById("running-count");
  if (pill) pill.hidden = running.length === 0;
  if (count) count.textContent = String(running.length);
}

function paintNav(page) {
  document.querySelectorAll("#nav a").forEach((a) => {
    const active = a.dataset.route === page;
    a.classList.toggle("active", active);
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

function refreshStateTick() {
  if (document.visibilityState !== "visible") return;
  loadState().then(() => {
    if (current.page === "logs" && !current.id) refreshJobsTick();
    if (current.page === "runs") updateRunningNotice();
  }).catch(() => setConn(false));
}

/* ---------- settings ---------- */

function viewSettings() {
  settingsDirty = false;
  setCrumbs("配置");
  const cfg = STATE.config;
  const presetId = providerIdForBase(cfg.base_url);
  const preset = MODEL_PRESETS.find((p) => p.id === presetId) || MODEL_PRESETS[2];
  const keyHint = cfg.configured ? `已保存 ${cfg.key_hint}` : "未配置";
  const keyPlaceholder = cfg.configured ? `已保存 ${cfg.key_hint}（留空不修改）` : "粘贴 API Key";
  const webCfg = cfg.web || { provider: "deepseek", configured: false, reused: false, key_hint: "", base_url: "", max_results: 5, enabled: true, providers: [] };
  const webProviders = webCfg.providers?.length ? webCfg.providers : [
    { id: "deepseek", label: "DeepSeek Search API", base_url: "https://api.deepseek.com/v1/tools", key_url: "https://platform.deepseek.com/api_keys", note: "DeepSeek Search API；可复用模型 key。" },
    { id: "exa", label: "Exa", base_url: "https://api.exa.ai", key_url: "https://dashboard.exa.ai/api-keys", note: "面向 AI 的网页搜索 API。" },
    { id: "tavily", label: "Tavily", base_url: "https://api.tavily.com", key_url: "https://app.tavily.com/home", note: "为 agent 设计的搜索 API。" },
  ];
  const webPreset = webProviders.find((item) => item.id === webCfg.provider) || webProviders[0];
  const webKeyHint = webCfg.reused ? "复用模型 key" : (webCfg.configured ? `已保存 ${webCfg.key_hint}` : "未配置");
  const webKeyPlaceholder = webCfg.reused
    ? `复用模型 key ${webCfg.key_hint}（留空不改；也可填单独的 DeepSeek key）`
    : (webCfg.configured ? `已保存 ${webCfg.key_hint}（留空不修改）` : "粘贴搜索 API Key");
  view.innerHTML = `
    ${pageHead({
      eyebrow: "Config",
      title: "配置",
      desc: `大模型 API Key、网络搜索和基础运行环境。搜索是可选项：配置后「一句话加产品」才能联网查产品信息；不配置也能用固定的产品谱系。`,
      actions: `<a class="pill blue" href="#/plugins">应用接入</a><span class="pill ${cfg.configured ? "blue" : "amber"}" id="key-pill">${cfg.configured ? "key 已保存" : "待配置 key"}</span>`,
    })}
    <div class="stack" style="max-width:900px">
      <div class="card">
        <div class="card-head">
          <div><h2>大模型 API Key</h2><p class="hint">一句话加产品时用这个 key 整理产品信息；Codex 这类外部 CLI 用各自的登录态，不读这里。</p></div>
        </div>
        <form id="settings-form" autocomplete="off">
          <div class="field-row">
            <label class="field"><span>服务商预设</span>
              <select id="f-provider">
                ${MODEL_PRESETS.map((p) => `<option value="${p.id}" ${p.id === presetId ? "selected" : ""}>${esc(p.label)}</option>`).join("")}
              </select>
            </label>
            <label class="field"><span>模型</span>
              <input id="f-model" type="text" value="${esc(cfg.model)}" placeholder="gpt-4o-mini" spellcheck="false">
              <div class="field-error" id="f-model-err"></div>
            </label>
          </div>
          <label class="field"><span>API Key</span>
            <div class="key-input">
              <input id="f-key" type="password" autocomplete="new-password" spellcheck="false"
                     placeholder="${esc(keyPlaceholder)}" aria-describedby="f-key-status">
              <button type="button" class="key-toggle" id="f-key-toggle" hidden aria-label="显示 key">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>
              </button>
            </div>
            <div class="field-hint"><span id="f-key-status">${esc(keyHint)}</span> ·
              <a id="f-key-link" href="${esc(preset.keyUrl || "#")}" target="_blank" rel="noopener" ${preset.keyUrl ? "" : "hidden"}>去控制台获取 key</a> ·
              key 只写不读；保存后点「保存并测试」确认可用，401 通常是 key 无效或类型不对</div>
            <div class="field-error" id="f-key-err"></div>
          </label>
          <details class="prep" id="f-advanced" ${presetId === "custom" ? "open" : ""}>
            <summary>高级设置（Base URL / 超时）</summary>
            <div class="prep-body">
              <div class="field-row">
                <label class="field"><span>Base URL <b>*</b></span>
                  <input id="f-base" type="text" value="${esc(cfg.base_url)}" placeholder="https://api.openai.com/v1" spellcheck="false">
                  <div class="field-error" id="f-base-err"></div>
                </label>
                <label class="field" style="max-width:180px"><span>超时（秒）</span>
                  <input id="f-timeout" type="number" min="1" step="1" value="${esc(cfg.timeout)}">
                  <div class="field-error" id="f-timeout-err"></div>
                </label>
              </div>
              <span class="dim">不是 OpenAI-compatible 的网关不要用这个入口；自定义时改这里。</span>
            </div>
          </details>
          <div class="actions">
            <button class="primary" id="save" type="submit">保存</button>
            <button id="test" type="button">保存并测试</button>
            <span class="pill" id="dirty-pill" hidden>未保存</span>
            <span class="tiny" style="margin:0">测试会先保存，再发一条 8 token 的 ping</span>
          </div>
          <div class="form-status" id="test-status"></div>
        </form>
        <div class="note" style="margin-top:14px">配置文件：<code>${pathHtml(cfg.path)}</code>
          <button class="icon ghost" type="button" data-copy="${esc(cfg.path)}" title="${esc(cfg.path)}" aria-label="复制配置路径">${icon('<path d="M9 9h9v11H9z"/><path d="M5 15V4h9"/>')}</button><br>
          key 通过子进程环境变量传给 <code>wt.py agent</code>，不写在命令行、不写进 job 记录。</div>
      </div>
      <div class="card" id="web-card">
        <div class="card-head">
          <div><h2>网络搜索</h2><p class="hint">给「一句话加产品」用；DeepSeek 可复用模型 key，其他 provider 需要单独的 key。保存只代表有 key，是否有效用「保存并测试」验证。</p></div>
          <span class="pill ${webCfg.configured ? "blue" : "amber"}" id="web-pill">${webCfg.configured ? "搜索 key 已保存" : "待配置搜索"}</span>
        </div>
        <div class="note ${webCfg.configured ? "" : "warn"}" id="w-todo">
          ${webCfg.configured
            ? `搜索 key 已保存（${esc(webPreset.label)}）。点「保存并测试」验证；一句话加产品时会用它查产品信息，结果仍需要来源和确认。`
            : `待办：选一个服务商并配置搜索 API Key。也可以先用固定的产品谱系。<a id="w-key-link-note" href="${esc(webPreset.key_url || "#")}" target="_blank" rel="noopener">去 ${esc(webPreset.label)} 获取 key</a>`}
        </div>
        <form id="web-form" autocomplete="off">
          <div class="field-row">
            <label class="field"><span>服务商</span>
              <select id="w-provider">
                ${webProviders.map((item) => `<option value="${esc(item.id)}" ${item.id === webCfg.provider ? "selected" : ""}>${esc(item.label)}</option>`).join("")}
              </select>
              <div class="field-hint" id="w-provider-note">${esc(webPreset.note || "")}</div>
            </label>
            <label class="field" style="max-width:180px"><span>每次结果数</span>
              <input id="w-max" type="number" min="1" max="10" value="${esc(webCfg.max_results)}">
              <div class="field-error" id="w-max-err"></div>
            </label>
          </div>
          <label class="field"><span>搜索 API Key</span>
            <div class="key-input">
              <input id="w-key" type="password" autocomplete="new-password" spellcheck="false"
                     placeholder="${esc(webKeyPlaceholder)}" aria-describedby="w-key-status">
              <button type="button" class="key-toggle" id="w-key-toggle" hidden aria-label="显示搜索 key">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/></svg>
              </button>
            </div>
            <div class="field-hint"><span id="w-key-status">${esc(webKeyHint)}</span> ·
              <a id="w-key-link" href="${esc(webPreset.key_url || "#")}" target="_blank" rel="noopener" ${webPreset.key_url ? "" : "hidden"}>去控制台获取 key</a> ·
              搜索 key 只写不读；DeepSeek 可复用模型 key，其他 provider 单独存。先点「保存并测试」验证</div>
            <div class="field-error" id="w-key-err"></div>
          </label>
          <details class="prep" id="w-advanced">
            <summary>高级设置（搜索 Base URL）</summary>
            <div class="prep-body">
              <label class="field"><span>Base URL</span>
                <input id="w-base" type="text" value="${esc(webCfg.base_url || "")}" placeholder="${esc(webPreset.base_url || "")}" spellcheck="false">
                <div class="field-hint">留空用服务商默认地址；只有自建网关才需要改。</div>
                <div class="field-error" id="w-base-err"></div>
              </label>
            </div>
          </details>
          <label class="check"><input id="w-enabled" type="checkbox" ${webCfg.enabled ? "checked" : ""}> 启用网络搜索（配置 key 后自动开启）</label>
          <div class="actions">
            <button class="primary" id="w-save" type="submit">保存搜索配置</button>
            <button id="w-test" type="button">保存并测试</button>
            <span class="tiny" style="margin:0">测试会搜索一次 “DeepSeek”，消耗一次额度</span>
          </div>
          <div class="form-status" id="w-test-status"></div>
          <div id="w-results" class="search-results"></div>
        </form>
      </div>
      <div class="card" id="doctor-card">
        <div class="card-head">
          <div><h2>基础环境</h2><p class="hint">采集都依赖的基础环境；被测应用端口和连接状态在接入页。</p></div>
          <button class="ghost sm" id="doctor-refresh" type="button">重新检查</button>
        </div>
        <div id="doctor-body"><div class="empty">检查中…</div></div>
      </div>
    </div>`;

  const provider = document.getElementById("f-provider");
  const base = document.getElementById("f-base");
  const model = document.getElementById("f-model");
  const timeout = document.getElementById("f-timeout");
  const key = document.getElementById("f-key");
  const keyToggle = document.getElementById("f-key-toggle");
  const keyStatus = document.getElementById("f-key-status");
  const keyLink = document.getElementById("f-key-link");
  const keyPill = document.getElementById("key-pill");
  const advanced = document.getElementById("f-advanced");
  const dirtyPill = document.getElementById("dirty-pill");

  const eyeOpen = icon('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>');
  const eyeOff = icon('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/><path d="M4 4l16 16"/>');

  const clearTestStatus = () => {
    const status = document.getElementById("test-status");
    if (status) { status.className = "form-status"; status.innerHTML = ""; }
  };

  const markDirty = () => {
    settingsDirty = true;
    if (dirtyPill) dirtyPill.hidden = false;
  };

  const syncEye = () => {
    if (!key.value) key.type = "password";
    const shown = key.type === "text";
    keyToggle.hidden = !key.value;
    keyToggle.setAttribute("aria-pressed", String(shown));
    keyToggle.setAttribute("aria-label", shown ? "隐藏 key" : "显示 key");
    keyToggle.innerHTML = shown ? eyeOff : eyeOpen;
  };

  const setKeyLink = (p) => {
    if (!keyLink) return;
    keyLink.href = p.keyUrl || "#";
    keyLink.hidden = !p.keyUrl;
  };

  const updateKeyStatus = () => {
    const now = STATE.config;
    if (keyStatus) keyStatus.textContent = now.configured ? `已保存 ${now.key_hint}` : "未配置";
    if (key) key.placeholder = now.configured ? `已保存 ${now.key_hint}（留空不修改）` : "粘贴 API Key";
    if (keyPill) {
      keyPill.textContent = now.configured ? "key 已保存" : "待配置 key";
      keyPill.className = "pill " + (now.configured ? "blue" : "amber");
    }
  };

  provider.addEventListener("change", () => {
    const p = MODEL_PRESETS.find((item) => item.id === provider.value) || MODEL_PRESETS[2];
    if (p.id === "custom") {
      advanced.open = true;
    } else {
      base.value = p.base;
      model.value = p.model;
    }
    clearFieldError("f-base");
    clearFieldError("f-model");
    setKeyLink(p);
    markDirty();
    clearTestStatus();
  });

  [base, model, timeout].forEach((field) => field.addEventListener("input", () => {
    markDirty();
    clearFieldError(field.id);
    clearTestStatus();
  }));

  key.addEventListener("input", () => {
    markDirty();
    clearFieldError("f-key");
    clearTestStatus();
    syncEye();
  });
  keyToggle.addEventListener("click", () => {
    key.type = key.type === "password" ? "text" : "password";
    syncEye();
    key.focus();
  });
  syncEye();
  setKeyLink(preset);

  const collect = () => {
    const body = {
      base_url: base.value.trim(),
      model: model.value.trim(),
      timeout: timeout.value,
    };
    const keyValue = key.value.trim();
    if (keyValue) body.api_key = keyValue;
    return body;
  };

  const validateSettings = () => {
    let ok = true;
    const baseValue = base.value.trim();
    const modelValue = model.value.trim();
    const timeoutValue = Number(timeout.value);
    if (!baseValue) {
      setFieldError("f-base", "填一个 endpoint，例如 https://api.openai.com/v1");
      advanced.open = true;
      ok = false;
    } else {
      try {
        const url = new URL(baseValue);
        if (!["http:", "https:"].includes(url.protocol)) throw new Error("protocol");
      } catch (_) {
        setFieldError("f-base", "需要是 http:// 或 https:// 开头的完整 URL");
        advanced.open = true;
        ok = false;
      }
    }
    if (!modelValue) { setFieldError("f-model", "填模型名，例如 gpt-4o-mini"); ok = false; }
    if (!Number.isFinite(timeoutValue) || timeoutValue <= 0) { setFieldError("f-timeout", "超时必须是大于 0 的数字"); advanced.open = true; ok = false; }
    if (!STATE.config.configured && !key.value.trim()) { setFieldError("f-key", "填一个 API Key"); ok = false; }
    return ok;
  };

  const persist = async () => {
    await api("/api/config", { body: collect() });
    await loadState();
    key.value = "";
    key.type = "password";
    syncEye();
    settingsDirty = false;
    if (dirtyPill) dirtyPill.hidden = true;
    updateKeyStatus();
  };

  const saveConfig = async () => {
    const button = document.getElementById("save");
    if (button.disabled) return;
    if (!validateSettings()) return;
    button.disabled = true;
    button.textContent = "保存中…";
    try {
      await persist();
      route();
      toast("配置已保存", "ok");
    } catch (err) {
      toast(err.message, "bad");
      button.disabled = false;
      button.textContent = "保存";
    }
  };

  document.getElementById("settings-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveConfig();
  });

  document.getElementById("test").onclick = async (event) => {
    const button = event.target;
    if (button.disabled) return;
    if (!validateSettings()) return;
    button.disabled = true;
    const old = button.textContent;
    button.textContent = "保存并连接…";
    try {
      await persist();
      setFormStatus("test-status", "show", `<span class="spinner"></span> 已保存，正在请求 provider…`);
      const data = await api("/api/config/test", { body: {} });
      setFormStatus("test-status", "ok", `连通正常 · ${esc(data.model)} · ${esc(data.elapsed_s)}s`);
      toast("连通正常", "ok");
    } catch (err) {
      setFormStatus("test-status", "bad", esc(err.message));
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  };

  // ----- network search card -----
  const wProvider = document.getElementById("w-provider");
  const wMax = document.getElementById("w-max");
  const wBase = document.getElementById("w-base");
  const wKey = document.getElementById("w-key");
  const wToggle = document.getElementById("w-key-toggle");
  const wEnabled = document.getElementById("w-enabled");
  const wPill = document.getElementById("web-pill");
  const wKeyStatus = document.getElementById("w-key-status");
  const wKeyLink = document.getElementById("w-key-link");
  const wProviderNote = document.getElementById("w-provider-note");
  const wTodo = document.getElementById("w-todo");
  const wResults = document.getElementById("w-results");
  const wAdvanced = document.getElementById("w-advanced");

  const currentWeb = () => STATE.config.web || webCfg;
  const webPresetFor = (id) => webProviders.find((item) => item.id === id) || webProviders[0];

  const clearWebStatus = () => {
    const status = document.getElementById("w-test-status");
    if (status) { status.className = "form-status"; status.innerHTML = ""; }
    if (wResults) wResults.innerHTML = "";
  };

  const syncWebEye = () => {
    if (!wKey.value) wKey.type = "password";
    const shown = wKey.type === "text";
    wToggle.hidden = !wKey.value;
    wToggle.setAttribute("aria-pressed", String(shown));
    wToggle.setAttribute("aria-label", shown ? "隐藏搜索 key" : "显示搜索 key");
    wToggle.innerHTML = shown
      ? icon('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/><path d="M4 4l16 16"/>')
      : icon('<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z"/><circle cx="12" cy="12" r="3"/>');
  };

  const updateWebCard = () => {
    const web = currentWeb();
    const preset = webPresetFor(web.provider);
    if (wPill) {
      wPill.textContent = web.configured ? (web.enabled ? "搜索 key 已保存" : "搜索已停用") : "待配置搜索";
      wPill.className = "pill " + (web.configured && web.enabled ? "blue" : "amber");
    }
    const reused = Boolean(web.reused);
    if (wKeyStatus) wKeyStatus.textContent = reused ? "复用模型 key" : (web.configured ? `已保存 ${web.key_hint}` : "未配置");
    if (wKey) wKey.placeholder = reused
      ? `复用模型 key ${web.key_hint}（留空不改；也可填单独的 DeepSeek key）`
      : (web.configured ? `已保存 ${web.key_hint}（留空不修改）` : "粘贴搜索 API Key");
    if (wKeyLink) {
      wKeyLink.href = preset.key_url || "#";
      wKeyLink.textContent = `去 ${preset.label} 获取 key`;
      wKeyLink.hidden = !preset.key_url;
    }
    if (wProviderNote) wProviderNote.textContent = preset.note || "";
    if (wBase) wBase.placeholder = preset.base_url || "";
    if (wEnabled) wEnabled.checked = Boolean(web.enabled);
    if (wTodo) {
      if (!web.configured) {
        wTodo.className = "note warn";
        wTodo.innerHTML = `待办：选一个服务商并配置搜索 API Key。也可以先用固定的产品谱系。<a href="${esc(preset.key_url || "#")}" target="_blank" rel="noopener">去 ${esc(preset.label)} 获取 key</a>`;
      } else if (!web.enabled) {
        wTodo.className = "note warn";
        wTodo.innerHTML = `搜索 key 已保存，但网络搜索被停用；勾选下面的「启用网络搜索」后保存即可。`;
      } else if (web.reused) {
        wTodo.className = "note";
        wTodo.innerHTML = `搜索 key 已保存（DeepSeek，复用模型 key）。点「保存并测试」验证；一句话加产品时会用它查产品信息，结果仍需要来源和确认。`;
      } else {
        wTodo.className = "note";
        wTodo.innerHTML = `搜索 key 已保存（${esc(preset.label)}）。点「保存并测试」验证；一句话加产品时会用它查产品信息，结果仍需要来源和确认。`;
      }
    }
  };

  wProvider.addEventListener("change", () => {
    const preset = webPresetFor(wProvider.value);
    if (wProviderNote) wProviderNote.textContent = preset.note || "";
    if (wKeyLink) {
      wKeyLink.href = preset.key_url || "#";
      wKeyLink.textContent = `去 ${preset.label} 获取 key`;
      wKeyLink.hidden = !preset.key_url;
    }
    if (wBase) wBase.placeholder = preset.base_url || "";
    clearWebStatus();
    clearFieldError("w-key");
    clearFieldError("w-base");
  });
  [wMax, wBase].forEach((field) => field.addEventListener("input", () => {
    clearWebStatus();
    clearFieldError(field.id);
  }));
  wKey.addEventListener("input", () => { clearWebStatus(); clearFieldError("w-key"); syncWebEye(); });
  wToggle.addEventListener("click", () => {
    wKey.type = wKey.type === "password" ? "text" : "password";
    syncWebEye();
    wKey.focus();
  });
  wEnabled.addEventListener("change", clearWebStatus);
  syncWebEye();

  const collectWeb = () => {
    const body = {
      web: {
        provider: wProvider.value,
        base_url: wBase.value.trim(),
        max_results: Number(wMax.value),
        enabled: wEnabled.checked || Boolean(wKey.value.trim()),
      },
    };
    const value = wKey.value.trim();
    if (value) body.web.api_key = value;
    return body;
  };

  const validateWeb = () => {
    let ok = true;
    const maxValue = Number(wMax.value);
    if (!Number.isFinite(maxValue) || !Number.isInteger(maxValue) || maxValue < 1 || maxValue > 10) {
      setFieldError("w-max", "结果数需要是 1–10 的整数");
      ok = false;
    }
    const baseValue = wBase.value.trim();
    if (baseValue) {
      try {
        const parsed = new URL(baseValue);
        if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("protocol");
      } catch (_) {
        setFieldError("w-base", "需要是 http:// 或 https:// 开头的完整 URL");
        if (wAdvanced) wAdvanced.open = true;
        ok = false;
      }
    }
    if (!currentWeb().configured && !wKey.value.trim()) {
      setFieldError("w-key", "填一个搜索 API Key");
      ok = false;
    }
    return ok;
  };

  const persistWeb = async () => {
    await api("/api/config", { body: collectWeb() });
    await loadState();
    wKey.value = "";
    wKey.type = "password";
    syncWebEye();
    updateWebCard();
  };

  const saveWeb = async () => {
    if (!validateWeb()) return false;
    const button = document.getElementById("w-save");
    if (button.disabled) return false;
    button.disabled = true;
    const old = button.textContent;
    button.textContent = "保存中…";
    try {
      await persistWeb();
      toast("搜索配置已保存", "ok");
      return true;
    } catch (err) {
      setFormStatus("w-test-status", "bad", esc(err.message));
      return false;
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  };

  document.getElementById("web-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveWeb();
  });

  document.getElementById("w-test").onclick = async (event) => {
    const button = event.target;
    if (button.disabled) return;
    if (!validateWeb()) return;
    button.disabled = true;
    const old = button.textContent;
    button.textContent = "保存并搜索…";
    try {
      await persistWeb();
      setFormStatus("w-test-status", "show", `<span class="spinner"></span> 已保存，正在请求搜索 provider…`);
      const data = await api("/api/config/test-search", { body: { query: "DeepSeek" } });
      const results = data.results || [];
      setFormStatus("w-test-status", "ok",
        `搜索正常 · ${esc(data.provider_label)} · ${results.length} 条结果 · ${esc(data.elapsed_s)}s`);
      if (results.length && wResults) {
        wResults.innerHTML = results.slice(0, 3).map((item) => {
          let host = "";
          try { host = new URL(item.url).hostname.replace(/^www\./, ""); } catch (_) { host = ""; }
          return `<a class="search-result" href="${esc(item.url)}" target="_blank" rel="noopener">
            <span class="sr-title">${esc(item.title || item.url)}</span>
            <span class="sr-host">${esc(host)}</span>
            ${item.snippet ? `<span class="sr-snippet">${esc(item.snippet)}</span>` : ""}
          </a>`;
        }).join("");
      }
      toast("搜索正常", "ok");
    } catch (err) {
      setFormStatus("w-test-status", "bad", esc(err.message));
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  };
  updateWebCard();

  view.querySelectorAll("[data-focus]").forEach((el) => {
    el.addEventListener("click", () => document.querySelector(el.dataset.focus)?.focus());
  });
  view.querySelectorAll("[data-copy]").forEach((el) => {
    el.addEventListener("click", () => copyText(el.dataset.copy));
  });

  let doctorData = null;
  let onlyProblems = false;
  const CORE_CHECKS = ["deps", "xdotool", "real-desktop"];

  const renderDoctor = () => {
    const box = document.getElementById("doctor-body");
    if (!box) return;
    if (!doctorData) {
      box.innerHTML = `<div class="empty">自检失败。<div class="actions"><button type="button" class="ghost sm" id="doctor-retry">重试</button></div></div>`;
      document.getElementById("doctor-retry").onclick = loadDoctor;
      return;
    }
    const checks = (doctorData.checks || []).filter((c) => CORE_CHECKS.includes(c.id));
    const failed = checks.filter((c) => !c.ok);
    const total = checks.length;
    const passed = total - failed.length;
    const summary = `<div class="doctor-summary ${failed.length ? "warn" : "ok"}">
      <div class="ds-main">
        <div class="doctor-score ${failed.length ? "amber" : "green"}">${passed}/${total}</div>
        <div class="ds-text"><b>${failed.length ? `${failed.length} 项需要处理` : "基础环境就绪"}</b>
          <small>${failed.length ? "先处理下面的黄色项，再发起任务。" : "CDP 依赖、桌面会话和 xdotool 都通过了。"}</small></div>
      </div>
      <div class="actions" style="margin:0">
        ${failed.length ? `<button type="button" class="ghost sm" id="doctor-only">${onlyProblems ? "看全部" : "只看需处理"}</button>` : ""}
        ${failed.some((c) => c.id === "deps") ? `<button type="button" class="primary sm" data-install>安装依赖</button>` : ""}
      </div>
    </div>`;
    const shown = onlyProblems ? failed : checks.slice().sort((a, b) => Number(a.ok) - Number(b.ok));
    const rows = shown.map((c) => {
      const action = !c.ok && c.id === "deps"
        ? `<button type="button" class="primary sm" data-install>安装依赖</button>` : "";
      return `<div class="check-row">
        <span class="dot ${c.ok ? "on" : "off"}"></span>
        <div class="check-body">
          <div class="check-title"><span>${esc(c.label)}</span>
            <span class="pill ${c.ok ? "green" : "amber"}">${c.ok ? "通过" : "需处理"}</span></div>
          <div class="check-detail">${esc(c.detail || "")}</div>
          ${c.fix ? `<div class="check-fix">${esc(c.fix)}</div>` : ""}
        </div>
        ${action ? `<div class="check-action">${action}</div>` : ""}
      </div>`;
    }).join("");
    box.innerHTML = summary + (shown.length
      ? `<div class="check-list">${rows}</div>`
      : `<div class="empty">全部通过，没有需要处理的项。</div>`);

    const only = document.getElementById("doctor-only");
    if (only) only.onclick = () => {
      onlyProblems = !onlyProblems;
      renderDoctor();
      document.getElementById("doctor-only")?.focus();
    };
    box.querySelectorAll("[data-install]").forEach((el) => el.addEventListener("click", () => installDeps(el)));
  };

  const loadDoctor = async () => {
    const box = document.getElementById("doctor-body");
    if (box) box.innerHTML = `<div class="empty"><span class="spinner"></span> 检查中…</div>`;
    try {
      doctorData = await api("/api/doctor");
      if (document.getElementById("doctor-body")) renderDoctor();
    } catch (err) {
      doctorData = null;
      const target = document.getElementById("doctor-body");
      if (target) {
        target.innerHTML = `<div class="empty">自检失败：${esc(err.message)}
          <div class="actions"><button type="button" class="ghost sm" id="doctor-retry">重试</button></div></div>`;
        document.getElementById("doctor-retry").onclick = loadDoctor;
      }
    }
  };

  const installDeps = async (source) => {
    const buttons = view.querySelectorAll("[data-install]");
    buttons.forEach((btn) => { btn.disabled = true; btn.textContent = "安装中…"; });
    if (source) source.disabled = true;
    toast("开始安装依赖，可能需要一分钟…", "info");
    try {
      const res = await api("/api/deps/install", { body: {} });
      if (res.ok) {
        toast("依赖已装到 workbench/.deps", "ok");
      } else {
        toast("安装失败，已显示输出", "bad");
        openModal(`
          <div class="modal-head"><div><h2 id="dlg-title">依赖安装失败</h2><div class="sub">workbench/.deps</div></div>
            <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">${icon('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>
          <div class="modal-body"><pre class="modal-pre">${esc(res.log || "没有输出")}</pre></div>
          <div class="modal-foot"><button type="button" id="dlg-close">关闭</button></div>`);
        document.getElementById("dlg-close").onclick = closeModal;
        document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeModal));
      }
    } catch (err) {
      toast(err.message, "bad");
    } finally {
      await loadDoctor();
      await loadState();
    }
  };

  document.getElementById("doctor-refresh").onclick = loadDoctor;
  loadDoctor();
}
function viewPlugins() {
  setCrumbs("接入");
  view.innerHTML = `
    ${pageHead({
      eyebrow: "Integrations",
      title: "应用接入",
      desc: `说一句「加上 Kimi Work」，工作台会查产品信息、检查本机安装，并生成产品卡。这里只管本机应用；能不能自动体验，运行页会告诉你。`,
      actions: `<a class="pill blue" href="#/config">基础环境</a>`,
    })}
    <div class="note" style="margin-bottom:10px">
      这里只看状态，不用手工启动：开始自动体验时，应用会被带调试端口自动拉起。CLI 工具装好、登录好就行。
    </div>
    <div class="note" style="margin-bottom:16px">
      产品谱系是项目里的固定数据，只读；新增家族由维护者加 <code>catalog/*.json</code>。
      手工补应用已经收进页面底部的「高级」折叠区，正式版会移除。
      搜索 key 在 <a href="#/config">配置 → 网络搜索</a> 里设置；下一步清单见仓库根目录的 <code>TODO.md</code>。
    </div>
    <div class="card" id="discover-card">
      <div class="card-head">
        <div><h2>一句话加产品</h2><p class="hint">例如「加上 Kimi Work」。会查产品信息、检查本机安装；不会自动下载或安装。</p></div>
        <span class="pill ${STATE.config?.web?.configured ? "blue" : "amber"}" id="discover-pill">${STATE.config?.web?.configured ? "搜索 key 已保存" : "搜索待配置"}</span>
      </div>
      <form id="discover-form" autocomplete="off">
        <div class="discover-row">
          <input id="discover-input" type="text" maxlength="200" placeholder="加上 Kimi Work" spellcheck="false">
          <button class="primary" id="discover-start" type="submit">开始查找</button>
        </div>
        <div class="field-hint">先查固定产品谱系；未收录时用网络搜索 + 模型整理，会消耗额度。搜索 key 在 <a href="#/config">配置 → 网络搜索</a>。</div>
        <div class="field-error" id="discover-error"></div>
      </form>
      <div id="discover-progress" hidden>
        <div class="discover-steps" id="discover-steps">准备中…</div>
        <pre class="discover-log" id="discover-log"></pre>
        <div class="actions" style="margin-top:8px">
          <a class="pill" id="discover-job-link" href="#/logs">在日志里看</a>
        </div>
      </div>
    </div>
    <div id="plugin-alert"></div>
    <div class="stats plugin-stats" id="plugin-stats"></div>
    <div class="card" id="discovered-card" hidden>
      <div class="card-head">
        <div><h2>自动发现</h2><p class="hint">一句话加的产品，存在本地接入；来源和“是否已找到本机安装”分开显示。</p></div>
      </div>
      <div id="discovered-body"></div>
    </div>
    <div class="card" id="family-card">
      <div class="card-head">
        <div><h2>产品谱系</h2><p class="hint">固定产品数据，来自项目里的 <code>catalog/*.json</code>；只读，不由用户维护。本机应用状态见下方。</p></div>
        <span class="pill" id="family-count">—</span>
      </div>
      <div id="family-body"><div class="empty"><span class="spinner"></span> 读取产品谱系…</div></div>
    </div>
    <div class="card">
      <div class="card-head">
        <div><h2>本机应用</h2><p class="hint">只看本机：装没装、跑没跑、调试端口开没开。开始自动体验时，运行页会把应用带端口自动拉起。</p></div>
        <button class="ghost sm" id="plugins-refresh" type="button">重新检查</button>
      </div>
      <div id="plugin-catalog"><div class="empty"><span class="spinner"></span> 读取接入清单…</div></div>
    </div>
    <div class="card" id="cli-card" style="margin-top:14px">
      <div class="card-head">
        <div><h2>命令行工具</h2><p class="hint">装在 PATH 里、在终端能直接用的产品；登录好后才能在运行页自动体验。</p></div>
      </div>
      <div id="cli-list"><div class="empty"><span class="spinner"></span> 读取…</div></div>
    </div>
    <details class="prep" id="manual-entry" style="margin-top:16px">
      <summary>高级 / 手工补充（过渡）</summary>
      <div class="prep-body">
        <p class="hint" style="margin-top:0">只有需要手工补一个应用时才用这里。正式版会移除。</p>
        <div class="actions">
          <button type="button" class="primary" id="add-app">添加应用</button>
        </div>
      </div>
    </details>
    <div class="tiny" id="plugin-path"></div>`;

  let doctor = null;
  let doctorError = "";

  const appById = (id) => (doctor?.apps || []).find((item) => item.id === id) || null;
  const buildRows = () => [...(doctor?.apps || [])].sort((a, b) =>
    Number(Boolean(a.custom)) - Number(Boolean(b.custom))
    || String(a.label).localeCompare(String(b.label)));

  const appStatus = (app) => {
    if (!app.installed) return ["未安装", ""];
    if (app.port_open) return ["已就绪", "green"];
    if (app.running) return ["运行中 · 无端口", "amber"];
    return ["未运行", ""];
  };

  const rowHTML = (app) => {
    const tags = [`<span class="pill ${app.custom ? "blue" : ""}">${app.custom ? "自定义应用" : "内置应用"}</span>`];
    if (app.overridden) tags.push(`<span class="pill">自定义路径</span>`);
    const info = appStatus(app);
    const actions = [];
    if (!app.installed && !app.custom) {
      actions.push(`<button type="button" class="ghost sm" data-app-path="${esc(app.id)}">设置路径</button>`);
    }
    if (app.installed && !app.custom) actions.push(`<button type="button" class="ghost sm" data-app-path="${esc(app.id)}">路径</button>`);
    if (app.custom || app.overridden) {
      actions.push(`<button type="button" class="ghost sm" data-app-remove="${esc(app.id)}">${app.custom ? "移除" : "恢复默认"}</button>`);
    }
    return `<div class="catalog-row">
      <div class="catalog-main">
        <div class="catalog-name"><b>${esc(app.label)}</b><span class="pill">GUI</span>${tags.join("")}</div>
        <div class="catalog-sub"><span>端口 ${app.port}</span></div>
      </div>
      <div class="catalog-cap cap-run">${app.installed && app.port_open ? `<span class="pill green">可体验</span>`
        : app.installed ? `<span class="pill amber">需启动</span>` : `<span class="pill">—</span>`}</div>
      <div class="catalog-state">
        <span class="pill ${info[1]}">${esc(info[0])}</span>
        ${app.installed && !app.port_open
          ? `<div class="catalog-why">运行页开始时会自动以 --remote-debugging-port=${app.port} 启动</div>` : ""}
      </div>
      <div class="catalog-actions">${actions.join("") || `<span class="dim">—</span>`}</div>
    </div>`;
  };

  const formLabel = (form) => ({
    ide: "IDE", cli: "CLI", work: "工作台", plugin: "插件",
    cloud: "云", desktop: "桌面", agent: "Agent", web: "Web",
  }[form] || form);

  const hostOf = (url) => {
    try { return new URL(url).hostname.replace(/^www\./, ""); }
    catch (_) { return "来源"; }
  };

  const renderFamilies = () => {
    const box = document.getElementById("family-body");
    const count = document.getElementById("family-count");
    if (!box) return;
    const families = STATE.catalog?.families || [];
    const products = families.reduce((n, family) => n + (family.products || []).length, 0);
    const surfaces = families.reduce((n, family) =>
      n + (family.products || []).reduce((m, product) => m + (product.surfaces || []).length, 0), 0);
    if (count) count.textContent = `${families.length} 个家族 · ${products} 个产品`;
    if (!families.length) {
      const errors = STATE.catalog?.errors || [];
      box.innerHTML = `<div class="empty"><strong>还没有产品谱系</strong><span>把 catalog/*.json 放进项目后刷新；文件错误会显示在下面。</span>${errors.length ? `<div class="tiny">${errors.map((item) => `${esc(item.file)}: ${esc(item.error)}`).join("<br>")}</div>` : ""}</div>`;
      return;
    }
    const errors = STATE.catalog?.errors || [];
    const errorNote = errors.length
      ? `<div class="note warn" style="margin:10px 14px">有 ${errors.length} 个 catalog 文件没有加载：${errors.map((item) => `${esc(item.file)}（${esc(item.error)}）`).join("；")}</div>`
      : "";
    box.innerHTML = `${errorNote}<div class="family-list">${families.map((family) => {
      const productChips = (family.products || []).map((product) =>
        `<span class="family-product"><span class="pill">${esc(formLabel(product.form))}</span>${esc(product.name)}</span>`).join("");
      const links = [
        family.homepage ? `<a href="${esc(family.homepage)}" target="_blank" rel="noopener">官网</a>` : "",
        family.docs ? `<a href="${esc(family.docs)}" target="_blank" rel="noopener">文档</a>` : "",
      ].filter(Boolean).join(" · ");
      const source = (family.sources || [])[0];
      const sourceLine = source
        ? `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(hostOf(source.url))}</a>${source.verified_at ? ` · 核实于 ${esc(source.verified_at)}` : ""}`
        : "未标注来源";
      const aliases = (family.aliases || []).length
        ? `<span class="family-alias">别名：${esc(family.aliases.join(" / "))}</span>` : "";
      const surfaceCount = (family.products || []).reduce((m, product) => m + (product.surfaces || []).length, 0);
      return `<div class="family-row">
        <div class="family-main">
          <div class="family-title"><b>${esc(family.name)}</b><span class="pill">${esc(family.vendor)}</span></div>
          <div class="family-desc">${esc(family.positioning)}</div>
          <div class="family-products">${productChips}</div>
          ${aliases}
        </div>
        <div class="family-side">
          <div class="family-meta">${(family.products || []).length} 个产品 · ${surfaceCount} 个可测面</div>
          <div class="family-links">${links || "—"}</div>
          <div class="family-source">${sourceLine}</div>
        </div>
      </div>`;
    }).join("")}</div>`;
  };

  const renderDiscovered = () => {
    const card = document.getElementById("discovered-card");
    const box = document.getElementById("discovered-body");
    if (!card || !box) return;
    const items = STATE.discovered || [];
    if (!items.length) { card.hidden = true; return; }
    card.hidden = false;
    box.innerHTML = items.map((item) => {
      const app = item.app_id ? appById(item.app_id) : null;
      const info = app ? appStatus(app) : null;
      const forms = (item.forms || []).map((form) => `<span class="pill">${esc(formLabel(form))}</span>`).join("");
      let status = `<span class="pill amber">未找到本机安装</span>`;
      if (app) status = `<span class="pill ${info[1]}">${esc(info[0])}</span><span class="pill">端口 ${esc(app.port)}</span>`;
      else if (item.cli_command) status = `<span class="pill">CLI · ${esc(item.cli_command)}</span>`;
      const actions = [];
      if (app) {
      } else if (item.homepage) {
        actions.push(`<a class="pill blue" href="${esc(item.homepage)}" target="_blank" rel="noopener">官网 / 安装</a>`);
        actions.push(`<button type="button" class="ghost sm" data-disc-retry="${esc(item.id)}">安装后重新查找</button>`);
      } else {
        actions.push(`<button type="button" class="ghost sm" data-disc-retry="${esc(item.id)}">重新查找</button>`);
      }
      actions.push(`<button type="button" class="ghost sm" data-disc-remove="${esc(item.id)}">移除</button>`);
      const sources = (item.sources || []).slice(0, 2).map((source) =>
        `<a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.title || source.url)}</a>`).join(" · ");
      return `<div class="discovered-row">
        <div class="discovered-main">
          <div class="discovered-title"><b>${esc(item.name)}</b><span class="pill blue">自动发现</span>${forms}</div>
          <div class="discovered-vendor">${esc(item.vendor || "厂商未确认")} · ${esc(item.positioning || "定位未确认")}</div>
          <div class="discovered-status">${status}</div>
          ${item.install_hint ? `<div class="discovered-hint">${esc(item.install_hint)}</div>` : ""}
          ${sources ? `<div class="discovered-sources">来源：${sources}</div>` : ""}
        </div>
        <div class="discovered-actions">${actions.join("")}</div>
      </div>`;
    }).join("");
    box.querySelectorAll("[data-disc-remove]").forEach((btn) => {
      btn.onclick = () => {
        const item = items.find((entry) => entry.id === btn.dataset.discRemove);
        if (!item) return;
        confirmAction({
          title: `移除自动发现「${item.name}」？`,
          message: "只移除这条本地发现记录；已经添加的本机应用不会删除。",
          confirmText: "移除",
          danger: true,
          onConfirm: async () => {
            try {
              await api("/api/discovered/remove", { body: { id: item.id } });
              toast("已移除自动发现记录", "ok");
              await loadPlugins();
            } catch (err) {
              toast(err.message, "bad");
            }
          },
        });
      };
    });
    box.querySelectorAll("[data-disc-retry]").forEach((btn) => {
      btn.onclick = () => {
        const item = items.find((entry) => entry.id === btn.dataset.discRetry);
        if (!item) return;
        const input = document.getElementById("discover-input");
        if (input) {
          input.value = `加上 ${item.query || item.name}`;
          input.focus();
          input.scrollIntoView({ block: "center" });
        }
      };
    });
  };

  const renderPath = () => {
    const box = document.getElementById("plugin-path");
    if (!box) return;
    const target = STATE.plugins?.path || "~/.config/tool-walkthrough/plugins.json";
    box.innerHTML = `自定义应用保存在 <code>${pathHtml(target)}</code>；内置应用清单来自 <code>workbench/apps.py</code>。`;
  };

  const renderAlert = () => {
    const box = document.getElementById("plugin-alert");
    if (!box) return;
    box.innerHTML = doctor
      ? ""
      : `<div class="note warn" style="margin-bottom:14px">读不到应用状态${doctorError ? `：${esc(doctorError)}` : ""}。到 <a href="#/config">配置 → 基础环境</a> 检查服务。</div>`;
  };

  const renderStats = (rows) => {
    const box = document.getElementById("plugin-stats");
    if (!box) return;
    const ready = rows.filter((app) => app.port_open).length;
    const needStart = rows.filter((app) => app.installed && !app.port_open).length;
    const custom = rows.filter((app) => app.custom || app.overridden).length;
    const stat = (label, value) => `<div class="stat"><span class="k">${label}</span><span class="v">${value}</span></div>`;
    box.innerHTML = stat("应用", rows.length) + stat("已就绪", ready)
      + stat("需启动", needStart) + stat("自定义", custom);
  };

  const renderCli = () => {
    const box = document.getElementById("cli-list");
    if (!box) return;
    const items = (SURVEY?.products || []).filter((product) => (product.form || "") === "cli");
    if (!items.length) {
      box.innerHTML = `<div class="empty">产品谱系里还没有 CLI 产品。</div>`;
      return;
    }
    box.innerHTML = items.map((product) => {
      const installed = Boolean(product.cli_installed);
      const pill = !installed
        ? `<span class="pill">未检测到</span>`
        : product.runnable
          ? `<span class="pill green">可体验</span>`
          : `<span class="pill amber">已安装 · 未就绪</span>`;
      return `<div class="cli-row">
        <div class="catalog-main">
          <div class="catalog-name"><b>${esc(product.name)}</b><span class="pill">CLI</span></div>
          <div class="catalog-sub"><span>${esc(product.family || "")}</span>${installed ? "" : `<span>${product.why === "这个产品还不能自动体验" ? "暂未支持自动体验" : "命令不在 PATH 里"}</span>`}</div>
        </div>
        <div class="catalog-state">${pill}${installed && !product.runnable ? `<div class="catalog-why">${esc(product.why || "")}</div>` : ""}</div>

      </div>`;
    }).join("");
  };

  const renderCatalog = () => {
    const box = document.getElementById("plugin-catalog");
    if (!box) return;
    const rows = buildRows();
    renderStats(rows);
    if (!rows.length) {
      box.innerHTML = `<div class="empty"><strong>还没有可接入的应用</strong><span>产品谱系是固定的；下一步用一句话加产品。需要手工补时用页面底部的「高级」。</span></div>`;
      return;
    }
    box.innerHTML = `<div class="catalog">
      <div class="catalog-head"><span>应用</span><span>体验</span><span>状态</span><span>操作</span></div>
      ${rows.map(rowHTML).join("")}
    </div>`;
    box.querySelectorAll("[data-app-path]").forEach((btn) => {
      btn.onclick = () => {
        const app = appById(btn.dataset.appPath);
        if (app) openAppModal(app);
      };
    });
    box.querySelectorAll("[data-app-remove]").forEach((btn) => {
      btn.onclick = () => {
        const app = appById(btn.dataset.appRemove);
        if (!app) return;
        const custom = Boolean(app.custom);
        confirmAction({
          title: custom ? `移除 ${app.label}？` : `恢复 ${app.label} 的默认路径？`,
          message: custom ? "只从工作台的自定义接入里移除；不会删除本机程序。" : "会删掉这里保存的自定义可执行文件路径，不会动程序本身。",
          confirmText: custom ? "移除" : "恢复默认",
          danger: true,
          onConfirm: () => removeApp(app),
        });
      };
    });
  };

  const openAppModal = (app = null) => {
    const builtin = Boolean(app && !app.custom);
    const title = app ? (builtin ? `设置 ${app.label} 的可执行文件` : `应用 ${app.label}`) : "添加应用";
    const intro = builtin
      ? (app.installed
        ? "修改这个内置应用的可执行文件路径；保存后下次启动使用新路径。"
        : "当前没有找到这个应用的可执行文件。指向本机安装位置后，先启动应用，再确认调试端口。")
      : "适合 Chromium / Electron 应用。添加后带调试端口启动，就能在运行页自动体验。只添加你信任的可执行文件。";
    openModal(`
      <div class="modal-head"><div><h2 id="dlg-title">${esc(title)}</h2></div>
        <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">${icon('<path d="M6 6l12 12M18 6 6 18"/>')}</button></div>
      <div class="modal-body">
        <p>${esc(intro)}</p>
        <form id="pa-form" autocomplete="off">
          <label class="field"><span>应用名称 <b>*</b></span>
            <input id="pa-label" type="text" value="${esc(app?.label || "")}" placeholder="My App" ${builtin ? "disabled" : ""}>
          </label>
          <label class="field"><span>可执行文件 <b>*</b></span>
            <input id="pa-exe" type="text" value="${esc(app?.exe || "")}" placeholder="/opt/my-app/my-app" spellcheck="false">
          </label>
          <label class="field"><span>调试端口 <b>*</b></span>
            <input id="pa-port" type="number" min="1" max="65535" value="${esc(app?.port || 9222)}" ${builtin ? "disabled" : ""}>
          </label>
          <div class="form-status" id="pa-status"></div>
          <div class="actions"><button type="button" class="ghost" id="pa-cancel">取消</button><button type="submit" class="primary" id="pa-save">保存</button></div>
        </form>
      </div>`, { narrow: true });
    const close = () => closeModal();
    document.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
    document.getElementById("pa-cancel").onclick = close;
    document.getElementById("pa-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("pa-save");
      if (button.disabled) return;
      const exe = document.getElementById("pa-exe").value.trim();
      const label = document.getElementById("pa-label").value.trim();
      const port = Number(document.getElementById("pa-port").value);
      if (!exe) { setFormStatus("pa-status", "bad", "填可执行文件路径"); return; }
      if (!builtin && !label) { setFormStatus("pa-status", "bad", "填应用名称"); return; }
      if (!builtin && (!Number.isFinite(port) || port < 1 || port > 65535)) { setFormStatus("pa-status", "bad", "端口需要在 1–65535 之间"); return; }
      const body = builtin ? { id: app.id, exe } : { label, exe, port };
      button.disabled = true;
      button.textContent = "保存中…";
      try {
        await api("/api/plugins/apps", { body });
        closeModal();
        toast(builtin ? "已保存可执行文件路径" : "已添加应用", "ok");
        await loadPlugins();
      } catch (err) {
        setFormStatus("pa-status", "bad", esc(err.message));
        button.disabled = false;
        button.textContent = "保存";
      }
    });
  };

  const removeApp = async (app) => {
    try {
      const res = await api("/api/plugins/apps/remove", { body: { id: app.id } });
      if (!res.removed) throw new Error("没有找到这条自定义接入");
      toast(app.custom ? "应用已移除" : "已恢复默认路径", "ok");
      await loadPlugins();
    } catch (err) {
      toast(err.message, "bad");
    }
  };

  const loadPlugins = async () => {
    const catalog = document.getElementById("plugin-catalog");
    if (catalog) catalog.innerHTML = `<div class="empty"><span class="spinner"></span> 读取接入清单…</div>`;
    try { await loadState(); } catch (_) { /* keep the last state */ }
    try {
      doctor = await api("/api/doctor");
      doctorError = "";
    } catch (err) {
      doctor = null;
      doctorError = err.message;
    }
    try { await loadSurvey(); } catch (_) { /* CLI 区块保持空 */ }
    if (!document.getElementById("plugin-catalog")) return;
    renderCli();
    renderAlert();
    renderFamilies();
    renderDiscovered();
    renderCatalog();
    renderPath();
  };

  const discoverForm = document.getElementById("discover-form");
  const discoverInput = document.getElementById("discover-input");
  const discoverStart = document.getElementById("discover-start");
  const discoverProgress = document.getElementById("discover-progress");
  const discoverSteps = document.getElementById("discover-steps");
  const discoverLog = document.getElementById("discover-log");
  const discoverError = document.getElementById("discover-error");
  const discoverJobLink = document.getElementById("discover-job-link");

  discoverInput.addEventListener("input", () => {
    if (discoverError) discoverError.textContent = "";
  });

  discoverForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (discoverStart.disabled) return;
    const query = discoverInput.value.trim();
    if (!query) {
      if (discoverError) discoverError.textContent = "输入一个产品名，例如：加上 Kimi Work";
      discoverInput.focus();
      return;
    }
    discoverError.textContent = "";
    discoverStart.disabled = true;
    const old = discoverStart.textContent;
    discoverStart.textContent = "查找中…";
    discoverProgress.hidden = false;
    discoverSteps.textContent = "提交任务…";
    discoverLog.textContent = "";
    try {
      const data = await api("/api/jobs", { body: { kind: "discover", query } });
      const job = data.job;
      if (discoverJobLink) discoverJobLink.href = `#/logs/${encodeURIComponent(job.id)}`;
      let detail = job;
      while (true) {
        const response = await api(`/api/jobs/${encodeURIComponent(job.id)}`);
        detail = response.job || response;
        const tail = await api(`/api/jobs/${encodeURIComponent(job.id)}/log?lines=14`);
        discoverLog.textContent = tail.log || "";
        const statusLabel = {
          finished: "完成", failed: "失败", stopped: "已停止", interrupted: "中断", running: "进行中",
        }[detail.status] || detail.status;
        discoverSteps.textContent = detail.status === "running"
          ? "查找中：搜索产品、检查本机安装…"
          : `任务${statusLabel}`;
        if (detail.status !== "running") break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      if (detail.status !== "finished") {
        throw new Error((discoverLog.textContent || "").trim().split("\n").slice(-2).join(" ") ||
                        `发现任务结束：${detail.status || "未知状态"}`);
      }
      const before = new Set((STATE.discovered || []).map((item) => item.id));
      await loadPlugins();
      const fresh = (STATE.discovered || []).filter((item) => !before.has(item.id));
      if (fresh.length) {
        toast(`已加入：${fresh.map((item) => item.name).join("、")}`, "ok");
        if (document.getElementById("discovered-card")) {
          document.getElementById("discovered-card").scrollIntoView({ block: "start" });
        }
      } else {
        toast("已查完；如果是已收录产品，见上方产品谱系", "ok");
      }
    } catch (err) {
      discoverSteps.textContent = "没有完成";
      discoverError.textContent = err.message;
      discoverStart.disabled = false;
      discoverStart.textContent = old;
      return;
    }
    discoverStart.disabled = false;
    discoverStart.textContent = old;
  });

  document.getElementById("add-app").onclick = () => openAppModal();
  document.getElementById("plugins-refresh").onclick = loadPlugins;
  loadPlugins();
}
function setFieldError(id, message) {
  const field = document.getElementById(id);
  const err = document.getElementById(id + "-err");
  if (field) field.setAttribute("aria-invalid", "true");
  if (err) { err.textContent = message; err.classList.add("show"); }
}

function clearFieldError(id) {
  const field = document.getElementById(id);
  const err = document.getElementById(id + "-err");
  if (field) field.removeAttribute("aria-invalid");
  if (err) { err.textContent = ""; err.classList.remove("show"); }
}

function setFormStatus(id, kind, html) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = "form-status show" + (kind === "ok" || kind === "bad" || kind === "warn" ? " " + kind : "");
  el.innerHTML = html;
}

function readSettingsForm() {
  return {
    base: document.getElementById("f-base")?.value ?? "",
    model: document.getElementById("f-model")?.value ?? "",
    timeout: document.getElementById("f-timeout")?.value ?? "",
    key: document.getElementById("f-key")?.value ?? "",
  };
}

function restoreSettingsForm(snapshot) {
  const set = (id, value) => { const el = document.getElementById(id); if (el) el.value = value; };
  set("f-base", snapshot.base);
  set("f-model", snapshot.model);
  set("f-timeout", snapshot.timeout);
  set("f-key", snapshot.key);
  settingsDirty = true;
  const pill = document.getElementById("dirty-pill");
  if (pill) pill.hidden = false;
}

/* ---------- survey: dimensions / scenarios / runs / report ---------- */

const UNIT_LABEL = { ms: "ms", s: "s", min: "min", count: "", bool: "", score: "/5", percent: "%", text: "" };
const UNIT_HINT = { ms: "毫秒", s: "秒", min: "分钟", count: "次 / 个", bool: "是 / 否", score: "1–5", percent: "%", text: "文本" };
const METHOD_LABEL = { script: "脚本", human: "人", llm: "LLM" };
const AGG_LABEL = { last: "取最后", sum: "求和", avg: "平均", max: "取最大", min: "取最小" };
const CONF_LABEL = { single: "一次观察", repeat: "复现 ≥2 次", measured: "有实测数据" };
const RUN_STATUS = { ok: ["完成", "green"], failed: ["失败", "red"], timeout: ["超时", "amber"], blocked: ["受阻", "amber"] };

let SURVEY = null;
let APPS = null;
let surveyDim = "";
let reportTable = null;
let reportPicks = null;

function unitLabel(unit) { return UNIT_LABEL[unit] ?? unit; }
function methodLabel(method) { return METHOD_LABEL[method] || method; }
function dimById(id) { return (SURVEY?.dimensions || []).find((d) => d.id === id) || null; }
function scenarioById(id) { return (SURVEY?.scenarios || []).find((s) => s.id === id) || null; }
function productById(id) { return (SURVEY?.products || []).find((p) => p.id === id) || null; }

function runDraft() {
  const data = DRAFT.runs || {};
  const products = Array.isArray(data.products)
    ? data.products.filter((p) => p && typeof p.id === "string")
        .map((p) => ({ id: p.id, version: String(p.version || ""), model: String(p.model || "") }))
    : [];
  return {
    scenario: typeof data.scenario === "string" ? data.scenario : "",
    products,
    confidence: ["single", "repeat", "measured"].includes(data.confidence) ? data.confidence : "single",
  };
}

function saveRunDraft(patch) {
  DRAFT.runs = { ...runDraft(), ...patch };
  persistDrafts();
}

async function loadSurvey() {
  SURVEY = await api("/api/survey");
  return SURVEY;
}

function updateRunningNotice() {
  const box = document.getElementById("w-running");
  if (!box) return;
  const jobs = runningJobs();
  if (!jobs.length) { box.innerHTML = ""; return; }
  const job = jobs[0];
  const more = jobs.length > 1 ? `，另有 ${jobs.length - 1} 个` : "";
  box.innerHTML = `<div class="note warn" style="margin-bottom:14px">
    <b>${esc(jobTitle(job))}</b> 正在跑${esc(more)} · 已用 ${esc(fmtDur(elapsed(job)))}
    <a href="#/logs/${encodeURIComponent(job.id)}">看进度</a>
  </div>`;
}

/* ---- 维度编辑 ---- */

function indicatorRowHtml(ind = {}) {
  const units = Object.keys(UNIT_LABEL);
  const methods = Object.keys(METHOD_LABEL);
  const aggs = Object.keys(AGG_LABEL);
  return `<div class="ind-row" data-ind>
    <input class="ind-key" placeholder="key（英文）" value="${esc(ind.key || "")}" spellcheck="false">
    <input class="ind-label" placeholder="显示名" value="${esc(ind.label || "")}">
    <select class="ind-unit" title="单位">${units.map((u) => `<option value="${u}" ${ind.unit === u ? "selected" : ""}>${u}</option>`).join("")}</select>
    <select class="ind-method" title="采集方式">${methods.map((m) => `<option value="${m}" ${ind.method === m ? "selected" : ""}>${METHOD_LABEL[m]}</option>`).join("")}</select>
    <select class="ind-agg" title="跨运行聚合">${aggs.map((a) => `<option value="${a}" ${ind.aggregate === a ? "selected" : ""}>${AGG_LABEL[a]}</option>`).join("")}</select>
    <button type="button" class="icon ghost" data-del-ind title="删掉这一行" aria-label="删掉这一行">×</button>
  </div>`;
}

function turnRowHtml(text, index = 0) {
  return `<div class="turn-row" data-turn>
    <div class="turn-head"><span class="turn-n">第 ${index + 1} 轮</span>
      <button type="button" class="ghost sm danger-text" data-del-turn>删除</button></div>
    <textarea class="turn-text" rows="3" spellcheck="false" placeholder="这一轮要对产品说什么">${esc(text || "")}</textarea>
  </div>`;
}

function collectIndicators(box) {
  return [...box.querySelectorAll("[data-ind]")].map((row) => ({
    key: row.querySelector(".ind-key").value.trim(),
    label: row.querySelector(".ind-label").value.trim(),
    unit: row.querySelector(".ind-unit").value,
    method: row.querySelector(".ind-method").value,
    aggregate: row.querySelector(".ind-agg").value,
  })).filter((ind) => ind.key || ind.label);
}

function dimensionModal(dim) {
  const isNew = !dim;
  const d = dim || { id: "", name: "", note: "", indicators: [{}] };
  openModal(`
    <div class="modal-head">
      <div><h2 id="dlg-title">${isNew ? "新增维度" : "编辑维度"}</h2>
        <div class="sub">指标 key 定下就别改：报告靠它对齐历史数据。</div></div>
      <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">×</button>
    </div>
    <div class="modal-body">
      <div class="field-row">
        <label class="field"><span>名称</span><input id="dm-name" type="text" value="${esc(d.name)}" maxlength="40"></label>
        <label class="field"><span>id（英文）</span><input id="dm-id" type="text" value="${esc(d.id)}" ${isNew ? "" : "readonly"} spellcheck="false"></label>
      </div>
      <label class="field"><span>一句说明</span><input id="dm-note" type="text" value="${esc(d.note || "")}" maxlength="200" placeholder="这个维度看什么"></label>
      <div class="field-block">
        <span>指标</span>
        <div id="dm-inds">${(d.indicators.length ? d.indicators : [{}]).map(indicatorRowHtml).join("")}</div>
        <button type="button" class="ghost sm" id="dm-add">加一个指标</button>
        <div class="field-hint">key / 显示名 / 单位 / 采集方式 / 聚合方式。稳定性、成本这类跨运行指标用「求和 / 平均」。</div>
      </div>
      <div class="field-error" id="dm-err"></div>
    </div>
    <div class="modal-foot">
      <button type="button" data-close>取消</button>
      <button type="button" class="primary" id="dm-save">保存</button>
    </div>`);

  const box = document.getElementById("dm-inds");
  document.getElementById("dm-add").onclick = () => {
    box.insertAdjacentHTML("beforeend", indicatorRowHtml({}));
  };
  box.addEventListener("click", (event) => {
    const del = event.target.closest("[data-del-ind]");
    if (!del) return;
    if (box.querySelectorAll("[data-ind]").length > 1) del.closest("[data-ind]").remove();
    else toast("至少要留一个指标", "info");
  });
  document.getElementById("dm-save").onclick = async () => {
    const err = document.getElementById("dm-err");
    err.classList.remove("show");
    const payload = {
      id: document.getElementById("dm-id").value.trim(),
      name: document.getElementById("dm-name").value.trim(),
      note: document.getElementById("dm-note").value.trim(),
      indicators: collectIndicators(box),
    };
    try {
      await api("/api/survey/dimension/save", { body: { dimension: payload } });
      closeModal();
      await loadSurvey();
      surveyDim = payload.id;
      toast("维度已保存", "ok");
      viewDimensions();
    } catch (e) {
      err.textContent = e.message;
      err.classList.add("show");
    }
  };
}

/* ---- 场景编辑 ---- */

function scenarioModal(scenario) {
  const isNew = !scenario;
  const s = scenario || { id: "", title: "", kind: "manual", dimensions: surveyDim ? [surveyDim] : [], brief: "", command: { argv: [], timeout_s: 600 } };
  const picked = new Set(s.dimensions || []);
  openModal(`
    <div class="modal-head">
      <div><h2 id="dlg-title">${isNew ? "新增场景" : "编辑场景"}</h2>
        <div class="sub">场景是执行单位；它点亮哪些维度，就在运行页被哪些维度选中。</div></div>
      <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">×</button>
    </div>
    <div class="modal-body">
      <div class="field-row">
        <label class="field"><span>标题</span><input id="sc-title" type="text" value="${esc(s.title)}" maxlength="60" placeholder="P1 行内补全"></label>
        <label class="field"><span>id（英文）</span><input id="sc-id" type="text" value="${esc(s.id)}" ${isNew ? "" : "readonly"} spellcheck="false" placeholder="full-delivery"></label>
      </div>
      <div class="field-block">
        <span>点亮哪些维度</span>
        <div class="chip-row" id="sc-dims">
          ${(SURVEY?.dimensions || []).map((d) => `<label class="check"><input type="checkbox" value="${esc(d.id)}" ${picked.has(d.id) ? "checked" : ""}> <span>${esc(d.name)}</span></label>`).join("")}
        </div>
      </div>
      <label class="field"><span>一句话说明</span><input id="sc-brief" type="text" value="${esc(s.brief || "")}" maxlength="400" placeholder="这个场景让产品做什么"></label>
      <div class="field-block">
        <span>提示词（按轮次，原样发给产品）</span>
        <div id="sc-turns">${(s.prompts?.length ? s.prompts : [""]).map(turnRowHtml).join("")}</div>
        <button type="button" class="ghost sm" id="sc-add-turn">加一轮</button>
        <div class="field-hint">复杂场景要写具体的：改哪些文件、验收标准、不要动什么。第 3 轮那种打断也直接写成一轮。</div>
      </div>
      <div class="field-error" id="sc-err"></div>
    </div>
    <div class="modal-foot">
      <button type="button" data-close>取消</button>
      <button type="button" class="primary" id="sc-save">保存</button>
    </div>`);

  const turns = document.getElementById("sc-turns");
  const renumberTurns = () => {
    [...turns.querySelectorAll("[data-turn]")].forEach((row, index) => {
      row.querySelector(".turn-n").textContent = `第 ${index + 1} 轮`;
    });
  };
  document.getElementById("sc-add-turn").onclick = () => {
    turns.insertAdjacentHTML("beforeend", turnRowHtml(""));
    renumberTurns();
  };
  turns.addEventListener("click", (event) => {
    const del = event.target.closest("[data-del-turn]");
    if (!del) return;
    if (turns.querySelectorAll("[data-turn]").length > 1) {
      del.closest("[data-turn]").remove();
      renumberTurns();
    } else toast("至少留一轮", "info");
  });
  document.getElementById("sc-save").onclick = async () => {
    const err = document.getElementById("sc-err");
    err.classList.remove("show");
    const dims = [...document.querySelectorAll("#sc-dims input:checked")].map((i) => i.value);
    const payload = {
      id: document.getElementById("sc-id").value.trim(),
      title: document.getElementById("sc-title").value.trim(),
      kind: s.kind === "command" ? "command" : "manual",
      dimensions: dims,
      brief: document.getElementById("sc-brief").value.trim(),
      prompts: [...turns.querySelectorAll(".turn-text")].map((el) => el.value.trim()).filter(Boolean),
      command: s.command || {},
    };
    try {
      await api("/api/survey/scenario/save", { body: { scenario: payload } });
      closeModal();
      await loadSurvey();
      toast("场景已保存", "ok");
      viewDimensions();
    } catch (e) {
      err.textContent = e.message;
      err.classList.add("show");
    }
  };
}

/* ---- 维度页 ---- */

function scenarioNavHtml(dim, scenarios) {
  const runsFor = (id) => (SURVEY?.runs || []).filter((r) => r.scenario?.id === id);
  const rows = scenarios.map((s) => {
    const others = s.dimensions.filter((d) => d !== dim.id);
    const runs = runsFor(s.id);
    const last = runs[0];
    return `<div class="dim-scenario" data-open-sc="${esc(s.id)}" role="button" tabindex="0">
      <div class="dim-scenario-main">
        <div class="dim-scenario-title"><b>${esc(s.title)}</b>
          ${(s.prompts || []).length ? `<span class="pill">${s.prompts.length} 轮</span>` : ""}
          ${runs.length ? `<span class="pill green">${runs.length} 次数据</span>` : `<span class="pill amber">没跑过</span>`}</div>
        <div class="tiny">${esc(s.brief || "")}${last ? ` · 最近 ${esc(fmtShortTime(last.ts))}` : ""}</div>
        ${others.length ? `<div class="chip-row" style="margin-top:6px">${others.map((id) => `<span class="chip">${esc(dimById(id)?.name || id)}</span>`).join("")}</div>` : ""}
      </div>
      <div class="dim-scenario-actions">
        <button type="button" class="ghost sm" data-run-sc="${esc(s.id)}">去运行</button>
        <button type="button" class="ghost sm" data-edit-sc="${esc(s.id)}">编辑</button>
      </div>
    </div>`;
  }).join("");
  return `<div class="card-head">
      <div><h2>场景导航 · ${esc(dim.name)}</h2>
        <p class="hint">这些是「会点亮这个维度」的场景。点一行看详情，或直接去运行页只跑它。</p></div>
      <div class="actions" style="margin:0">
        <span class="pill">${scenarios.length} 个场景</span>
        <a class="ghost sm" href="#/scenarios">全部场景</a>
        <button type="button" class="ghost sm" id="dim-sc-new">新建场景</button>
      </div>
    </div>
    ${rows || emptyState("还没有场景点亮这个维度", "新建一个场景，或到别的维度下面挂一个共享场景。")}`;
}

function scenarioDetailModal(scenario) {
  const runs = (SURVEY?.runs || []).filter((r) => r.scenario?.id === scenario.id);

  openModal(`
    <div class="modal-head">
      <div><h2 id="dlg-title">${esc(scenario.title)}</h2>
        <div class="sub">${esc(scenario.brief || "")}</div></div>
      <button type="button" class="icon ghost" data-close title="关闭" aria-label="关闭">×</button>
    </div>
    <div class="modal-body">
      <div class="chip-row" style="margin-bottom:8px">
        ${scenario.dimensions.map((id) => `<span class="chip">${esc(dimById(id)?.name || id)}</span>`).join("")}
      </div>
      <div class="field-block"><span>提示词 · ${(scenario.prompts || []).length} 轮</span>
        <div class="prompt-list">${(scenario.prompts || []).map((text, index) => `<div class="prompt-turn"><span class="prompt-n">第 ${index + 1} 轮</span><p>${esc(text)}</p></div>`).join("") || `<div class="tiny">还没有提示词。</div>`}</div>
      </div>
      <h3 style="font-size:13px;margin:16px 0 8px">这个场景的记录 · ${runs.length}</h3>
      ${runs.length ? `<div class="matrix-wrap"><table class="result-table">
        <thead><tr><th>时间</th><th>产品</th><th>状态</th><th>指标</th></tr></thead>
        <tbody>${runs.slice(0, 8).map((run) => {
          const [label, tone] = RUN_STATUS[run.status] || [run.status || "—", ""];
          return `<tr><td class="mono">${esc(fmtShortTime(run.ts))}</td>
            <td>${esc(run.product?.name || "—")} <span class="dim">${esc(run.product?.version || "")}</span></td>
            <td><span class="pill ${tone}">${esc(label)}</span></td>
            <td class="mono">${(run.measurements || []).length}</td></tr>`;
        }).join("")}</tbody></table></div>` : emptyState("还没跑过", "去运行页跑一次，数据会出现在这里。")}
    </div>
    <div class="modal-foot">
      <button type="button" class="ghost sm danger-text" id="sc-detail-del">删除</button>
      <span class="spacer"></span>
      <button type="button" data-close>关闭</button>
      <button type="button" class="ghost" id="sc-detail-edit">编辑</button>
      <button type="button" class="primary" id="sc-detail-run">去运行</button>
    </div>`);
  document.getElementById("sc-detail-edit").onclick = () => { closeModal(); scenarioModal(scenario); };
  document.getElementById("sc-detail-del").onclick = () => {
    confirmAction({
      title: "删除场景",
      message: `删掉「${scenario.title}」？历史运行数据保留。`,
      confirmText: "删除", danger: true,
      onConfirm: async () => {
        try {
          await api("/api/survey/scenario/delete", { body: { id: scenario.id } });
          await loadSurvey();
          toast("场景已删除", "ok");
          viewDimensions();
        } catch (err) { toast(err.message, "bad"); }
      },
    });
  };
  document.getElementById("sc-detail-run").onclick = () => goRunScenario(scenario);
}

async function viewDimensions() {
  setCrumbs("维度");
  try {
    if (!SURVEY) await loadSurvey();
  } catch (err) {
    view.innerHTML = `<div class="card">${emptyState("读不到维度数据", err.message)}</div>`;
    return;
  }
  const dims = SURVEY.dimensions;
  if (!surveyDim || !dimById(surveyDim)) surveyDim = dims[0]?.id || "";
  const sel = dimById(surveyDim);
  const scenarios = sel ? SURVEY.scenarios.filter((s) => s.dimensions.includes(sel.id)) : [];

  view.innerHTML = `
    ${pageHead({
      eyebrow: "Dimensions",
      title: "维度",
      desc: `维度定义「看什么」，场景定义「怎么点亮它」。一次运行喂多个维度，所以运行的是场景，不是维度。配置存在 <code>${esc(SURVEY.store)}</code>。`,
      actions: `<button type="button" class="primary" id="dim-new">新增维度</button>`,
    })}
    <div class="grid">
      <div class="card">
        <div class="card-head"><div><h2>维度清单 · ${dims.length}</h2>
          <p class="hint">点一行切换右侧的场景导航。</p></div></div>
        <div class="dim-list" id="dim-list">
          ${dims.map((d) => {
            const measured = SURVEY.measured?.[d.id] || 0;
            return `<div class="dim-item ${d.id === surveyDim ? "on" : ""}" data-dim="${esc(d.id)}" role="button" tabindex="0">
              <div class="dim-item-top">
                <b>${esc(d.name)}</b>
                <span class="dim">${d.indicators.length} 指标 · ${SURVEY.coverage?.[d.id] || 0} 场景${measured ? ` · ${measured} 条数据` : ""}</span>
              </div>
              ${d.note ? `<div class="tiny">${esc(d.note)}</div>` : ""}
              <div class="chip-row" style="margin-top:6px">${d.indicators.map((i) => `<span class="chip">${esc(i.label)}</span>`).join("")}</div>
            </div>`;
          }).join("") || emptyState("还没有维度", "先建一个维度，再加指标。")}
        </div>
      </div>
      <div class="card" id="dim-side">
        ${sel ? scenarioNavHtml(sel, scenarios) : emptyState("选一个维度", "左边点一行。")}
        ${sel ? `<div class="divider"></div><div class="actions">
          <button type="button" class="ghost sm" id="dim-edit">编辑维度</button>
          <button type="button" class="ghost sm danger-text" id="dim-del">删除维度</button>
        </div>` : ""}
      </div>
    </div>`;

  document.getElementById("dim-new").onclick = () => dimensionModal(null);
  view.querySelectorAll("[data-dim]").forEach((row) => {
    const pick = () => { surveyDim = row.dataset.dim; viewDimensions(); };
    row.onclick = pick;
    row.onkeydown = (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); pick(); } };
  });
  if (!sel) return;
  document.getElementById("dim-edit").onclick = () => dimensionModal(sel);
  document.getElementById("dim-del").onclick = () => {
    confirmAction({
      title: "删除维度",
      message: `删掉「${sel.name}」？历史运行里的数据还在，但它会从场景和报告里消失。`,
      confirmText: "删除", danger: true,
      onConfirm: async () => {
        try {
          await api("/api/survey/dimension/delete", { body: { id: sel.id } });
          await loadSurvey();
          surveyDim = "";
          toast("维度已删除", "ok");
          viewDimensions();
        } catch (err) { toast(err.message, "bad"); }
      },
    });
  };
  document.getElementById("dim-sc-new").onclick = () => scenarioModal(null);
  view.querySelectorAll("[data-edit-sc]").forEach((btn) => {
    btn.onclick = (event) => { event.stopPropagation(); scenarioModal(scenarioById(btn.dataset.editSc)); };
  });
  view.querySelectorAll("[data-run-sc]").forEach((btn) => {
    btn.onclick = (event) => {
      event.stopPropagation();
      goRunScenario(scenarioById(btn.dataset.runSc));
    };
  });
  view.querySelectorAll("[data-open-sc]").forEach((row) => {
    const open = () => scenarioDetailModal(scenarioById(row.dataset.openSc));
    row.onclick = open;
    row.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    };
  });
}

let scenarioFilter = "all";

function appStatusPill(product) {
  const blocked = product.runnable === false;
  if (!product.app_id) {
    if ((product.form || "") === "cli") {
      return blocked
        ? `<span class="pill amber" title="${esc(product.why || "")}">CLI 不可体验</span>`
        : `<span class="pill green">CLI 可体验</span>`;
    }
    return `<span class="pill">${esc(FORM_LABEL[product.form] || product.form || "—")}</span>`;
  }
  if (blocked) {
    return `<span class="pill amber" title="${esc(product.why || "")}">不可体验</span>`;
  }
  const app = (APPS || []).find((item) => item.id === product.app_id);
  if (!app) return `<span class="pill">未接入</span>`;
  if (app.running && app.port_open) return `<span class="pill green">运行中 · ${app.port}</span>`;
  if (app.running) return `<span class="pill amber">运行中 · 无调试端口</span>`;
  if (app.installed) return `<span class="pill amber">已安装 · 未启动</span>`;
  return `<span class="pill">未安装</span>`;
}

function scenarioCardHtml(s) {
  const runs = (SURVEY?.runs || []).filter((r) => r.scenario?.id === s.id);
  const last = runs[0];
  return `<div class="dim-scenario" data-open-sc="${esc(s.id)}" role="button" tabindex="0">
    <div class="dim-scenario-main">
      <div class="dim-scenario-title"><b>${esc(s.title)}</b>
        ${(s.prompts || []).length ? `<span class="pill">${s.prompts.length} 轮</span>` : ""}
        ${runs.length ? `<span class="pill green">${runs.length} 次数据</span>` : `<span class="pill">没跑过</span>`}</div>
      <div class="tiny">${esc(s.brief || "")}${last ? ` · 最近 ${esc(fmtShortTime(last.ts))}` : ""}</div>
      <div class="chip-row" style="margin-top:6px">${s.dimensions.map((id) => `<span class="chip">${esc(dimById(id)?.name || id)}</span>`).join("")}</div>
    </div>
    <div class="dim-scenario-actions">
      <button type="button" class="primary sm" data-run-sc="${esc(s.id)}">去运行</button>
      <button type="button" class="ghost sm" data-edit-sc="${esc(s.id)}">编辑</button>
      <button type="button" class="ghost sm danger-text" data-del-sc="${esc(s.id)}">删除</button>
    </div>
  </div>`;
}

function deleteScenario(scenario) {
  confirmAction({
    title: "删除场景",
    message: `删掉「${scenario.title}」？历史运行数据保留。`,
    confirmText: "删除", danger: true,
    onConfirm: async () => {
      try {
        await api("/api/survey/scenario/delete", { body: { id: scenario.id } });
        await loadSurvey();
        toast("场景已删除", "ok");
        if (current.page === "scenarios") viewScenarios(); else viewDimensions();
      } catch (err) { toast(err.message, "bad"); }
    },
  });
}

async function viewScenarios() {
  setCrumbs("场景");
  try {
    await loadSurvey();
  } catch (err) {
    view.innerHTML = `<div class="card">${emptyState("读不到场景数据", err.message)}</div>`;
    return;
  }
  const scenarios = SURVEY.scenarios;
  const shown = scenarioFilter === "all"
    ? scenarios : scenarios.filter((s) => s.dimensions.includes(scenarioFilter));

  view.innerHTML = `
    ${pageHead({
      eyebrow: "Scenarios",
      title: "场景",
      desc: "场景就是「做一件具体的事」：一段多轮提示词 + 它自然照到的维度。运行页拿它去跑每个产品。",
      actions: `<button type="button" class="primary" id="sc-new">新建场景</button>`,
    })}
    <div class="card">
      <div class="card-head"><div><h2>按维度筛</h2>
        <p class="hint">一个场景可能同时挂在几个维度下；这里只是换视角，不改变归属。</p></div>
        <span class="pill">${shown.length} / ${scenarios.length}</span></div>
      <div class="chip-row" id="sc-filter">
        <button type="button" class="chip ${scenarioFilter === "all" ? "on" : ""}" data-f="all">全部</button>
        ${SURVEY.dimensions.map((d) => `<button type="button" class="chip ${scenarioFilter === d.id ? "on" : ""}" data-f="${esc(d.id)}">${esc(d.name)}</button>`).join("")}
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><div><h2>场景清单</h2>
        <p class="hint">点一行看详情；「去运行」会带着它的维度跳到运行页。</p></div></div>
      <div class="dim-list">
        ${shown.map(scenarioCardHtml).join("") || emptyState("这个维度下还没有场景", "点右上角「新建场景」，或换个筛选。")}
      </div>
    </div>`;

  document.getElementById("sc-new").onclick = () => scenarioModal(null);
  view.querySelectorAll("#sc-filter [data-f]").forEach((btn) => {
    btn.onclick = () => { scenarioFilter = btn.dataset.f; viewScenarios(); };
  });
  view.querySelectorAll("[data-run-sc]").forEach((btn) => {
    btn.onclick = (event) => { event.stopPropagation(); goRunScenario(scenarioById(btn.dataset.runSc)); };
  });
  view.querySelectorAll("[data-edit-sc]").forEach((btn) => {
    btn.onclick = (event) => { event.stopPropagation(); scenarioModal(scenarioById(btn.dataset.editSc)); };
  });
  view.querySelectorAll("[data-del-sc]").forEach((btn) => {
    btn.onclick = (event) => { event.stopPropagation(); deleteScenario(scenarioById(btn.dataset.delSc)); };
  });
  view.querySelectorAll("[data-open-sc]").forEach((row) => {
    const open = () => scenarioDetailModal(scenarioById(row.dataset.openSc));
    row.onclick = open;
    row.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); }
    };
  });
}

function goRunScenario(scenario) {
  if (!scenario) return;
  saveRunDraft({ scenario: scenario.id });
  closeModal();
  if (current.page === "runs") viewRuns();
  else location.hash = "#/runs";
}

/* ---- 运行页 ---- */

function productOptionsHtml(current) {
  const products = SURVEY?.products || [];
  if (!products.length) return `<option value="">（产品谱系是空的）</option>`;
  const groups = new Map();
  products.forEach((p) => {
    const key = p.family || "其他";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  });
  return [...groups.entries()].map(([family, items]) => `<optgroup label="${esc(family)}">
    ${items.map((p) => `<option value="${esc(p.id)}" ${p.id === current ? "selected" : ""}>${esc(p.name)}${p.form ? ` · ${esc(p.form)}` : ""}</option>`).join("")}
  </optgroup>`).join("");
}

async function viewRuns() {
  setCrumbs("运行");
  try {
    await loadSurvey();  // 回到这个页面就重新读一次：刚跑完的 run 要能看见
  } catch (err) {
    view.innerHTML = `<div class="card">${emptyState("读不到维度数据", err.message)}</div>`;
    return;
  }
  try { APPS = (await api("/api/apps")).apps; } catch (_) { APPS = APPS || []; }
  const d = runDraft();
  if (!d.scenario || !scenarioById(d.scenario)) {
    d.scenario = SURVEY.scenarios[0]?.id || "";
    if (d.scenario) saveRunDraft({ scenario: d.scenario });
  }
  const scenario = scenarioById(d.scenario);
  const selected = new Map(d.products.map((p) => [p.id, p]));
  const runs = SURVEY.runs || [];

  const covered = scenario ? scenario.dimensions : [];
  const missing = scenario ? SURVEY.dimensions.filter((dim) => !covered.includes(dim.id)) : [];

  const runsFor = (productId) => runs.filter((run) => run.scenario?.id === scenario?.id
    && run.product?.id === productId).length;
  const usable = [...selected.keys()].filter((id) => (productById(id)?.runnable) !== false);
  const blocked = selected.size - usable.length;

  view.innerHTML = `
    ${pageHead({
      eyebrow: "Runs",
      title: "运行",
      desc: "一个场景 × 多个产品，跑完再对比。场景是「做一件具体的事」，它会同时照到好几个维度；照不到的维度这次就没有数据。",
      actions: `<a class="pill blue" href="#/report">看报告</a>`,
    })}
    <div id="w-running"></div>
    <div class="grid">
      <div class="card">
        <div class="card-head"><div><h2>场景</h2><p class="hint">选这轮要做什么事；多轮对话也算在场景里。</p></div>
          ${scenario && scenario.prompts?.length ? `<span class="pill">${scenario.prompts.length} 轮</span>` : ""}</div>
        <label class="field"><span>场景</span>
          <select id="run-scenario">
            ${(SURVEY.scenarios || []).map((s) => `<option value="${esc(s.id)}" ${s.id === d.scenario ? "selected" : ""}>${esc(s.title)}</option>`).join("")}
          </select>
        </label>
        ${scenario ? `
          <div class="tiny" style="margin-bottom:10px">${esc(scenario.brief || "")}</div>
          <div class="field-block">
            <span>覆盖的维度 · ${covered.length} / ${SURVEY.dimensions.length}</span>
            <div class="chip-row">
              ${covered.map((id) => `<span class="chip on">${esc(dimById(id)?.name || id)}</span>`).join("")}
              ${missing.map((dim) => `<span class="chip" title="这个场景照不到">${esc(dim.name)}</span>`).join("")}
            </div>
            ${missing.length ? `<div class="field-hint">灰色的是这次照不到的维度，跑完它们不会有数据——这是正常的，不用为了凑满去加场景。</div>` : `<div class="field-hint">八个维度都被这个场景照到了。</div>`}
          </div>
          ${scenario.prompts?.length ? `<div class="field-block">
            <span>提示词 · ${scenario.prompts.length} 轮（运行时会原样发给产品）</span>
            <div class="prompt-list">${scenario.prompts.map((p, i) => `<div class="prompt-turn"><span class="prompt-n">第 ${i + 1} 轮</span><p>${esc(p)}</p></div>`).join("")}</div>
          </div>` : ""}
        ` : emptyState("还没有场景", "先去「场景」页建一个。")}
        <div class="actions" style="margin-top:12px">
          <button type="button" class="ghost sm" id="run-edit-scenario" ${scenario ? "" : "disabled"}>编辑场景</button>
        </div>
        <div class="divider"></div>
        <div class="actions">
          <button type="button" class="primary" id="run-start" ${usable.length && !blocked ? "" : "disabled"}>开始自动体验${selected.size ? `（${selected.size} 个产品）` : ""}</button>
          <span class="tiny" id="run-start-hint" style="margin:0">${!selected.size ? "至少勾一个产品" : blocked ? `${blocked} 个产品还不能自动体验` : ""}</span>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><div><h2>产品</h2><p class="hint">同一轮里勾几个产品，就跑几次同一个场景。</p></div>
          <span class="pill" id="run-count">已选 ${selected.size}</span></div>
        <div class="dim-list scroll" id="run-products">
          ${(SURVEY.products || []).map((product) => {
            const picked = selected.get(product.id);
            const done = runsFor(product.id);
            return `<label class="dim-item dim-check ${picked ? "on" : ""}" data-product="${esc(product.id)}">
              <input type="checkbox" value="${esc(product.id)}" ${picked ? "checked" : ""}>
              <span class="dim-check-body">
                <span class="dim-item-top"><b>${esc(product.name)}</b>
                  <span class="dim">${appStatusPill(product)} ${esc(product.family || "")}${done ? ` · 跑过 ${done} 次` : ""}</span></span>
                <span class="field-row" style="margin-top:4px">
                  <input class="prod-version" data-role="version" type="text" placeholder="版本" value="${esc(picked?.version || "")}" ${picked ? "" : "disabled"}>
                  <input class="prod-model" data-role="model" type="text" placeholder="模型" value="${esc(picked?.model || "")}" ${picked ? "" : "disabled"}>
                </span>
              </span>
            </label>`;
          }).join("") || emptyState("产品谱系是空的", "先到「接入」页加一个产品。")}
        </div>
        <div class="note" style="margin-top:12px">报告按 <code>产品 id + 版本</code> 分列：版本不同就是两列。</div>
      </div>
    </div>
    <div class="card" style="margin-top:14px">
      <div class="card-head"><div><h2>最近运行 · ${runs.length}</h2><p class="hint">一次运行 = 一个产品 × 一个场景。点一行看明细。</p></div></div>
      <div id="run-list">${runs.length ? runsTableHtml(runs) : emptyState("还没有记录", "跑完第一条就会出现在这里。")}</div>
    </div>`;

  const scenarioSelect = document.getElementById("run-scenario");
  scenarioSelect.onchange = () => { saveRunDraft({ scenario: scenarioSelect.value }); viewRuns(); };

  view.querySelectorAll("[data-product]").forEach((row) => {
    const id = row.dataset.product;
    const box = row.querySelector("input[type=checkbox]");
    const version = row.querySelector('[data-role="version"]');
    const model = row.querySelector('[data-role="model"]');
    const sync = () => {
      const current = runDraft();
      const rest = current.products.filter((p) => p.id !== id);
      if (box.checked) rest.push({ id, version: version.value, model: model.value });
      saveRunDraft({ products: rest });
      document.getElementById("run-count").textContent = `已选 ${rest.length}`;
      viewRuns();
    };
    box.onchange = sync;
    version.oninput = () => {
      const current = runDraft();
      const entry = current.products.find((p) => p.id === id);
      if (entry) { entry.version = version.value; saveRunDraft({ products: current.products }); }
    };
    model.oninput = () => {
      const current = runDraft();
      const entry = current.products.find((p) => p.id === id);
      if (entry) { entry.model = model.value; saveRunDraft({ products: current.products }); }
    };
    [version, model].forEach((input) => {
      input.onclick = (event) => event.stopPropagation();
      input.onkeydown = (event) => event.stopPropagation();
    });
  });

  if (scenario) {
    document.getElementById("run-edit-scenario").onclick = () => scenarioModal(scenario);
    const config = document.getElementById("run-config-collector");
    if (config) config.onclick = () => scenarioModal(scenario);
  }

  document.getElementById("run-start").onclick = async () => {
    if (!scenario) return;
    const payload = runDraft().products.map((picked) => {
      const meta = productById(picked.id) || {};
      return { id: picked.id, app_id: meta.app_id || "", name: meta.name || picked.id,
               family: meta.family || "", version: picked.version, model: picked.model };
    });
    if (!payload.length) { toast("至少勾一个产品", "bad"); return; }
    try {
      const res = await api("/api/survey/batch", { body: { scenario_id: scenario.id, products: payload } });
      toast(`已开始：${scenario.title} × ${payload.length} 个产品`, "ok");
      location.hash = `#/logs/${encodeURIComponent(res.job.id)}`;
    } catch (err) { toast(err.message, "bad"); }
  };

  view.querySelectorAll("[data-open-run]").forEach((row) => {
    row.onclick = () => runDetailModal(null, row.dataset.openRun);
  });
  updateRunningNotice();
}

function runsTableHtml(runs) {
  return `<div class="matrix-wrap"><table class="result-table">
    <thead><tr><th>时间</th><th>产品</th><th>场景</th><th>状态</th><th>指标</th><th>方式</th></tr></thead>
    <tbody>${runs.map((run) => {
      const [label, tone] = RUN_STATUS[run.status] || [run.status || "—", ""];
      return `<tr data-open-run="${esc(run.run_id)}" class="row-click">
        <td class="mono">${esc(fmtShortTime(run.ts))}</td>
        <td>${esc(run.product?.name || "—")} <span class="dim">${esc(run.product?.version || "")}</span></td>
        <td>${esc(run.scenario?.title || run.scenario?.id || "—")}</td>
        <td><span class="pill ${tone}">${esc(label)}</span></td>
        <td class="mono">${(run.measurements || []).length}</td>
        <td class="mono">${esc(methodLabel(run.method))} · ${esc(CONF_LABEL[run.confidence] || run.confidence || "")}</td>
      </tr>`;
    }).join("")}</tbody></table></div>`;
}

function runDetailModal(_unused, runId) {
  const run = (SURVEY?.runs || []).find((r) => r.run_id === runId);
  if (!run) { toast("这条运行记录不在最近 50 条里", "info"); return; }
  const rows = (run.measurements || []).map((m) => `<tr>
    <td>${esc(dimById(m.dimension)?.name || m.dimension)}</td>
    <td>${esc(m.indicator)}</td>
    <td class="mono">${esc(m.value)}${esc(unitLabel(m.unit))}</td>
    <td>${esc(methodLabel(m.method))}</td>
    <td class="mono">${esc(m.evidence || "—")}</td>
  </tr>`).join("");
  openModal(`
    <div class="modal-head"><div><h2 id="dlg-title">${esc(run.scenario?.title || run.run_id)}</h2>
      <div class="sub">${esc(run.product?.name || "")} ${esc(run.product?.version || "")} · ${esc(fmtTime(run.ts))}</div></div>
      <button type="button" class="icon ghost" data-close title="关闭">×</button></div>
    <div class="modal-body">
      ${run.notes ? `<p>${esc(run.notes)}</p>` : ""}
      ${rows ? `<div class="matrix-wrap"><table class="result-table">
        <thead><tr><th>维度</th><th>指标</th><th>值</th><th>方式</th><th>证据</th></tr></thead>
        <tbody>${rows}</tbody></table></div>` : emptyState("这条运行没有量到指标", "命令跑完了，但输出里没有对得上的键。")}
      <div class="tiny" style="margin-top:10px">run_id：${esc(run.run_id)}</div>
    </div>
    <div class="modal-foot"><button type="button" data-close>关闭</button></div>`);
}

/* ---- 报告页 ---- */

function reportCellHtml(cell) {
  if (!cell) return `<span class="dim">—</span>`;
  return cell.items.map((item) => `<span class="m-item">${esc(item.label)}
    <b>${esc(item.text)}${esc(unitLabel(item.unit))}</b>
    <span class="dim">${esc(methodLabel(item.method))}·${item.count}</span></span>`).join("");
}

async function viewReport() {
  setCrumbs("报告");
  try {
    await loadSurvey();
    if (!reportPicks) reportPicks = new Set(SURVEY.dimensions.map((d) => d.id));
    const qs = reportPicks.size && reportPicks.size < SURVEY.dimensions.length
      ? `?dimensions=${encodeURIComponent([...reportPicks].join(","))}` : "";
    reportTable = await api(`/api/survey/report${qs}`);
  } catch (err) {
    view.innerHTML = `<div class="card">${emptyState("读不到报告", err.message)}</div>`;
    return;
  }
  const table = reportTable;
  const products = table.products;
  view.innerHTML = `
    ${pageHead({
      eyebrow: "Report",
      title: "报告",
      desc: "行是维度，列是产品。格子里只有量到的值：方法、次数都标出来；没数据就是空。",
      actions: `<button type="button" class="ghost" id="rep-export">导出 Markdown</button>`,
    })}
    <div class="card">
      <div class="card-head"><div><h2>维度筛选</h2><p class="hint">取消勾选只是换视角，不会删数据。</p></div>
        <span class="pill" id="rep-count">${table.dimensions.length} / ${SURVEY.dimensions.length}</span></div>
      <div class="chip-row" id="rep-picks">
        ${SURVEY.dimensions.map((d) => `<button type="button" class="chip ${reportPicks.has(d.id) ? "on" : ""}" data-pick="${esc(d.id)}">${esc(d.name)}</button>`).join("")}
      </div>
    </div>
    ${products.length ? `<div class="card" style="margin-top:14px">
      <div class="matrix-wrap"><table class="result-table matrix">
        <thead><tr><th>维度</th>${products.map((p) => `<th>${esc(p.label)}</th>`).join("")}</tr></thead>
        <tbody>${table.dimensions.map((dim) => `<tr>
          <td><b>${esc(dim.name)}</b>${dim.note ? `<div class="tiny">${esc(dim.note)}</div>` : ""}</td>
          ${products.map((p) => {
            const cell = table.cells[`${dim.id}|${p.key}`];
            return `<td class="m-cell" data-cell="${esc(dim.id)}" data-prod="${esc(p.key)}">${reportCellHtml(cell)}</td>`;
          }).join("")}
        </tr>`).join("")}</tbody>
      </table></div>
    </div>` : `<div class="card" style="margin-top:14px">${emptyState("还没有任何运行记录", "去运行页选一个产品，先跑一条。", `<a class="pill blue" href="#/runs">去运行</a>`)}</div>`}
    ${table.missing.length ? `<div class="note warn" style="margin-top:12px">这些维度还没有数据：${table.missing.map((id) => `<b>${esc(dimById(id)?.name || id)}</b>`).join("、")}</div>` : ""}`;

  view.querySelectorAll("[data-pick]").forEach((btn) => {
    btn.onclick = () => {
      const id = btn.dataset.pick;
      if (reportPicks.has(id) && reportPicks.size === 1) { toast("至少留一个维度", "info"); return; }
      if (reportPicks.has(id)) reportPicks.delete(id); else reportPicks.add(id);
      viewReport();
    };
  });
  view.querySelectorAll(".m-cell").forEach((cell) => {
    cell.onclick = () => {
      const dim = dimById(cell.dataset.cell);
      const product = products.find((p) => p.key === cell.dataset.prod);
      const data = table.cells[`${cell.dataset.cell}|${cell.dataset.prod}`];
      if (!dim || !data) return;
      openModal(`
        <div class="modal-head"><div><h2 id="dlg-title">${esc(dim.name)} · ${esc(product?.label || "")}</h2>
          <div class="sub">${data.runs} 次运行；同一个指标可能既有脚本又有人的记录。</div></div>
          <button type="button" class="icon ghost" data-close title="关闭">×</button></div>
        <div class="modal-body"><div class="matrix-wrap"><table class="result-table">
          <thead><tr><th>指标</th><th>值</th><th>方式</th><th>次数</th><th>证据</th></tr></thead>
          <tbody>${data.items.map((item) => `<tr>
            <td>${esc(item.label)}</td>
            <td class="mono">${esc(item.text)}${esc(unitLabel(item.unit))}</td>
            <td>${esc(methodLabel(item.method))}</td>
            <td class="mono">${item.count}</td>
            <td class="mono">${esc(item.evidence || "—")}</td>
          </tr>`).join("")}</tbody></table></div></div>
        <div class="modal-foot"><button type="button" data-close>关闭</button></div>`);
    };
  });
  document.getElementById("rep-export").onclick = async () => {
    try {
      const dims = [...reportPicks];
      const res = await api("/api/survey/export", { body: { title: "能力画像", dimensions: dims } });
      toast("已导出", "ok");
      openTextPreview({ path: res.path, name: "report.md", text: true });
    } catch (err) { toast(err.message, "bad"); }
  };
}

/* ---------- jobs list ---------- */

function refreshJobsTick() {
  // Do not yank focus or a text selection out from under a keyboard user.
  const active = document.activeElement;
  if (active && active.closest && active.closest("#jobs-list, #jobs-stats")) return;
  renderJobsPage();
}

function filterJobs() {
  const q = jobsUI.q.trim().toLowerCase();
  const status = jobsUI.filter;
  return (STATE.jobs || []).filter((job) => {
    if (status === "running" && job.status !== "running") return false;
    if (status === "finished" && job.status !== "finished") return false;
    if (status === "attention" && !["failed", "stopped", "interrupted"].includes(job.status)) return false;
    if (!q) return true;
    const text = [job.id, job.title, job.kind, job.status, ...(jobSub(job))]
      .join(" ").toLowerCase();
    return text.includes(q);
  }).sort((a, b) => {
    if (a.status === "running" && b.status !== "running") return -1;
    if (b.status === "running" && a.status !== "running") return 1;
    return String(b.started_at || "").localeCompare(String(a.started_at || ""));
  });
}

function statButton(filter, label, count, tone = "") {
  return `<button type="button" class="stat ${tone} ${jobsUI.filter === filter ? "on" : ""}" data-filter="${filter}">
    <span class="k">${esc(label)}</span><span class="v">${count}</span>
  </button>`;
}

function renderJobsPage() {
  if (!STATE) return;
  const list = document.getElementById("jobs-list");
  if (!list) return;
  const jobs = STATE.jobs || [];
  const count = (fn) => jobs.filter(fn).length;
  const stats = document.getElementById("jobs-stats");
  if (stats) {
    stats.innerHTML = [
      statButton("all", "全部日志", jobs.length),
      statButton("running", "运行中", count((j) => j.status === "running"), "running"),
      statButton("finished", "已完成", count((j) => j.status === "finished")),
      statButton("attention", "需关注", count((j) => ["failed", "stopped", "interrupted"].includes(j.status)), "bad"),
    ].join("");
    stats.querySelectorAll("[data-filter]").forEach((btn) => {
      btn.onclick = () => { jobsUI.filter = btn.dataset.filter; renderJobsPage(); };
    });
  }
  const filtered = filterJobs();
  const meta = document.getElementById("jobs-meta");
  if (meta) meta.textContent = jobsUI.q || jobsUI.filter !== "all"
    ? `${filtered.length} / ${jobs.length} 条 · 5s 刷新`
    : `最近 ${jobs.length} 条 · 5s 刷新`;
  if (!filtered.length) {
    list.innerHTML = emptyState(
      jobs.length ? "没有匹配的运行日志" : "还没有运行日志",
      jobs.length ? "换个关键词或筛选条件试试。" : "去「运行」发起一次自动体验，跑完就在这里看日志和产物。",
      jobs.length
        ? `<button type="button" class="ghost" id="jobs-clear">清空筛选</button>`
        : `<a class="pill blue" href="#/runs">去运行</a>`,
    );
    const clear = document.getElementById("jobs-clear");
    if (clear) clear.onclick = () => {
      jobsUI = { filter: "all", q: "" };
      const input = document.getElementById("jobs-search");
      if (input) input.value = "";
      renderJobsPage();
    };
    return;
  }
  list.innerHTML = `<div class="run-list">${filtered.map((job) => {
    const duration = elapsed(job);
    const sub = jobSub(job);
    return `<a class="run-line ${job.status === "running" ? "running" : ""}" href="#/logs/${encodeURIComponent(job.id)}">
      <span class="run-status">${statusChip(job.status)}</span>
      <span class="run-main">
        <span class="run-title">${esc(jobTitle(job))}</span>
        <span class="run-sub"><span class="mono">${esc(job.id)}</span>${sub.map((s) => `<span>· ${esc(s)}</span>`).join("")}</span>
      </span>
      <span class="run-when">${esc(fmtShortTime(job.started_at))}<small>${esc(fmtRelative(job.started_at))}</small></span>
      <span class="run-dur">${esc(fmtDur(duration))}</span>
      ${icon('<path d="m9 6 6 6-6 6"/>', "chev")}
    </a>`;
  }).join("")}</div>`;
}

function viewJobs() {
  setCrumbs("日志");
  const jobs = STATE.jobs || [];
  view.innerHTML = `
    ${pageHead({
      eyebrow: "Logs",
      title: "运行日志",
      desc: "每次运行对应 runs/ 下的一个目录；点进去看结果、日志和产物。",
      actions: `<a class="pill blue" href="#/runs">去运行</a>`,
    })}
    <div class="stats" id="jobs-stats"></div>
    <div class="card">
      <div class="jobs-toolbar">
        <div class="task-search">
          ${icon('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4 4"/>')}
          <input id="jobs-search" type="search" placeholder="搜索 run id / 场景 / 产品" value="${esc(jobsUI.q)}" autocomplete="off">
        </div>
        <span class="meta" id="jobs-meta"></span>
      </div>
      <div id="jobs-list">${jobs.length ? "" : emptyState("还没有运行日志", "去「运行」发起一次自动体验。", `<a class="pill blue" href="#/runs">去运行</a>`)}</div>
    </div>`;
  const search = document.getElementById("jobs-search");
  search.addEventListener("input", () => { jobsUI.q = search.value; renderJobsPage(); });
  renderJobsPage();
}

/* ---------- job detail ---------- */

function viewJob(id) {
  setCrumbs(`日志 / <span class="mono">${esc(id)}</span>`);
  view.innerHTML = skeletonCard();
  detailState = {
    id, tab: null, detail: null, log: "", renderedLog: null,
    filesQuery: "", autoFollow: true, built: false, lastStatus: "", filesKey: "",
  };
  if (jobTimer) clearInterval(jobTimer);
  const tick = async () => {
    if (!detailState || detailState.id !== id) return;
    if (document.visibilityState !== "visible") return;
    const st = detailState;
    try {
      const [detail, log] = await Promise.all([
        api(`/api/jobs/${encodeURIComponent(id)}`),
        api(`/api/jobs/${encodeURIComponent(id)}/log?lines=500`),
      ]);
      if (!detailState || detailState.id !== id) return;
      const wasRunning = st.detail?.job?.status === "running";
      st.detail = detail;
      st.log = log.log || "";
      if (!st.tab) st.tab = detail.job.status === "running" || detail.job.kind === "discover" ? "log" : "overview";
      const filesKey = `${detail.files.length}:${detail.files.map((f) => f.path).join(",")}`;
      const statusChanged = st.lastStatus !== detail.job.status;
      const filesChanged = st.filesKey !== filesKey;
      if (!st.built) {
        buildJobShell();
        st.built = true;
        renderJobTab();
      } else {
        refreshJobHeader();
        if (statusChanged) {
          renderJobTab();
        } else if (filesChanged && st.tab === "files") renderJobTab();
        else if (st.tab === "log") updateLog();
      }
      st.lastStatus = detail.job.status;
      st.filesKey = filesKey;
      if (detail.job.status !== "running") {
        clearInterval(jobTimer);
        jobTimer = null;
        if (wasRunning) toast("运行已结束", "info");
        loadState().catch(() => {});
      }
    } catch (err) {
      if (!detailState || detailState.id !== id) return;
      clearInterval(jobTimer);
      jobTimer = null;
      renderJobError(err);
    }
  };
  tick();
  jobTimer = setInterval(tick, 2000);
}

function buildJobShell() {
  const st = detailState;
  const job = st.detail.job;
  const files = st.detail.files || [];
  view.innerHTML = `
    <div class="page-head job-head">
      <div>
        <p class="eyebrow">Run · ${esc(job.id)}</p>
        <div class="job-title-line"><h1>${esc(jobTitle(job))}</h1><span id="job-status">${statusChip(job.status)}</span></div>
        <div class="job-sub">
          <span class="mono">${pathHtml(job.run_dir || "")}</span>
          <span>开始 ${esc(fmtTime(job.started_at))}</span>
          <span id="job-dur">耗时 ${esc(fmtDur(elapsed(job)))}</span>
          <span id="job-exit">${job.returncode != null ? `exit ${esc(job.returncode)}` : ""}</span>
        </div>
        <div class="job-badges" id="job-badges">
          ${jobMetaBits(job).map((b) => `<span class="pill">${esc(b)}</span>`).join("")}
        </div>
      </div>
      <div class="job-actions" id="job-actions">
        <span id="job-stop-wrap">${job.status === "running" ? `<button type="button" class="danger" id="job-stop">停止运行</button>` : ""}</span>
        <button type="button" class="ghost" id="job-back">返回日志</button>
      </div>
    </div>
    <div class="tabs" id="job-tabs">
      <button type="button" data-tab="overview">概览</button>
      <button type="button" data-tab="log">日志</button>
      <button type="button" data-tab="files">产物 <span class="count" id="tab-files-count">${files.length}</span></button>
      <span class="spacer"></span>
      <button type="button" class="ghost sm" id="job-refresh" title="立即刷新">刷新数据</button>
    </div>
    <div id="tab-panel"></div>`;
  view.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.onclick = () => { st.tab = btn.dataset.tab; renderJobTab(); };
  });
  document.getElementById("job-back").onclick = () => go("#/logs");
  document.getElementById("job-refresh").onclick = async () => {
    try {
      const detail = await api(`/api/jobs/${encodeURIComponent(st.id)}`);
      const log = await api(`/api/jobs/${encodeURIComponent(st.id)}/log?lines=500`);
      if (!detailState || detailState !== st) return;
      st.detail = detail; st.log = log.log || "";
      st.summaryLoaded = false; st.findingsLoaded = false;
      st.summaryError = ""; st.findingsError = "";
      refreshJobHeader();
      renderJobTab();
      toast("已刷新", "ok");
    } catch (err) { toast(err.message, "bad"); }
  };
  bindStopButton();
}

function refreshJobHeader() {
  const st = detailState;
  if (!st?.detail) return;
  const job = st.detail.job;
  const status = document.getElementById("job-status");
  if (status) status.innerHTML = statusChip(job.status);
  const dur = document.getElementById("job-dur");
  if (dur) dur.textContent = `耗时 ${fmtDur(elapsed(job))}`;
  const exit = document.getElementById("job-exit");
  if (exit) exit.textContent = job.returncode != null ? `exit ${job.returncode}` : "";
  const badge = document.getElementById("job-dialog-badge");
  const count = document.getElementById("tab-files-count");
  if (count) count.textContent = String((st.detail.files || []).length);
  const stopWrap = document.getElementById("job-stop-wrap");
  if (stopWrap) {
    const hasStop = Boolean(document.getElementById("job-stop"));
    if (job.status === "running" && !hasStop) {
      stopWrap.innerHTML = `<button type="button" class="danger" id="job-stop">停止运行</button>`;
      bindStopButton();
    } else if (job.status !== "running" && hasStop) {
      stopWrap.innerHTML = "";
    }
  }
}

function bindStopButton() {
  const stop = document.getElementById("job-stop");
  if (!stop) return;
  stop.onclick = () => {
    const st = detailState;
    if (!st) return;
    confirmAction({
      title: "停止这次运行？",
      message: "会向整个进程组发 SIGTERM。已经写出的日志和产物会保留，但这次 run 会标记为「已停止」。",
      confirmText: "停止运行",
      danger: true,
      onConfirm: async () => {
        try {
          await api(`/api/jobs/${encodeURIComponent(st.id)}/stop`, { body: {} });
          toast("已发送停止信号", "ok");
        } catch (err) {
          toast(err.message, "bad");
        }
      },
    });
  };
}

function renderJobTab() {
  const st = detailState;
  if (!st?.detail) return;
  if (!st.tab) st.tab = st.detail.job.status === "running" ? "log" : "overview";
  view.querySelectorAll("#job-tabs [data-tab]").forEach((btn) => {
    btn.classList.toggle("on", btn.dataset.tab === st.tab);
  });
  const panel = document.getElementById("tab-panel");
  if (!panel) return;
  if (st.tab === "overview") renderOverview();
  else if (st.tab === "log") renderLogPanel();
  else renderFiles();
}

function renderOverview() {
  const st = detailState;
  const job = st.detail.job;
  const files = st.detail.files || [];
  const meta = job.meta || {};
  const items = [];
  if (job.kind === "survey") {
    if (meta.scenario_id) items.push(["场景", meta.scenario_id]);
    if ((meta.products || []).length) items.push(["产品", meta.products.join(", ")]);
    if (meta.product?.name) items.push(["产品", meta.product.name]);
  }
  items.push(["开始", fmtTime(job.started_at)]);
  items.push(["耗时", fmtDur(elapsed(job))]);
  items.push(["退出码", job.returncode == null ? "—" : String(job.returncode)]);
  const panel = document.getElementById("tab-panel");
  panel.innerHTML = `
    <div class="overview-grid">
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h2>运行信息</h2><p class="hint">这次 run 的上下文和命令。</p></div></div>
          <div class="meta-grid">
            ${items.map(([k, v]) => `<div class="meta-item"><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div></div>`).join("")}
          </div>
          <dl class="state-list">
            <div><dt>run 目录</dt><dd class="mono">${pathHtml(job.run_dir || "—")}
              ${job.run_dir ? `<button type="button" class="icon ghost" data-copy="${esc(absRunPath(job))}" title="复制完整路径" aria-label="复制完整路径">${icon('<path d="M9 9h9v11H9z"/><path d="M5 15V4h9"/>')}</button>` : ""}
            </dd></div>
            <div><dt>产物</dt><dd>${files.length} 个文件（含工作区）· ${files.filter((f) => f.image).length} 张截图</dd></div>
          </dl>
          <details class="prep" style="margin-top:12px">
            <summary>启动命令</summary>
            <div class="prep-body"><pre class="modal-pre" style="max-height:180px; width:100%">${esc((job.argv || []).join(" "))}</pre></div>
          </details>
        </div>
      </div>
      <div class="stack">
        <div class="card">
          <div class="card-head"><div><h2>快速查看</h2><p class="hint">先去日志看时序，或直接翻产物。</p></div></div>
          <div class="actions" style="margin:0">
            <button type="button" class="ghost" data-switch-tab="log">看日志</button>
            <button type="button" class="ghost" data-switch-tab="files">看产物</button>
            ${job.run_dir ? `<button type="button" class="ghost" data-copy="${esc(absRunPath(job))}">复制 run 路径</button>` : ""}
          </div>
        </div>
      </div>
    </div>`;
  panel.querySelectorAll("[data-switch-tab]").forEach((btn) => {
    btn.onclick = () => { if (detailState) { detailState.tab = btn.dataset.switchTab; renderJobTab(); } };
  });
  panel.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.onclick = () => copyText(btn.dataset.copy);
  });
}

function renderLogPanel() {
  const st = detailState;
  const job = st.detail.job;
  const panel = document.getElementById("tab-panel");
  panel.innerHTML = `
    <div class="log-toolbar">
      <span class="live ${job.status === "running" ? "" : "off"}"><i></i>${job.status === "running" ? "实时日志 · 每 2 秒刷新" : "运行已结束 · 日志已定格"}</span>
      <span class="tiny" id="log-lines" style="margin:0"></span>
      <span class="spacer"></span>
      <button type="button" class="ghost sm" id="log-follow">跟随最新</button>
    </div>
    <div class="log-shell">
      <pre class="log" id="logbox"></pre>
      <button type="button" class="ghost sm jump" id="jump-latest" hidden>↓ 跳到最新</button>
    </div>`;
  const box = document.getElementById("logbox");
  const follow = document.getElementById("log-follow");
  const jump = document.getElementById("jump-latest");
  const updateFollow = () => {
    if (follow) follow.className = "ghost sm" + (st.autoFollow ? "" : "");
    if (follow) {
      follow.textContent = st.autoFollow ? "跟随最新：开" : "跟随最新：关";
      follow.setAttribute("aria-pressed", String(st.autoFollow));
    }
    if (jump) jump.hidden = st.autoFollow;
  };
  if (follow) follow.onclick = () => { st.autoFollow = !st.autoFollow; updateFollow(); if (st.autoFollow) updateLog(true); };
  if (jump) jump.onclick = () => { st.autoFollow = true; updateFollow(); updateLog(true); };
  box.addEventListener("scroll", () => {
    const near = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
    if (near !== st.autoFollow) {
      st.autoFollow = near;
      updateFollow();
    }
  });
  updateFollow();
  st.renderedLog = null;
  updateLog(true);
}

function logHtml(text) {
  if (!text || !text.trim()) return `<span class="ln dim">（暂无输出）</span>`;
  return text.split("\n").map((line) => {
    let cls = "ln";
    if (/^===/.test(line) || /^---/.test(line)) cls += " meta";
    else if (/\b(error|failed|failure|traceback|fatal)\b/i.test(line) || /\brc=[1-9]\d*\b/.test(line)) cls += " err";
    else if (/\b(warn|warning|blocked|unknown)\b/i.test(line)) cls += " warn";
    else if (/\b(pass|passed|ok)\b/i.test(line)) cls += " ok";
    return `<span class="${cls}">${esc(line) || " "}</span>`;
  }).join("");
}

function updateLog(force = false) {
  const st = detailState;
  const box = document.getElementById("logbox");
  if (!st || !box) return;
  const text = st.log || "";
  if (!force && text === st.renderedLog) return;
  const stick = st.autoFollow;
  const oldTop = box.scrollTop;
  box.innerHTML = logHtml(text);
  st.renderedLog = text;
  if (stick) box.scrollTop = box.scrollHeight;
  else box.scrollTop = oldTop;
  const lines = document.getElementById("log-lines");
  if (lines) lines.textContent = `${text.split("\n").filter(Boolean).length} 行`;
}

function renderFiles() {
  const st = detailState;
  const job = st.detail.job;
  const files = st.detail.files || [];
  const panel = document.getElementById("tab-panel");
  const q = st.filesQuery.trim().toLowerCase();
  const match = (f) => !q || relPath(job, f).toLowerCase().includes(q);
  const workspace = files.filter((f) => isWorkspaceFile(f) && match(f));
  const primary = files.filter((f) => !isWorkspaceFile(f) && match(f));
  const images = primary.filter((f) => isImageFile(f));
  const docs = primary.filter((f) => !isImageFile(f));
  const active = document.activeElement;
  const wasSearch = Boolean(active && active.id === "files-search");
  const caret = wasSearch ? active.selectionStart : null;
  const resultsOpen = panel.querySelector('[data-group="results"]')?.open ?? true;
  const workspaceOpen = panel.querySelector('[data-group="workspace"]')?.open ?? false;
  panel.innerHTML = `
    <div class="file-toolbar">
      <div class="task-search">
        ${icon('<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4 4"/>')}
        <input id="files-search" type="search" placeholder="筛选文件名 / 路径" value="${esc(st.filesQuery)}" autocomplete="off">
      </div>
      <span class="meta">${primary.length} 个结果文件 · ${workspace.length} 个工作区文件</span>
    </div>
    ${images.length ? `<div class="card-head" style="margin-bottom:9px"><div><h2 style="font-size:13px">截图</h2></div><span class="tiny" style="margin:0">${images.length} 张 · 点击看原图</span></div>
      <div class="gallery">${images.map((f) => `<button type="button" class="shot" data-image="${esc(f.path)}">
        <span class="img-wrap"><img loading="lazy" src="${esc(fileUrl(f.path))}" alt="${esc(f.name)}"></span>
        <span class="cap">${esc(relPath(job, f))}</span></button>`).join("")}</div>` : ""}
    ${docs.length ? `<details class="file-group" data-group="results" ${resultsOpen ? "open" : ""}>
      <summary>结果与报告 <span class="n">${docs.length}</span></summary>
      <div class="file-list">${docs.map((f) => fileRow(job, f)).join("")}</div>
    </details>` : ""}
    ${workspace.length ? `<details class="file-group" data-group="workspace" ${q || workspaceOpen ? "open" : ""}>
      <summary>工作区文件 <span class="n">${workspace.length}</span></summary>
      <div class="file-list">${workspace.map((f) => fileRow(job, f)).join("")}</div>
    </details>` : ""}
    ${!primary.length && !workspace.length ? `<div class="empty">${q ? "没有匹配的文件" : "还没有产物"}</div>` : ""}
    ${!primary.length && workspace.length && !q ? `<div class="note" style="margin-top:10px">结果文件还没有出现；工作区里的源码和 .git 默认收起，展开可以看。</div>` : ""}`;
  const search = document.getElementById("files-search");
  if (wasSearch) {
    search.focus();
    if (caret != null) search.setSelectionRange(caret, caret);
  }
  search.addEventListener("input", () => {
    st.filesQuery = search.value;
    renderFiles();
  });
  panel.querySelectorAll("[data-image]").forEach((btn) => {
    btn.onclick = () => {
      const list = images;
      openLightbox(list, list.findIndex((f) => f.path === btn.dataset.image));
    };
  });
  panel.querySelectorAll("[data-file]").forEach((btn) => {
    btn.onclick = () => {
      const file = files.find((f) => f.path === btn.dataset.file);
      if (!file) return;
      if (isImageFile(file)) {
        openLightbox(images, images.findIndex((f) => f.path === file.path));
      } else if (isTextFile(file)) {
        openTextPreview(file);
      } else {
        window.open(fileUrl(file.path), "_blank", "noopener");
      }
    };
  });
}

function fileRow(job, file) {
  const name = relPath(job, file);
  const text = isTextFile(file) ? "预览" : isImageFile(file) ? "看原图" : "打开";
  return `<button type="button" class="file-row" data-file="${esc(file.path)}" title="${esc(name)} · ${esc(text)}">
    <span class="fname">${esc(name)}</span>
    <span class="fsize">${esc(fmtBytes(file.size))}</span>
    <span class="ftime">${esc(fmtShortTime(file.mtime))}</span>
    ${icon('<path d="M9 6l6 6-6 6"/>')}
  </button>`;
}

function renderJobError(err) {
  view.innerHTML = `
    <div class="page-head"><div><p class="eyebrow">Run</p><h1>读不到这个 run</h1>
      <p>${esc(err.message)}</p></div></div>
    <div class="card">${emptyState("服务端没有返回这个 run 的详情", "可能是记录被删了，或服务刚重启。",
      `<button type="button" class="ghost" id="job-retry">重试</button><a class="pill blue" href="#/logs">返回日志</a>`)}</div>`;
  document.getElementById("job-retry").onclick = () => route();
}

/* ---------- router / boot ---------- */

function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function route() {
  closeModal();
  const raw = location.hash.replace(/^#\/?/, "").replace(/\/$/, "");
  const [head, id] = raw.split("/");
  const aliases = { settings: "config", jobs: "logs" };
  const page = aliases[head] || head || "config";
  current = { page, id: id || "" };
  if (aliases[head]) {
    history.replaceState(null, "", `#/${page}${id ? "/" + id : ""}`);
  }
  const titles = { config: "配置", plugins: "接入", dimensions: "维度", scenarios: "场景", runs: "运行", report: "报告", walkthrough: "运行", eval: "运行", logs: id ? `日志 · ${id}` : "日志" };
  document.title = `${titles[page] || "能力工作台"} · 能力工作台`;
  paintNav(page);
  if (jobTimer) { clearInterval(jobTimer); jobTimer = null; }
  detailState = null;
  const known = ["config", "plugins", "dimensions", "scenarios", "runs", "report", "walkthrough", "eval", "logs"];
  if (!known.includes(page)) { location.hash = "#/config"; return; }
  if (page === "config") return viewSettings();
  if (page === "plugins") return viewPlugins();
  if (page === "dimensions") return viewDimensions();
  if (page === "scenarios") return viewScenarios();
  if (page === "runs") return viewRuns();
  if (page === "walkthrough") { location.hash = "#/runs"; return; }
  if (page === "eval") { location.hash = "#/runs"; return; }
  if (page === "report") return viewReport();
  if (page === "logs") return id ? viewJob(id) : viewJobs();
  return viewSettings();
}

async function hardRefresh() {
  const button = document.getElementById("refresh");
  if (button) button.disabled = true;
  const snapshot = settingsDirty && current.page === "config" ? readSettingsForm() : null;
  try {
    await loadState();
    route();
    if (snapshot) restoreSettingsForm(snapshot);
    toast("已刷新", "ok");
  } catch (err) {
    setConn(false);
    toast(err.message, "bad");
  } finally {
    if (button) button.disabled = false;
  }
}

window.addEventListener("hashchange", route);
document.getElementById("refresh").onclick = hardRefresh;
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    if (current.page === "logs" && current.id && !jobTimer && !detailState) viewJob(current.id);
    refreshStateTick();
  }
});

(async () => {
  try {
    await loadState();
  } catch (err) {
    setConn(false);
    paintNav("config");
    setCrumbs("配置");
    view.innerHTML = `<div class="page-head"><div><p class="eyebrow">Offline</p><h1>连不上工作台服务</h1>
      <p>${esc(err.message)}</p></div></div>
    <div class="card">${emptyState("服务没有响应", "确认 python3 workbench/server.py 或 ./start.sh 还在跑。",
      `<button type="button" class="ghost" id="boot-retry">重试</button>`)}</div>`;
    document.getElementById("boot-retry").onclick = () => location.reload();
    return;
  }
  if (!location.hash) history.replaceState(null, "", "#/config");
  route();
  setInterval(refreshStateTick, 5000);
})();
