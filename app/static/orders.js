// Orders page: lists order/stay requests the chatbot collected for one business,
// lets staff move each order through new -> confirmed -> delivered / cancelled.
(() => {
  const BIZ = location.pathname.split("/").filter(Boolean)[1] || "wholesale";
  const TZ = "Asia/Ulaanbaatar";
  const REFRESH_MS = 30000;
  const STATUSES = [
    ["new", "Шинэ"], ["confirmed", "Баталгаажсан"], ["delivered", "Хүргэгдсэн"], ["cancelled", "Цуцлагдсан"],
  ];
  const STATUS_LABEL = Object.fromEntries(STATUSES);
  const CHANNEL = { messenger: "Messenger", instagram: "Instagram", cli: "Туршилт" };

  const app = document.getElementById("app");
  const toast = document.getElementById("toast");
  const state = { data: null, filter: "all", query: "", seen: null, updatedAt: null, error: "" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = new Intl.DateTimeFormat("mn-MN", {
    timeZone: TZ, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

  function ago(seconds) {
    if (seconds < 60) return "дөнгөж сая";
    const m = Math.floor(seconds / 60);
    if (m < 60) return `${m} мин өмнө`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h} цагийн өмнө`;
    return `${Math.floor(h / 24)} өдрийн өмнө`;
  }

  function showToast(text) {
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(showToast.t);
    showToast.t = setTimeout(() => { toast.hidden = true; }, 2600);
  }

  async function load() {
    try {
      const r = await fetch(`/api/orders/${encodeURIComponent(BIZ)}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status === 404 ? "Ийм бизнес олдсонгүй." : `Алдаа (${r.status})`);
      const data = await r.json();
      const ids = new Set(data.orders.map((o) => o.id));
      const fresh = state.seen ? data.orders.filter((o) => !state.seen.has(o.id)).map((o) => o.id) : [];
      state.seen = ids;
      state.data = data;
      state.fresh = new Set(fresh);
      state.updatedAt = new Date();
      state.error = "";
      if (fresh.length) showToast(`${fresh.length} шинэ захиалга ирлээ`);
    } catch (e) {
      state.error = e.message || "Ачааллах үед алдаа гарлаа.";
    }
    render();
  }

  async function setStatus(id, status) {
    const r = await fetch(`/api/orders/${encodeURIComponent(BIZ)}/${id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
    });
    if (!r.ok) { showToast("Төлөв хадгалагдсангүй. Дахин оролдоно уу."); await load(); return; }
    const order = state.data.orders.find((o) => o.id === id);
    if (order) order.status = status;
    showToast(`#${id} → ${STATUS_LABEL[status]}`);
    render();
  }

  function visibleOrders() {
    const q = state.query.trim().toLowerCase();
    return state.data.orders.filter((o) => {
      if (state.filter !== "all" && o.status !== state.filter) return false;
      if (!q) return true;
      return [o.name, o.phone, ...(o.details || [])].join(" ").toLowerCase().includes(q);
    });
  }

  function tiles(orders, now) {
    const today = dayKey.format(new Date(now * 1000));
    const week = now - 7 * 86400;
    const count = (f) => orders.filter(f).length;
    return [
      ["is-new", "Шинэ (хариу хүлээж буй)", count((o) => o.status === "new")],
      ["", "Өнөөдөр", count((o) => dayKey.format(new Date(o.created_at * 1000)) === today)],
      ["", "Сүүлийн 7 хоногт", count((o) => o.created_at >= week)],
      ["", "Нийт", orders.length],
    ].map(([cls, label, value]) =>
      `<div class="o-tile ${cls}"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
  }

  function card(o, now) {
    const [items, ...rest] = o.details || [];
    const phone = String(o.phone || "");
    const options = STATUSES.map(([v, l]) =>
      `<option value="${v}"${v === o.status ? " selected" : ""}>${l}</option>`).join("");
    return `
      <article class="o-card${state.fresh.has(o.id) ? " is-fresh" : ""}" data-status="${esc(o.status)}">
        <div>
          <div class="o-meta">#${o.id} · ${esc(fmt.format(new Date(o.created_at * 1000)))}
            ${o.status === "new" ? '<span class="o-badge-new">ШИНЭ</span>' : ""}</div>
          <div class="o-name">${esc(o.name) || "—"}</div>
          ${phone ? `<a class="o-phone" href="tel:${esc(phone.replace(/[^\d+]/g, ""))}">📞 ${esc(phone)}</a>` : ""}
          <div><span class="o-channel">${esc(CHANNEL[o.channel] || o.channel || "Чат")}</span></div>
        </div>
        <ul class="o-items">
          <li><span class="k">Захиалга</span>${esc(items) || "—"}</li>
          ${rest.map((r) => `<li><span class="k">Хүргэлт / тэмдэглэл</span>${esc(r)}</li>`).join("")}
        </ul>
        <div class="o-side">
          <label class="visually-hidden" for="st-${o.id}">Төлөв</label>
          <select class="o-status" id="st-${o.id}" data-id="${o.id}" aria-label="#${o.id} захиалгын төлөв">${options}</select>
          <div class="o-age">${ago(Math.max(0, now - o.created_at))}</div>
        </div>
      </article>`;
  }

  function render() {
    if (!state.data) {
      app.innerHTML = state.error
        ? `<div class="o-empty">${esc(state.error)}<br><br><button class="o-btn" id="retry">Дахин оролдох</button></div>`
        : '<p class="loading">Ачааллаж байна…</p>';
      document.getElementById("retry")?.addEventListener("click", load);
      return;
    }
    const { business, orders, now } = state.data;
    const shown = visibleOrders();
    const counts = Object.fromEntries(STATUSES.map(([v]) => [v, orders.filter((o) => o.status === v).length]));
    const chips = [["all", "Бүгд", orders.length], ...STATUSES.map(([v, l]) => [v, l, counts[v]])]
      .map(([v, l, n]) => `<button class="o-chip" data-filter="${v}" aria-pressed="${state.filter === v}">${l}<span class="n">${n}</span></button>`)
      .join("");
    const updated = state.updatedAt ? state.updatedAt.toLocaleTimeString("mn-MN", { timeZone: TZ, hour12: false }) : "";
    const isDark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);

    app.innerHTML = `
      <header class="o-head">
        <div>
          <h1 class="o-title">${esc(business.emoji)} ${esc(business.name.mn)} — захиалгууд</h1>
          <p class="o-sub">Чатботоор (Messenger, Instagram) ирсэн захиалга. 30 секунд тутам шинэчлэгдэнэ.</p>
        </div>
        <div class="o-actions">
          <span class="o-updated">${state.error ? `⚠ ${esc(state.error)}` : `Шинэчилсэн ${esc(updated)}`}</span>
          <button class="o-btn" id="refresh">↻ Шинэчлэх</button>
          <button class="o-btn" id="csv">⬇ CSV</button>
          <button class="o-btn" id="theme" aria-label="Өнгөний горим солих">${isDark ? "☀" : "☾"}</button>
        </div>
      </header>
      <section class="o-tiles" aria-label="Тойм">${tiles(orders, now)}</section>
      <div class="o-filters">
        ${chips}
        <input class="o-search" id="search" type="search" placeholder="Хайх: нэр, утас, бараа…" value="${esc(state.query)}" aria-label="Захиалга хайх">
      </div>
      <section class="o-list" aria-live="polite">
        ${shown.length ? shown.map((o) => card(o, now)).join("") : `<div class="o-empty">${orders.length
          ? "Энэ шүүлтүүрт тохирох захиалга алга."
          : "Одоогоор захиалга алга.<br>Чатботоор ирсэн захиалга энд шууд харагдана."}</div>`}
      </section>
      <p class="o-note">Чатбот үнийг ойролцоогоор хэлдэг тул эцсийн үнэ, үлдэгдлийг захиалагчид залгаж баталгаажуулна уу.</p>`;

    app.querySelectorAll(".o-chip").forEach((b) => b.addEventListener("click", () => {
      state.filter = b.dataset.filter; render();
    }));
    const search = document.getElementById("search");
    search.addEventListener("input", () => {
      state.query = search.value;
      const pos = search.selectionStart;
      render();
      const again = document.getElementById("search");
      again.focus(); again.setSelectionRange(pos, pos);
    });
    app.querySelectorAll(".o-status").forEach((s) => s.addEventListener("change", () => setStatus(Number(s.dataset.id), s.value)));
    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("csv").addEventListener("click", downloadCsv);
    document.getElementById("theme").addEventListener("click", () => {
      const next = isDark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("ajilt-theme", next); } catch (e) { /* storage blocked */ }
      render();
    });
  }

  function downloadCsv() {
    const rows = [["#", "Огноо", "Нэр", "Утас", "Захиалга", "Хүргэлт / тэмдэглэл", "Төлөв", "Суваг"]];
    for (const o of visibleOrders()) {
      const [items, ...rest] = o.details || [];
      rows.push([o.id, fmt.format(new Date(o.created_at * 1000)), o.name, o.phone, items || "",
        rest.join(" | "), STATUS_LABEL[o.status] || o.status, CHANNEL[o.channel] || o.channel]);
    }
    const csv = "﻿" + rows.map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `orders-${BIZ}-${dayKey.format(new Date())}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  load();
  setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
})();
