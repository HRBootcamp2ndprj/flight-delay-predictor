// ───────── 설정 ─────────

// 위험도는 확률에서 파생되는 표현일 뿐이므로 프론트에서 계산한다 (CONTEXT.md).
// 결항은 기본 발생률이 훨씬 낮으므로 기준을 따로 둔다.
const RISK_THRESHOLDS = {
  delay: { medium: 0.2, high: 0.35 },
  cancel: { medium: 0.02, high: 0.05 },
};
const BOOKING_WINDOW_DAYS = 365; // 서버와 동일
const RECENT_KEY = "recentQueries";
const RECENT_MAX = 5;

const $ = (id) => document.getElementById(id);
const form = $("predict-form");
let OPTIONS = { airlines: [], airports: [] };
const byCode = {};

// ───────── 유틸 ─────────

function localISODate(d) {
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}
function addDays(d, n) { const c = new Date(d); c.setDate(c.getDate() + n); return c; }
function pct(p) { return (p * 100).toFixed(1); }
function escapeHTML(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }

const storage = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} },
};

function riskLevel(kind, p) {
  const t = RISK_THRESHOLDS[kind];
  if (p >= t.high) return { label: "높음", cls: "high", icon: '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/>' };
  if (p >= t.medium) return { label: "보통", cls: "medium", icon: '<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>' };
  return { label: "낮음", cls: "low", icon: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>' };
}

// ───────── 테마 ─────────

$("theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const isDark = root.dataset.theme
    ? root.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  root.dataset.theme = isDark ? "light" : "dark";
  try { localStorage.setItem("theme", root.dataset.theme); } catch {}
});

// ───────── 콤보박스 (목록 드롭다운 + 검색): 항공사, 출발지, 도착지 ─────────

class Combo {
  constructor(root, items, emptyText) {
    this.root = root;
    this.items = items;
    this.byCode = new Map(items.map((a) => [a.code, a]));
    this.emptyText = emptyText;
    this.hidden = root.querySelector('input[type="hidden"]');
    this.input = root.querySelector(".combo-input");
    this.list = root.querySelector(".combo-list");
    this.active = -1;
    this.matches = [];

    this.input.addEventListener("focus", () => { this.input.select(); this.open(""); });
    this.input.addEventListener("click", () => { if (this.list.hidden) this.open(""); });
    this.input.addEventListener("input", () => { this.hidden.value = ""; this.open(this.input.value); });
    this.input.addEventListener("keydown", (e) => this.onKey(e));
    this.input.addEventListener("blur", () => setTimeout(() => this.commit(), 0));
    this.root.querySelector(".chev").addEventListener("mousedown", (e) => {
      e.preventDefault();
      if (this.list.hidden) this.input.focus(); else this.close();
    });
    this.list.addEventListener("mousedown", (e) => {
      e.preventDefault(); // blur 방지
      const li = e.target.closest("li[data-code]");
      if (li) { this.set(li.dataset.code); this.close(); }
    });
  }

  label(code) {
    const a = this.byCode.get(code);
    return a ? `${a.code} ${a.name_ko}` : "";
  }

  get value() { return this.hidden.value; }

  set(code) {
    this.hidden.value = code || "";
    this.input.value = this.label(code);
  }

  filter(q) {
    q = q.trim().toLowerCase();
    if (!q || q === this.label(this.value).toLowerCase()) return this.items;
    const starts = [], contains = [];
    for (const a of this.items) {
      const hay = [a.code, a.name, a.name_ko].map((s) => s.toLowerCase());
      if (hay[0].startsWith(q)) starts.push(a);
      else if (hay.some((h) => h.includes(q))) contains.push(a);
    }
    return [...starts, ...contains];
  }

  open(q) {
    this.matches = this.filter(q);
    this.active = this.matches.findIndex((a) => a.code === this.value);
    if (this.active < 0 && q.trim()) this.active = 0;
    this.render();
    this.list.hidden = false;
    this.root.dataset.open = "";
    this.input.setAttribute("aria-expanded", "true");
    this.scrollActive();
  }

  close() {
    this.list.hidden = true;
    delete this.root.dataset.open;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
  }

  render() {
    if (!this.matches.length) {
      this.list.innerHTML = `<li class="empty">${this.emptyText}</li>`;
      return;
    }
    const id = this.list.id;
    this.list.innerHTML = this.matches.map((a, i) => `
      <li id="${id}-${a.code}" role="option" data-code="${a.code}"
          aria-selected="${i === this.active}" class="${a.code === this.value ? "current" : ""}">
        <span class="code">${a.code}</span>
        <span class="nm">${escapeHTML(a.name_ko)}<small>${escapeHTML(a.name)}</small></span>
      </li>`).join("");
    if (this.active >= 0) this.input.setAttribute("aria-activedescendant", `${id}-${this.matches[this.active].code}`);
  }

  scrollActive() {
    const el = this.list.querySelector('[aria-selected="true"]');
    if (el) el.scrollIntoView({ block: "nearest" });
  }

  onKey(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (this.list.hidden) return this.open(this.input.value);
      const n = this.matches.length;
      if (!n) return;
      this.active = (this.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n;
      this.render(); this.scrollActive();
    } else if (e.key === "Enter") {
      if (!this.list.hidden && this.matches[this.active]) {
        e.preventDefault();
        this.set(this.matches[this.active].code);
        this.close();
      }
    } else if (e.key === "Escape") {
      this.close();
      this.input.value = this.label(this.value);
    }
  }

  // 포커스가 빠질 때: 선택이 없으면 정확히 일치하거나 유일한 후보를 자동 선택
  commit() {
    if (document.activeElement === this.input) return;
    this.close();
    if (this.value) { this.input.value = this.label(this.value); return; }
    const q = this.input.value.trim();
    if (!q) return;
    const exact = this.items.find((a) => a.code.toLowerCase() === q.toLowerCase());
    const matches = this.filter(q);
    const pick = exact || (matches.length === 1 ? matches[0] : null);
    if (pick) this.set(pick.code);
    else this.hidden.value = q.toUpperCase(); // 서버가 "지원하지 않는 공항"으로 응답
  }
}

let airlineCombo, originCombo, destCombo;

// ───────── 폼 ─────────

function showErrors(errors) {
  form.querySelectorAll(".error").forEach((el) => { el.textContent = errors[el.dataset.for] || ""; });
}

function fillForm(q) {
  airlineCombo.set(q.airline);
  originCombo.set(q.origin);
  destCombo.set(q.dest);
  if (q.date) form.elements.date.value = q.date;
  form.elements.dep_time.value = q.dep_time;
}

$("swap").addEventListener("click", () => {
  const o = originCombo.value, d = destCombo.value;
  originCombo.set(d); destCombo.set(o);
});

async function postJSON(url, payload) {
  const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  return { ok: res.ok, data: await res.json().catch(() => ({})) };
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  showErrors({});
  const payload = Object.fromEntries(new FormData(form));
  const button = form.querySelector(".primary");
  button.disabled = true;
  try {
    const [single, hourly] = await Promise.all([
      postJSON("/api/predict", payload),
      postJSON("/api/predict/hourly", payload),
    ]);
    if (!single.ok) { showErrors(single.data.errors || { _: "요청에 실패했습니다." }); return; }
    renderResult(payload, single.data, hourly.ok ? hourly.data : null);
    remember(payload);
  } catch {
    showErrors({ _: "서버에 연결할 수 없습니다." });
  } finally {
    button.disabled = false;
  }
});

// ───────── 최근 조회 ─────────

function chip(q) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "chip";
  const d = q.date ? `<small>${q.date.slice(5).replace("-", "/")} ${q.dep_time}</small>` : "";
  b.innerHTML = `${escapeHTML(q.airline)} ${escapeHTML(q.origin)} → ${escapeHTML(q.dest)}${d}`;
  b.addEventListener("click", () => { fillForm(q); form.requestSubmit(); });
  return b;
}

function renderRecent() {
  const today = localISODate(new Date());
  const items = storage.get(RECENT_KEY, []).filter((q) => q.date >= today);
  $("recent-row").hidden = !items.length;
  $("recent-list").replaceChildren(...items.map((q) => chip(q)));
}

function remember(q) {
  const key = (x) => [x.airline, x.origin, x.dest, x.date, x.dep_time].join("|");
  const items = storage.get(RECENT_KEY, []).filter((x) => key(x) !== key(q));
  storage.set(RECENT_KEY, [q, ...items].slice(0, RECENT_MAX));
  renderRecent();
}

// ───────── 결과 ─────────

function renderMetric(kind, p) {
  $(`${kind}-prob`).textContent = pct(p);
  requestAnimationFrame(() => { $(`${kind}-meter`).style.width = `${Math.max(p * 100, 1)}%`; });
  const r = riskLevel(kind, p);
  const el = $(`${kind}-risk`);
  el.className = `risk ${r.cls}`;
  el.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${r.icon}</svg>위험도 ${r.label}`;
}

function renderResult(q, single, hourly) {
  const al = OPTIONS.airlines.find((a) => a.code === q.airline);
  $("r-origin").textContent = q.origin;
  $("r-origin-name").textContent = byCode[q.origin]?.name_ko ?? "";
  $("r-dest").textContent = q.dest;
  $("r-dest-name").textContent = byCode[q.dest]?.name_ko ?? "";
  $("r-airline").textContent = al ? `${al.name_ko} (${al.code})` : q.airline;
  const [y, m, d] = q.date.split("-").map(Number);
  $("r-date").textContent = new Intl.DateTimeFormat("ko-KR", { dateStyle: "full" }).format(new Date(y, m - 1, d));
  $("r-time").textContent = `출발 예정 ${q.dep_time}`;

  renderMetric("delay", single.delay_probability);
  renderMetric("cancel", single.cancel_probability);

  const selectedHour = Number(q.dep_time.split(":")[0]);
  if (hourly) {
    renderHourlyChart($("chart-delay"), "delay", hourly.hours, selectedHour);
    renderHourlyChart($("chart-cancel"), "cancel", hourly.hours, selectedHour);
    $("hourly-table").innerHTML = hourly.hours.map((h) => `
      <tr class="${h.hour === selectedHour ? "current" : ""}">
        <td>${String(h.hour).padStart(2, "0")}:00</td><td>${pct(h.delay_probability)}%</td><td>${pct(h.cancel_probability)}%</td>
      </tr>`).join("");
  }
  document.querySelector(".hourly").hidden = !hourly;

  const section = $("result");
  const wasHidden = section.hidden;
  section.hidden = false;
  if (wasHidden) section.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ───────── 시간대별 막대 차트 ─────────

function niceMax(v) {
  const steps = [0.01, 0.02, 0.025, 0.05, 0.1, 0.2, 0.25, 0.5, 1];
  for (const s of steps) if (v <= s * 4) return s * 4 > 1 ? 1 : s * 4;
  return 1;
}

function renderHourlyChart(el, kind, hours, selectedHour) {
  const key = `${kind}_probability`;
  const W = 420, H = 180, padL = 34, padR = 6, padT = 22, padB = 22;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const max = niceMax(Math.max(...hours.map((h) => h[key])));
  const band = innerW / hours.length;
  const bw = Math.min(16, band - 4);
  const y = (v) => padT + innerH - (v / max) * innerH;

  const ticks = [0, max / 2, max];
  const fmtTick = (v) => `${+(v * 100).toFixed(1)}%`;
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="시간대별 ${kind === "delay" ? "지연" : "결항"} 확률 막대 차트">`;
  for (const t of ticks) {
    svg += `<line class="gridline" x1="${padL}" x2="${W - padR}" y1="${y(t)}" y2="${y(t)}"/>`;
    svg += `<text class="tick" x="${padL - 6}" y="${y(t) + 4}" text-anchor="end">${fmtTick(t)}</text>`;
  }

  const minIdx = hours.reduce((best, h, i) => (h[key] < hours[best][key] ? i : best), 0);
  const selIdx = hours.findIndex((h) => h.hour === selectedHour);
  const hasSel = selIdx >= 0;

  hours.forEach((h, i) => {
    const cx = padL + band * i + band / 2;
    const v = h[key];
    const top = y(v), base = y(0);
    const hgt = Math.max(base - top, 1);
    const r = Math.min(4, hgt, bw / 2);
    const x0 = cx - bw / 2, x1 = cx + bw / 2;
    const path = `M${x0},${base} V${top + r} Q${x0},${top} ${x0 + r},${top} H${x1 - r} Q${x1},${top} ${x1},${top + r} V${base} Z`;
    const dim = hasSel && i !== selIdx ? " dim" : "";
    svg += `<rect class="hit" x="${padL + band * i}" y="${padT}" width="${band}" height="${innerH}" tabindex="0" role="button"
              data-i="${i}" aria-label="${h.hour}시 출발: ${pct(v)}%. 이 시각으로 다시 예측"/>`;
    svg += `<path class="bar${dim}" d="${path}"/>`;
    if (h.hour % 2 === 0) svg += `<text class="tick" x="${cx}" y="${H - 6}" text-anchor="middle">${h.hour}시</text>`;
  });

  // 선택한 시각과 최저 시각에만 값 라벨 (겹치면 선택 시각만)
  // 양 끝 막대의 라벨은 축 눈금과 겹치지 않도록 막대 쪽으로 정렬
  const label = (i, text, cls) => {
    const cx = padL + band * i + band / 2;
    const [x, anchor] = i <= 1 ? [cx - bw / 2, "start"] : i >= hours.length - 2 ? [cx + bw / 2, "end"] : [cx, "middle"];
    svg += `<text class="lbl ${cls}" x="${x}" y="${y(hours[i][key]) - 6}" text-anchor="${anchor}">${text}</text>`;
  };
  if (hasSel) label(selIdx, `${pct(hours[selIdx][key])}%`, "");
  if (!hasSel || Math.abs(minIdx - selIdx) > 1) label(minIdx, `최저 ${pct(hours[minIdx][key])}%`, "sub");
  svg += "</svg>";
  el.innerHTML = svg;

  el.querySelectorAll(".hit").forEach((hit) => {
    const h = hours[Number(hit.dataset.i)];
    const show = () => showTooltip(hit, h, kind);
    hit.addEventListener("mouseenter", show);
    hit.addEventListener("focus", show);
    hit.addEventListener("mouseleave", hideTooltip);
    hit.addEventListener("blur", hideTooltip);
    const pick = () => {
      hideTooltip();
      form.elements.dep_time.value = `${String(h.hour).padStart(2, "0")}:00`;
      form.requestSubmit();
    };
    hit.addEventListener("click", pick);
    hit.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  });
}

const tooltip = $("tooltip");
function showTooltip(target, h, kind) {
  const color = kind === "delay" ? "var(--series-delay)" : "var(--series-cancel)";
  const name = kind === "delay" ? "지연" : "결항";
  tooltip.innerHTML = `<div>${String(h.hour).padStart(2, "0")}:00 출발</div>
    <div><span class="sw" style="background:${color}"></span>${name} 확률 <b>${pct(h[`${kind}_probability`])}%</b></div>`;
  tooltip.hidden = false;
  // 막대 바로 위에 띄운다 (막대는 hit 영역 다음 형제)
  const bar = target.nextElementSibling.getBoundingClientRect();
  const r = target.getBoundingClientRect();
  const t = tooltip.getBoundingClientRect();
  let left = r.left + r.width / 2 - t.width / 2;
  left = Math.max(8, Math.min(left, innerWidth - t.width - 8));
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${Math.max(8, bar.top - t.height - 26)}px`;
}
function hideTooltip() { tooltip.hidden = true; }

// ───────── 초기화 ─────────

async function init() {
  OPTIONS = await (await fetch("/api/options")).json();
  OPTIONS.airports.forEach((a) => { byCode[a.code] = a; });

  const combo = (name, items, emptyText) => new Combo(form.querySelector(`[data-name="${name}"]`), items, emptyText);
  airlineCombo = combo("airline", OPTIONS.airlines, "일치하는 항공사가 없어요");
  originCombo = combo("origin", OPTIONS.airports, "일치하는 공항이 없어요");
  destCombo = combo("dest", OPTIONS.airports, "일치하는 공항이 없어요");

  const today = new Date();
  form.elements.date.min = localISODate(today);
  form.elements.date.max = localISODate(addDays(today, BOOKING_WINDOW_DAYS));
  form.elements.date.value = localISODate(addDays(today, 14));
  form.elements.dep_time.value = "09:00";

  renderRecent();
}

init();
