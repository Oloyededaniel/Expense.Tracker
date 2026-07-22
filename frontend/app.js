// ============================================================================
// Ledger & Lens - frontend logic
// Same-origin: backend serves the frontend, so no absolute API host needed.
// ============================================================================
const API_BASE = "";

let authMode = "login";
let authToken = localStorage.getItem("ll_token") || null;
let currentUsername = localStorage.getItem("ll_username") || null;

const CATEGORY_COLORS = [
  "#D4A24E", "#6FBF97", "#E2725B", "#8AA9C8", "#C9A0DC",
  "#E9C784", "#7FB3B0", "#D08770", "#A9AFB8", "#B08DD8", "#5FAF9F",
];

// ---------------------------------------------------------------------------
// Auth screen wiring
// ---------------------------------------------------------------------------
function setAuthMode(mode) {
  authMode = mode;
  document.getElementById("tabLoginBtn").classList.toggle("active", mode === "login");
  document.getElementById("tabSignupBtn").classList.toggle("active", mode === "signup");
  document.getElementById("incomeField").classList.toggle("hidden", mode === "login");
  document.getElementById("authSubmitBtn").textContent = mode === "login" ? "Log In" : "Create account";
  document.getElementById("password").setAttribute(
    "autocomplete", mode === "login" ? "current-password" : "new-password"
  );
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const income = parseFloat(document.getElementById("income").value) || 0;
  const errorEl = document.getElementById("authError");
  errorEl.classList.add("hidden");

  const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/signup";
  const body = authMode === "login"
    ? { username, password }
    : { username, password, monthly_income: income };

  try {
    const res = await fetch(API_BASE + endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Something went wrong");

    authToken = data.access_token;
    currentUsername = data.username;
    localStorage.setItem("ll_token", authToken);
    localStorage.setItem("ll_username", currentUsername);
    enterApp();
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove("hidden");
  }
  return false;
}

function logout() {
  authToken = null;
  currentUsername = null;
  localStorage.removeItem("ll_token");
  localStorage.removeItem("ll_username");
  document.getElementById("appScreen").classList.add("hidden");
  document.getElementById("authScreen").classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: {
      ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${authToken}`,
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    logout();
    throw new Error("Session expired, please log in again");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3200);
}

// ---------------------------------------------------------------------------
// App entry
// ---------------------------------------------------------------------------
function enterApp() {
  document.getElementById("authScreen").classList.add("hidden");
  document.getElementById("appScreen").classList.remove("hidden");
  document.getElementById("welcomeUser").textContent = `@${currentUsername}`;
  document.getElementById("txnDate").valueAsDate = new Date();
  refreshEverything();
}

function showSection(name) {
  document.querySelectorAll(".section").forEach((s) => s.classList.remove("active"));
  document.getElementById(`section-${name}`).classList.add("active");
  document.querySelectorAll(".nav-tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.section === name)
  );
  if (name === "insights") loadInsightsTab();
}

async function refreshEverything() {
  await Promise.all([loadSummary(), loadTransactions(), loadPersona(), loadHeatmap()]);
}

// ---------------------------------------------------------------------------
// Dashboard: summary + charts
// ---------------------------------------------------------------------------
let trendChart, donutChart, forecastChart;

async function loadSummary() {
  try {
    const summary = await api("/api/insights/summary");
    document.getElementById("statTotal").textContent = formatMoney(summary.total_spent);
    document.getElementById("statMonth").textContent = formatMoney(summary.current_month_total);

    renderDonut(summary.category_totals);
    renderTrend(summary.monthly_trend);
  } catch (err) {
    console.error(err);
  }

  try {
    const forecast = await api("/api/insights/forecast");
    if (forecast.risk_week) {
      const rw = forecast.risk_week;
      document.getElementById("statRiskWeek").textContent =
        `${rw.start_date.slice(5)} → ${rw.end_date.slice(5)}`;
    } else {
      document.getElementById("statRiskWeek").textContent = "Need more data";
    }
    renderForecastChart(forecast);
  } catch (err) {
    console.error(err);
  }
}

function renderDonut(categoryTotals) {
  const ctx = document.getElementById("chartDonut");
  const labels = Object.keys(categoryTotals);
  const values = Object.values(categoryTotals);
  if (donutChart) donutChart.destroy();
  donutChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: labels.map((_, i) => CATEGORY_COLORS[i % CATEGORY_COLORS.length]),
        borderColor: "#1A222D",
        borderWidth: 2,
      }],
    },
    options: {
      plugins: {
        legend: { position: "right", labels: { color: "#EDEAE3", font: { family: "IBM Plex Mono", size: 11 } } },
      },
    },
  });
}

function renderTrend(monthlyTrend) {
  const ctx = document.getElementById("chartTrend");
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: monthlyTrend.map((m) => m.month),
      datasets: [{
        label: "Monthly spend",
        data: monthlyTrend.map((m) => m.total),
        backgroundColor: "#D4A24E",
        borderRadius: 2,
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { color: "#A9AFB8", font: { family: "IBM Plex Mono", size: 10 } }, grid: { color: "#2B3542" } },
        y: { ticks: { color: "#A9AFB8", font: { family: "IBM Plex Mono", size: 10 } }, grid: { color: "#2B3542" } },
      },
    },
  });
}

function renderForecastChart(forecast) {
  const ctx = document.getElementById("chartForecast");
  if (!forecast.forecast || forecast.forecast.length === 0) {
    document.getElementById("forecastNote").textContent =
      forecast.message || "Not enough data yet.";
    if (forecastChart) { forecastChart.destroy(); forecastChart = null; }
    return;
  }
  document.getElementById("forecastNote").textContent =
    "Solid line = history, dashed = 30-day AI forecast with confidence band";

  const historyLabels = forecast.history.map((h) => h.date);
  const historyData = forecast.history.map((h) => h.actual);
  const forecastLabels = forecast.forecast.map((f) => f.date);
  const forecastData = forecast.forecast.map((f) => f.predicted);
  const upperData = forecast.forecast.map((f) => f.upper);
  const lowerData = forecast.forecast.map((f) => f.lower);

  const labels = [...historyLabels, ...forecastLabels];
  const nullPad = (arr, padLen, before) =>
    before ? [...arr, ...Array(padLen).fill(null)] : [...Array(padLen).fill(null), ...arr];

  if (forecastChart) forecastChart.destroy();
  forecastChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Actual",
          data: nullPad(historyData, forecastLabels.length, true),
          borderColor: "#EDEAE3",
          backgroundColor: "transparent",
          pointRadius: 0,
          tension: 0.25,
        },
        {
          label: "Forecast",
          data: nullPad(forecastData, historyLabels.length, false),
          borderColor: "#D4A24E",
          borderDash: [4, 3],
          backgroundColor: "transparent",
          pointRadius: 0,
          tension: 0.25,
        },
        {
          label: "Upper bound",
          data: nullPad(upperData, historyLabels.length, false),
          borderColor: "rgba(212,162,78,0.25)",
          backgroundColor: "rgba(212,162,78,0.08)",
          pointRadius: 0,
          fill: "+1",
        },
        {
          label: "Lower bound",
          data: nullPad(lowerData, historyLabels.length, false),
          borderColor: "rgba(212,162,78,0.25)",
          backgroundColor: "transparent",
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: "#EDEAE3", font: { family: "IBM Plex Mono", size: 10 } } } },
      scales: {
        x: { ticks: { color: "#A9AFB8", maxTicksLimit: 8, font: { family: "IBM Plex Mono", size: 9 } }, grid: { display: false } },
        y: { ticks: { color: "#A9AFB8", font: { family: "IBM Plex Mono", size: 10 } }, grid: { color: "#2B3542" } },
      },
    },
  });
}

// ---------------------------------------------------------------------------
// Heatmap calendar
// ---------------------------------------------------------------------------
async function loadHeatmap() {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  try {
    const data = await api(`/api/insights/heatmap?year=${year}&month=${month}`);
    renderHeatmap(data);
  } catch (err) {
    console.error(err);
  }
}

function renderHeatmap(data) {
  const { year, month, daily_totals } = data;
  const dowEl = document.getElementById("heatmapDow");
  const gridEl = document.getElementById("heatmapGrid");
  dowEl.innerHTML = "";
  gridEl.innerHTML = "";

  ["S", "M", "T", "W", "T", "F", "S"].forEach((d) => {
    const el = document.createElement("div");
    el.className = "heatmap-dow";
    el.textContent = d;
    dowEl.appendChild(el);
  });

  const firstDay = new Date(year, month - 1, 1);
  const daysInMonth = new Date(year, month, 0).getDate();
  const startOffset = firstDay.getDay();
  const totals = Object.values(daily_totals);
  const maxVal = Math.max(...totals, 1);

  document.getElementById("heatmapLabel").textContent =
    `${firstDay.toLocaleString("default", { month: "long" })} ${year}, day by day`;

  for (let i = 0; i < startOffset; i++) {
    const filler = document.createElement("div");
    gridEl.appendChild(filler);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const val = daily_totals[day] || 0;
    const intensity = val / maxVal;
    const cell = document.createElement("div");
    cell.className = "heatmap-cell";
    cell.textContent = day;
    cell.title = `$${val.toFixed(2)}`;
    cell.style.background = intensity === 0
      ? "transparent"
      : `rgba(226,114,91,${(0.12 + intensity * 0.75).toFixed(2)})`;
    gridEl.appendChild(cell);
  }
}

// ---------------------------------------------------------------------------
// Transactions
// ---------------------------------------------------------------------------
async function loadTransactions() {
  try {
    const txns = await api("/api/transactions");
    renderTransactionTable(txns);
    document.getElementById("statAnomalies").textContent =
      txns.filter((t) => t.is_anomaly).length;
  } catch (err) {
    console.error(err);
  }
}

function renderTransactionTable(txns) {
  const tbody = document.getElementById("txnTableBody");
  tbody.innerHTML = "";
  txns.forEach((t) => {
    const tr = document.createElement("tr");
    if (t.is_anomaly) tr.classList.add("anomaly-row");
    tr.innerHTML = `
      <td class="num">${t.date}</td>
      <td>${escapeHtml(t.description)}</td>
      <td><span class="cat-pill">${escapeHtml(t.category)}</span> <span class="badge-source">${t.category_source}</span></td>
      <td class="amount-cell">${formatMoney(t.amount)}</td>
      <td><button class="row-btn" onclick="deleteTransaction(${t.id})">remove</button></td>
    `;
    tbody.appendChild(tr);
  });
}

async function handleAddTransaction(event) {
  event.preventDefault();
  const date = document.getElementById("txnDate").value;
  const description = document.getElementById("txnDesc").value.trim();
  const amount = parseFloat(document.getElementById("txnAmount").value);
  const category = document.getElementById("txnCategory").value.trim() || null;
  const resultEl = document.getElementById("addTxnResult");

  try {
    const txn = await api("/api/transactions", {
      method: "POST",
      body: JSON.stringify({ date, description, amount, category }),
    });
    resultEl.textContent = `Categorized as "${txn.category}" (${txn.category_source})`;
    document.getElementById("txnDesc").value = "";
    document.getElementById("txnAmount").value = "";
    document.getElementById("txnCategory").value = "";
    await refreshEverything();
  } catch (err) {
    showToast(err.message);
  }
  return false;
}

async function deleteTransaction(id) {
  try {
    await api(`/api/transactions/${id}`, { method: "DELETE" });
    await refreshEverything();
  } catch (err) {
    showToast(err.message);
  }
}

async function handleCsvUpload(event) {
  const file = event.target.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append("file", file);
  const resultEl = document.getElementById("csvResult");
  resultEl.textContent = "Uploading & categorizing…";
  try {
    const res = await fetch(`${API_BASE}/api/transactions/upload-csv`, {
      method: "POST",
      headers: { Authorization: `Bearer ${authToken}` },
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");
    resultEl.textContent = `Imported ${data.created} transactions` +
      (data.errors.length ? ` (${data.errors.length} rows skipped)` : "");
    await refreshEverything();
  } catch (err) {
    resultEl.textContent = err.message;
  }
  event.target.value = "";
}

// ---------------------------------------------------------------------------
// Insights tab: persona + budget
// ---------------------------------------------------------------------------
async function loadPersona() {
  try {
    const persona = await api("/api/insights/persona");
    const badge = document.getElementById("personaBadge");
    if (persona.persona && persona.persona !== "Getting Started") {
      badge.textContent = persona.persona;
      badge.classList.remove("hidden");
    }
    document.getElementById("personaName").textContent = persona.persona;
    document.getElementById("personaConfidence").textContent =
      persona.confidence ? `Confidence: ${(persona.confidence * 100).toFixed(0)}%` : "";
  } catch (err) {
    console.error(err);
  }
}

async function loadInsightsTab() {
  try {
    const budgets = await api("/api/insights/budget");
    const tbody = document.getElementById("budgetTableBody");
    tbody.innerHTML = "";
    budgets.forEach((b) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td><span class="cat-pill">${escapeHtml(b.category)}</span></td>
        <td class="amount-cell">${formatMoney(b.current_avg_monthly)}</td>
        <td class="amount-cell num" style="color:var(--brass);">${formatMoney(b.recommended_budget)}</td>
        <td style="font-size:12.5px; color:var(--paper-dim);">${escapeHtml(b.note)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error(err);
  }
}

// ---------------------------------------------------------------------------
// Ask Your Ledger (NL query)
// ---------------------------------------------------------------------------
async function handleAskQuestion(event) {
  event.preventDefault();
  const input = document.getElementById("askInput");
  const question = input.value.trim();
  if (!question) return false;
  appendChat(question, "user");
  input.value = "";

  try {
    const result = await api("/api/insights/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    let html = escapeHtml(result.answer);
    if (result.rows && result.rows.length) {
      html += `<table class="ledger-table" style="margin-top:8px;"><tbody>`;
      result.rows.slice(0, 8).forEach((r) => {
        html += `<tr><td class="num">${r.date}</td><td>${escapeHtml(r.description)}</td><td><span class="cat-pill">${escapeHtml(r.category)}</span></td><td class="amount-cell">${formatMoney(r.amount)}</td></tr>`;
      });
      html += `</tbody></table>`;
    }
    appendChat(html, "ai", true);
  } catch (err) {
    appendChat(err.message, "ai");
  }
  return false;
}

function appendChat(content, who, isHtml = false) {
  const log = document.getElementById("chatLog");
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${who === "user" ? "chat-user" : "chat-ai"}`;
  if (isHtml) bubble.innerHTML = content; else bubble.textContent = content;
  log.appendChild(bubble);
  log.scrollTop = log.scrollHeight;
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function formatMoney(n) {
  return `$${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// PWA service worker registration
// ---------------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch((err) => console.warn("SW registration failed", err));
  });
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
if (authToken && currentUsername) {
  enterApp();
}
