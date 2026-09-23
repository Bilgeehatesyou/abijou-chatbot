// Ajilt-AI's own meetings: everything booked with us, from the chatbot's sales
// flow and from the ajiltai.tech form, in one list. Sources stay labelled, and
// each meeting can be moved through new -> confirmed -> done / cancelled.
(() => {
  const TZ = "Asia/Ulaanbaatar";
  const REFRESH_MS = 30000;
  const STATUSES = [
    ["new", "Шинэ"], ["confirmed", "Баталгаажсан"], ["done", "Болсон"], ["cancelled", "Цуцлагдсан"],
  ];
  const STATUS_LABEL = Object.fromEntries(STATUSES);
  const SOURCES = { chatbot: "💬 Чатбот", website: "🌐 Вэбсайт" };
  const CHANNEL = { messenger: "Messenger", instagram: "Instagram", cli: "Туршилт" };
  const WEEKDAY = { Sun: "Ням", Mon: "Даваа", Tue: "Мягмар", Wed: "Лхагва", Thu: "Пүрэв", Fri: "Баасан", Sat: "Бямба" };

  const app = document.getElementById("app");
  const toast = document.getElementById("toast");
  const state = { data: null, when: "upcoming", source: "all", status: "all", query: "", seen: null, fresh: new Set(), updatedAt: null, error: "" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const partFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ, weekday: "short", year: "numeric", month: "numeric", day: "numeric",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const dayKey = new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" });

  function parts(d) {
    const o = {};
    for (const p of partFmt.formatToParts(d)) o[p.type] = p.value;
    return o;
  }
  const dayLabel = (d) => { const p = parts(d); return `${p.month}-р сарын ${p.day}, ${WEEKDAY[p.weekday] || ""}`; };
  const timeLabel = (d) => { const p = parts(d); return `${p.hour}:${p.minute}`; };
  const dayDiff = (a, b) => Math.round((Date.parse(`${dayKey.format(a)}T00:00:00Z`) - Date.parse(`${dayKey.format(b)}T00:00:00Z`)) / 86400000);

  function relative(start, now) {
    const d = dayDiff(start, now);
    if (d === 0) return `Өнөөдөр ${timeLabel(start)}`;
    if (d === 1) return `Маргааш ${timeLabel(start)}`;
    if (d === -1) return `Өчигдөр ${timeLabel(start)}`;
    return d > 0 ? `${d} өдрийн дараа` : `${-d} өдрийн өмнө`;
  }

  function showToast(text) {
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(showToast.t);
    showToast.t = setTimeout(() => { toast.hidden = true; }, 2600);
  }

  const key = (m) => `${m.source}-${m.id}`;

  async function load() {
    try {
      const r = await fetch("/api/meetings", { cache: "no-store" });
      if (!r.ok) throw new Error(`Алдаа (${r.status})`);
      const data = await r.json();
      const ids = new Set(data.meetings.map(key));
      const fresh = state.seen ? data.meetings.filter((m) => !state.seen.has(key(m))).map(key) : [];
      state.seen = ids;
      state.data = data;
      state.fresh = new Set(fresh);
      state.updatedAt = new Date();
      state.error = "";
      if (fresh.length) showToast(`${fresh.length} шинэ уулзалт бүртгэгдлээ`);
    } catch (e) {
      state.error = e.message || "Ачааллах үед алдаа гарлаа.";
    }
    render();
  }

  async function setStatus(m, status) {
    const r = await fetch(`/api/meetings/${m.source}/${m.id}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
    });
    if (!r.ok) { showToast("Төлөв хадгалагдсангүй. Дахин оролдоно уу."); await load(); return; }
    m.status = status;
    showToast(`${m.name || "Уулзалт"} → ${STATUS_LABEL[status]}`);
    render();
  }

  const isUpcoming = (m, now) => Date.parse(m.end_at || m.start_at) >= now.getTime();

  function visible(now) {
    const q = state.query.trim().toLowerCase();
    const list = state.data.meetings.filter((m) => {
      if (state.when === "upcoming" && !isUpcoming(m, now)) return false;
      if (state.when === "past" && isUpcoming(m, now)) return false;
      if (state.source !== "all" && m.source !== state.source) return false;
      if (state.status !== "all" && m.status !== state.status) return false;
      if (!q) return true;
      return [m.name, m.phone, m.email, m.business, m.plan, m.facebook, m.instagram]
        .join(" ").toLowerCase().includes(q);
    });
    // Nearest meeting first when looking ahead, most recent first when looking back.
    list.sort((a, b) => (state.when === "past" ? -1 : 1) * (Date.parse(a.start_at) - Date.parse(b.start_at)));
    return list;
  }

  function tiles(all, now) {
    const today = dayKey.format(now);
    const week = now.getTime() + 7 * 86400000;
    const count = (f) => all.filter(f).length;
    return [
      ["is-new", "Хариу хүлээж буй", count((m) => m.status === "new" && isUpcoming(m, now))],
      ["", "Өнөөдөр", count((m) => dayKey.format(new Date(m.start_at)) === today && m.status !== "cancelled")],
      ["", "Ирэх 7 хоногт", count((m) => isUpcoming(m, now) && Date.parse(m.start_at) <= week && m.status !== "cancelled")],
      ["", "Нийт уулзалт", all.length],
    ].map(([cls, label, value]) =>
      `<div class="o-tile ${cls}"><div class="label">${label}</div><div class="value">${value}</div></div>`).join("");
  }

  function facts(m) {
    const rows = [];
    if (m.source === "website") {
      const fmt = [m.format_label, m.platform_label].filter(Boolean).join(" · ");
      if (fmt) rows.push(["Хэлбэр", `${fmt}${m.duration ? ` · ${m.duration} мин` : ""}`]);
    } else {
      rows.push(["Хэлбэр", `Чатботоор товлосон${m.channel ? ` · ${CHANNEL[m.channel] || m.channel}` : ""}`]);
    }
    if (m.plan) rows.push(["Сонирхсон багц", m.plan]);
    if (m.business) rows.push(["Бизнес", m.business]);
    const size = [m.employees && `${m.employees} ажилтан`, m.branches && `${m.branches} салбар`].filter(Boolean).join(" · ");
    if (size) rows.push(["Хэмжээ", size]);
    if (m.facebook) rows.push(["Facebook", m.facebook]);
    if (m.instagram) rows.push(["Instagram", m.instagram]);
    return rows.map(([k, v]) => `<li><span class="k">${esc(k)}</span>${esc(v)}</li>`).join("");
  }

  function card(m, now) {
    const start = new Date(m.start_at);
    const phone = String(m.phone || "").replace(/[^\d+]/g, "");
    const options = STATUSES.map(([v, l]) =>
      `<option value="${v}"${v === m.status ? " selected" : ""}>${l}</option>`).join("");
    const warnings = [
      m.clash ? '<div class="m-warn m-clash">⚠ Өөр уулзалттай цаг давхцаж байна</div>' : "",
      m.calendar_status && m.calendar_status !== "booked"
        ? '<div class="m-warn">⚠ Google Calendar-т ороогүй</div>' : "",
    ].join("");
    return `
      <article class="o-card m-card${state.fresh.has(key(m)) ? " is-fresh" : ""}${isUpcoming(m, now) ? "" : " is-past"}" data-status="${esc(m.status)}">
        <div>
          <span class="m-source ${esc(m.source)}">${SOURCES[m.source] || m.source}</span>
          <div class="m-when">${esc(timeLabel(start))}<span class="rel">${esc(relative(start, now))}</span></div>
          ${warnings}
        </div>
        <div>
          <div class="o-name">${esc(m.name) || "—"}
            ${m.status === "new" ? '<span class="o-badge-new">ШИНЭ</span>' : ""}</div>
          <div class="m-contact">
            ${phone ? `<a href="tel:${esc(phone)}">📞 ${esc(m.phone)}</a>` : ""}
            ${m.email ? `<a href="mailto:${esc(m.email)}">✉ ${esc(m.email)}</a>` : ""}
          </div>
          <ul class="m-facts" style="margin-top:8px">${facts(m)}</ul>
        </div>
        <div class="o-side">
          <label class="visually-hidden" for="st-${esc(key(m))}">Төлөв</label>
          <select class="o-status" id="st-${esc(key(m))}" data-key="${esc(key(m))}"
                  aria-label="${esc(m.name || "уулзалт")} — төлөв">${options}</select>
        </div>
      </article>`;
  }

  function groups(list, now) {
    let out = "", day = "";
    for (const m of list) {
      const d = dayKey.format(new Date(m.start_at));
      if (d !== day) {
        day = d;
        const label = dayLabel(new Date(m.start_at));
        const diff = dayDiff(new Date(m.start_at), now);
        const note = diff === 0 ? " · Өнөөдөр" : diff === 1 ? " · Маргааш" : "";
        out += `<h2 class="m-day">${esc(label)}<span class="n">${esc(note)}</span></h2>`;
      }
      out += card(m, now);
    }
    return out;
  }

  function chips(name, options, current) {
    return options.map(([v, l, n]) =>
      `<button class="o-chip" data-chip="${name}" data-value="${v}" aria-pressed="${current === v}">${l}${
        n === undefined ? "" : `<span class="n">${n}</span>`}</button>`).join("");
  }

  function render() {
    if (!state.data) {
      app.innerHTML = state.error
        ? `<div class="o-empty">${esc(state.error)}<br><br><button class="o-btn" id="retry">Дахин оролдох</button></div>`
        : '<p class="loading">Ачааллаж байна…</p>';
      document.getElementById("retry")?.addEventListener("click", load);
      return;
    }
    const all = state.data.meetings;
    const now = new Date(state.data.now);
    const shown = visible(now);
    const bySource = (s) => all.filter((m) => m.source === s).length;
    const byStatus = (s) => all.filter((m) => m.status === s).length;
    const updated = state.updatedAt ? state.updatedAt.toLocaleTimeString("mn-MN", { timeZone: TZ, hour12: false }) : "";
    const isDark = document.documentElement.dataset.theme === "dark" ||
      (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);

    app.innerHTML = `
      <header class="o-head">
        <div>
          <h1 class="o-title">📅 Ажилт-AI — уулзалтууд</h1>
          <p class="o-sub">Чатбот болон ajiltai.tech-ээр товлогдсон уулзалт. 30 секунд тутам шинэчлэгдэнэ.
            ${state.data.calendar ? "" : '<br>⚠ Google Calendar холбогдоогүй байна.'}</p>
        </div>
        <div class="o-actions">
          <span class="o-updated">${state.error ? `⚠ ${esc(state.error)}` : `Шинэчилсэн ${esc(updated)}`}</span>
          <button class="o-btn" id="refresh">↻ Шинэчлэх</button>
          <button class="o-btn" id="csv">⬇ CSV</button>
          <button class="o-btn" id="theme" aria-label="Өнгөний горим солих">${isDark ? "☀" : "☾"}</button>
        </div>
      </header>
      <section class="o-tiles" aria-label="Тойм">${tiles(all, now)}</section>
      <div class="o-filters">
        ${chips("when", [["upcoming", "Ирэх"], ["past", "Өнгөрсөн"], ["all", "Бүгд"]], state.when)}
        ${chips("source", [["all", "Бүх суваг"], ["chatbot", SOURCES.chatbot, bySource("chatbot")],
    ["website", SOURCES.website, bySource("website")]], state.source)}
      </div>
      <div class="o-filters">
        ${chips("status", [["all", "Бүх төлөв"], ...STATUSES.map(([v, l]) => [v, l, byStatus(v)])], state.status)}
        <input class="o-search" id="search" type="search" placeholder="Хайх: нэр, утас, и-мэйл, бизнес…"
               value="${esc(state.query)}" aria-label="Уулзалт хайх">
      </div>
      <section class="o-list" aria-live="polite">
        ${shown.length ? groups(shown, now) : `<div class="o-empty">${all.length
        ? "Энэ шүүлтүүрт тохирох уулзалт алга."
        : "Одоогоор уулзалт алга.<br>Чатбот болон вэбсайтаар товлогдсон уулзалт энд шууд харагдана."}</div>`}
      </section>
      <p class="o-note">Уулзалтууд Google Calendar-т бас ордог: чатботынх хөх, вэбсайтынх улбар шар өнгөтэй.</p>`;

    app.querySelectorAll(".o-chip").forEach((b) => b.addEventListener("click", () => {
      state[b.dataset.chip] = b.dataset.value;
      render();
    }));
    const search = document.getElementById("search");
    search.addEventListener("input", () => {
      state.query = search.value;
      const pos = search.selectionStart;
      render();
      const again = document.getElementById("search");
      again.focus(); again.setSelectionRange(pos, pos);
    });
    app.querySelectorAll(".o-status").forEach((s) => s.addEventListener("change", () => {
      const m = all.find((x) => key(x) === s.dataset.key);
      if (m) setStatus(m, s.value);
    }));
    document.getElementById("refresh").addEventListener("click", load);
    document.getElementById("csv").addEventListener("click", () => downloadCsv(now));
    document.getElementById("theme").addEventListener("click", () => {
      const next = isDark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("ajilt-theme", next); } catch (e) { /* storage blocked */ }
      render();
    });
  }

  function downloadCsv(now) {
    const rows = [["Огноо", "Цаг", "Суваг", "Нэр", "Утас", "И-мэйл", "Хэлбэр", "Багц", "Бизнес",
      "Ажилтан", "Салбар", "Facebook", "Instagram", "Төлөв"]];
    for (const m of visible(now)) {
      const start = new Date(m.start_at);
      rows.push([dayLabel(start), timeLabel(start), m.source === "website" ? "Вэбсайт" : "Чатбот",
        m.name, m.phone, m.email, [m.format_label, m.platform_label].filter(Boolean).join(" "),
        m.plan, m.business, m.employees, m.branches, m.facebook, m.instagram,
        STATUS_LABEL[m.status] || m.status]);
    }
    const csv = "﻿" + rows.map((r) => r.map((v) => `"${String(v ?? "").replace(/"/g, '""')}"`).join(",")).join("\r\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    a.download = `ajiltai-meetings-${dayKey.format(new Date())}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  load();
  setInterval(() => { if (!document.hidden) load(); }, REFRESH_MS);
})();
