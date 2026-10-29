const form = document.querySelector("#expense-form");
const list = document.querySelector("#expense-list");
const summary = document.querySelector("#summary");
const errorBox = document.querySelector("#form-error");
const monthInput = document.querySelector("#month");
const exportLink = document.querySelector("#export-link");

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function monthQuery() {
  return monthInput.value ? `?month=${encodeURIComponent(monthInput.value)}` : "";
}

function renderSummary(data) {
  const rows = (data.by_category || []).map((item) =>
    `<li><span>${esc(item.category)}</span><b>${(item.total_cents / 100).toFixed(2)} 元</b><em>${item.count} 笔</em></li>`
  ).join("");
  summary.innerHTML = `<div class="total">合计 <strong>${(data.total_cents / 100).toFixed(2)}</strong> 元</div><ul>${rows || "<li>这个月还没有支出</li>"}</ul>`;
}

function renderExpenses(rows) {
  list.innerHTML = rows.map((item) => `<article class="item">
    <div><b>${esc(item.category)}</b><span>${esc(item.spent_on)}${item.note ? " · " + esc(item.note) : ""}</span></div>
    <strong>${(item.amount_cents / 100).toFixed(2)} 元</strong>
    <button data-delete="${item.id}" type="button">删除</button>
  </article>`).join("") || "<p class=\"empty\">还没有记录，先记第一笔。</p>";
}

async function load() {
  const [expenses, stats] = await Promise.all([
    fetch(`/expenses${monthQuery()}`).then((r) => r.json()),
    fetch(`/summary${monthQuery()}`).then((r) => r.json()),
  ]);
  renderExpenses(expenses.expenses || []);
  renderSummary(stats);
  exportLink.href = `/export.csv${monthQuery()}`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.textContent = "";
  const data = new FormData(form);
  const payload = {
    amount_cents: Math.round(Number(data.get("amount")) * 100),
    category: data.get("category"),
    spent_on: data.get("spent_on"),
    note: data.get("note") || "",
  };
  const response = await fetch("/expenses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    errorBox.textContent = body.error || "保存失败";
    return;
  }
  form.reset();
  await load();
});

list.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-delete]");
  if (!button) return;
  await fetch(`/expenses/${button.dataset.delete}`, { method: "DELETE" });
  await load();
});

monthInput.addEventListener("change", load);
load();
