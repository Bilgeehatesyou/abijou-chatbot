/* Ajilt-AI owner dashboard. Data comes from /api/dashboard/{id}, which is a
   mirror of the business's Google Calendar (synced every minute). */
(() => {
  "use strict";

  // ---------- text ----------
  const TEXT = {
    mn: {
      overview: "Тойм", bookings: "Захиалгууд", schedule: "Хуваарь",
      pickTitle: "Ajilt-AI хяналтын самбар", pickSub: "Бизнесээ сонгоно уу. Чатботоор ирсэн захиалга Google Calendar-аас шууд харагдана.",
      noCalendar: "Календарь холбогдоогүй", linked: "Google Calendar холбогдсон",
      today: "Өнөөдөр", todayBookings: "Өнөөдрийн захиалга", upcomingN: "Ирэх захиалга",
      newIn24: "Сүүлийн 24 цагт +{n} шинэ", justBooked: "Саяхан", remaining: "{n} нь хүлээгдэж байна",
      bookingsN: "Захиалга", newCustomers: "Шинэ {customers}", returning: "Давтан захиалга",
      revenue: "Орлого (тооцоолсон)", cancelRate: "Цуцлалт", cancelledN: "{n} цуцалсан",
      vsPrev: "өмнөх {d} хоногоос", lastDays: "Сүүлийн {d} хоног",
      weekly: "Долоо хоног бүрийн захиалга", weeklyHint: "Сүүлийн 12 долоо хоног, цуцалснаас бусад",
      firstTime: "Анх удаа", regular: "Байнгын", lapsed: "Удаан ирээгүй",
      channels: "Захиалгын суваг", channelsHint: "Захиалга хаанаас ирсэн бэ",
      chatbot: "Чатбот (Ajilt-AI)", phone: "Утсаар", "walk-in": "Биечлэн", manual: "Календарт гараар",
      byStaff: "{staff} тус бүрийн захиалга", topServices: "Эрэлттэй үйлчилгээ",
      upcoming: "Удахгүй", past: "Өнгөрсөн", cancelled: "Цуцалсан", all: "Бүгд",
      nextUp: "Дараагийн захиалгууд", viewAll: "Бүгдийг харах",
      date: "Огноо", time: "Цаг", customer: "Нэр", service: "Үйлчилгээ", staffCol: "Ажилтан",
      channel: "Суваг", status: "Төлөв", visit: "{n} дахь удаа", done: "Ирсэн", booked: "Товлосон",
      search: "Нэр, утсаар хайх…", allStaff: "Бүх ажилтан", allServices: "Бүх үйлчилгээ",
      allTypes: "Бүх төрөл", noRows: "Захиалга алга", shown: "{a}–{b} / {n}",
      prev: "Өмнөх", next: "Дараах", unassigned: "Хуваарилаагүй",
      sync: "Шинэчлэх", synced: "{t}-д шинэчилсэн", syncing: "Шинэчилж байна…", syncErr: "Синк алдаа",
      load: "Энэ 7 хоногийн ачаалал", nextAppt: "Дараагийн: {t} — {n}", noNext: "Ойрын захиалга алга",
      inRange: "{d} хоногт", regShare: "байнгын", rev: "орлого", viewBookings: "Захиалгыг харах",
      visits: "Ирсэн", lastVisit: "Сүүлд", nextVisit: "Дараагийн", usually: "Ихэвчлэн", spent: "Нийт",
      closed: "Энэ өдөр амарна", lapsedHint: "{d}+ хоног ирээгүй байнгын {customers}. Утсаар урих боломжтой.",
      customerType: "Төрөл", mnt: "₮", back: "Бүх бизнес", theme: "Өнгө", branch: "Салбар", allBranches: "Бүх салбар",
      funnel: "Танилцах → Зөвлөгөө", funnelHint: "Танилцахаар ирээд дараа нь зөвлөгөө авсан гэр бүл",
    },
    en: {
      overview: "Overview", bookings: "Bookings", schedule: "Schedule",
      pickTitle: "Ajilt-AI dashboard", pickSub: "Pick a business. Chatbot bookings show up straight from Google Calendar.",
      noCalendar: "No calendar linked", linked: "Google Calendar linked",
      today: "Today", todayBookings: "Today's bookings", upcomingN: "Upcoming bookings",
      newIn24: "+{n} booked in the last 24h", justBooked: "Just booked", remaining: "{n} still to come",
      bookingsN: "Bookings", newCustomers: "New {customers}", returning: "Repeat bookings",
      revenue: "Revenue (estimated)", cancelRate: "Cancellations", cancelledN: "{n} cancelled",
      vsPrev: "vs previous {d} days", lastDays: "Last {d} days",
      weekly: "Bookings per week", weeklyHint: "Last 12 weeks, excluding cancellations",
      firstTime: "First-time", regular: "Regular", lapsed: "Lapsed",
      channels: "Booking channels", channelsHint: "Where bookings came from",
      chatbot: "Chatbot (Ajilt-AI)", phone: "Phone", "walk-in": "Walk-in", manual: "Added in calendar",
      byStaff: "Bookings per {staff1}", topServices: "Top services",
      upcoming: "Upcoming", past: "Past", cancelled: "Cancelled", all: "All",
      nextUp: "Next up", viewAll: "View all",
      date: "Date", time: "Time", customer: "Name", service: "Service", staffCol: "Staff",
      channel: "Channel", status: "Status", visit: "visit #{n}", done: "Completed", booked: "Booked",
      search: "Search name or phone…", allStaff: "All staff", allServices: "All services",
      allTypes: "All types", noRows: "No bookings", shown: "{a}–{b} of {n}",
      prev: "Prev", next: "Next", unassigned: "Unassigned",
      sync: "Sync now", synced: "Synced {t}", syncing: "Syncing…", syncErr: "Sync error",
      load: "Load this week", nextAppt: "Next: {t} — {n}", noNext: "Nothing booked soon",
      inRange: "in {d} days", regShare: "regular", rev: "revenue", viewBookings: "View bookings",
      visits: "Visits", lastVisit: "Last visit", nextVisit: "Next", usually: "Usually with", spent: "Spent",
      closed: "Closed this day", lapsedHint: "Regular {customers} who haven't been back in {d}+ days. Worth a call.",
      customerType: "Type", mnt: "₮", back: "All businesses", theme: "Theme", branch: "Branch", allBranches: "All branches",
      funnel: "Tour → consultation", funnelHint: "Families who came for a tour and then booked a consultation",
    },
  };

  // Words that change per industry.
  const TERMS = {
    salon: {
      mn: { staff: "Мастерууд", Staff1: "Мастер", staff1: "мастер", customers: "үйлчлүүлэгч", Customers: "Үйлчлүүлэгчид" },
      en: { staff: "Stylists", Staff1: "Stylist", staff1: "stylist", customers: "clients", Customers: "Clients" },
      lapsedDays: 35, revenue: true,
    },
    dental: {
      mn: { staff: "Эмч нар", Staff1: "Эмч", staff1: "эмч", customers: "үйлчлүүлэгч", Customers: "Үйлчлүүлэгчид" },
      en: { staff: "Doctors", Staff1: "Doctor", staff1: "doctor", customers: "patients", Customers: "Patients" },
      lapsedDays: 60, revenue: true,
    },
    education: {
      mn: { staff: "Зөвлөхүүд", Staff1: "Зөвлөх", staff1: "зөвлөх", customers: "гэр бүл", Customers: "Гэр бүлүүд" },
      en: { staff: "Advisors", Staff1: "Advisor", staff1: "advisor", customers: "families", Customers: "Families" },
      lapsedDays: 30, revenue: false, funnel: true,
    },
  };

  const STAFF_VARS = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
  const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  const DAY_NAMES = {
    mn: ["Ням", "Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба"],
    en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
  };
  const MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const PAGE_SIZE = 25;

  const ICONS = {
    overview: '<path d="M4 13h6V4H4zM14 20h6V11h-6zM4 20h6v-4H4zM14 4v4h6V4z"/>',
    bookings: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
    schedule: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    staff: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M16 11.5a3 3 0 100-6M21.5 20a5.5 5.5 0 00-4-5.3"/>',
    customers: '<path d="M20 21v-1.5a4.5 4.5 0 00-4.5-4.5h-7A4.5 4.5 0 004 19.5V21"/><circle cx="12" cy="7.5" r="4"/>',
    today: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M8 15h3"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8M15 7h6v6"/>',
    userPlus: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0114 0M19 8v6M16 11h6"/>',
    repeat: '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 013-3h15M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 01-3 3H3"/>',
    money: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/>',
    x: '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>',
    sync: '<path d="M21 12a9 9 0 01-15.5 6.2L3 16M3 12a9 9 0 0115.5-6.2L21 8M21 3v5h-5M3 21v-5h5"/>',
    moon: '<path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z"/>',
  };
  const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;

  // ---------- state ----------
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };
  const state = {
    lang: store.get("ajilt-lang", "mn"),
    view: "overview",
    range: Number(store.get("ajilt-range", "30")),
    data: null,
    charts: [],
    bookings: { tab: "upcoming", q: "", staff: "", service: "", type: "", branch: "", page: 0 },
    customers: { tab: "all", q: "", page: 0 },
    day: null,
    syncing: false,
  };

  const $app = document.getElementById("app");
  const $tip = document.getElementById("tooltip");

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const L = () => TEXT[state.lang];
  const term = () => TERMS[state.data?.business.industry] || TERMS.salon;
  function t(key, vars = {}) {
    const all = { ...term()[state.lang], ...vars };
    return (L()[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => all[k] ?? `{${k}}`);
  }
  const nm = (obj) => (obj ? obj[state.lang] || obj.en || obj.mn : "");
  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parse = (s) => { const [d, tm = "00:00"] = s.split("T"); const [y, m, dd] = d.split("-").map(Number); const [h, mi] = tm.split(":").map(Number); return new Date(y, m - 1, dd, h, mi); };
  const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const hhmm = (d) => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  function dateLabel(d, withDay = true) {
    const wd = DAY_NAMES[state.lang][d.getDay()];
    if (state.lang === "mn") return `${d.getMonth() + 1}/${d.getDate()}${withDay ? " " + wd : ""}`;
    return `${withDay ? wd + ", " : ""}${MONTHS_EN[d.getMonth()]} ${d.getDate()}`;
  }
  const fmtNum = (n) => Math.round(n).toLocaleString("en-US");
  function fmtMoney(n) {
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + (state.lang === "mn" ? " сая₮" : "M ₮");
    return fmtNum(n) + "₮";
  }
  const initials = (s) => (s || "?").replace(/^(Др\.|Dr\.)\s*/, "").trim().charAt(0).toUpperCase();
  function staffColor(staffId) {
    const p = state.data.staffById[staffId];
    return p ? cssVar(STAFF_VARS[p.color]) : cssVar("--muted");
  }

  // ---------- data prep ----------
  function prepare(data) {
    data.nowDate = parse(data.now);
    data.staffById = Object.fromEntries(data.staff.map((p) => [p.id, p]));
    data.serviceById = Object.fromEntries(data.services.map((s) => [s.id, s]));
    for (const e of data.events) {
      e.start = parse(e.start_at);
      e.end = parse(e.end_at);
      e.price = data.serviceById[e.service_id]?.price || 0;
      e.isCancelled = e.status === "cancelled";
      e.isFuture = e.start >= data.nowDate;
      // booked (not just scheduled) in the last 24 hours
      e.isFresh = !!e.created_at && Date.now() - new Date(e.created_at).getTime() < 864e5;
    }
    // per-customer aggregate
    const customers = {};
    for (const e of data.events) {
      const c = customers[e.customer] ||= { key: e.customer, name: e.name, phone: e.phone, visits: 0, spent: 0, last: null, next: null, first: null, staffCount: {}, cancelled: 0 };
      if (e.name) c.name = e.name;
      if (e.isCancelled) { c.cancelled++; continue; }
      if (e.isFuture) { if (!c.next || e.start < c.next) c.next = e.start; continue; }
      c.visits++;
      c.spent += e.price;
      if (!c.first) c.first = e.start;
      c.last = e.start;
      if (e.staff_id) c.staffCount[e.staff_id] = (c.staffCount[e.staff_id] || 0) + 1;
    }
    for (const c of Object.values(customers)) {
      c.favorite = Object.entries(c.staffCount).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
      c.type = c.visits >= 2 ? "regular" : "new";
      const lapsedDays = (TERMS[data.business.industry] || TERMS.salon).lapsedDays;
      c.lapsed = c.visits >= 2 && !c.next && c.last && (data.nowDate - c.last) / 864e5 > lapsedDays;
    }
    data.customers = Object.values(customers);
    return data;
  }

  const inRange = (e, from, to) => e.start >= from && e.start < to;
  function rangeBounds(offset = 0) {
    const to = addDays(state.data.nowDate, -state.range * offset);
    return [addDays(to, -state.range), to];
  }

  // ---------- fetching ----------
  async function api(path, opts) {
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error((await r.text()) || r.statusText);
    return r.json();
  }
  const signature = (d) => d.events.length + "|" + d.events.reduce((m, e) => (e.updated_at > m ? e.updated_at : m), "") + "|" + d.now.slice(0, 13);
  async function load(id, keepView = true) {
    const data = prepare(await api(`/api/dashboard/${encodeURIComponent(id)}`));
    if (keepView && state.data && signature(data) === signature(state.data)) {
      state.data.sync = data.sync;  // nothing new: just refresh the "synced at" label
      renderTop();
      return;
    }
    state.data = data;
    if (!state.day) state.day = startOfDay(data.nowDate);
    if (!keepView) state.view = "overview";
    render();
  }
  async function syncNow() {
    state.syncing = true; renderTop();
    try { await api(`/api/dashboard/${state.data.business.id}/sync`, { method: "POST" }); }
    catch (e) { alert(e.message); }
    state.syncing = false;
    await load(state.data.business.id);
    renderTop();
  }

  // ---------- picker ----------
  async function renderPicker() {
    const list = await api("/api/dashboard");
    document.title = "Ajilt-AI Dashboard";
    $app.className = "";
    $app.innerHTML = `
      <div class="picker">
        <div class="top"><div><h1>${esc(L().pickTitle)}</h1></div><div class="spacer"></div>${langToggle()}${themeButton()}</div>
        <p>${esc(L().pickSub)}</p>
        <div class="biz-grid">
          ${list.map((b) => `
            <a class="card biz ${b.calendar_linked ? "" : "off"}" href="/dashboard/${esc(b.id)}">
              <div class="em">${esc(b.emoji)}</div>
              <div class="nm">${esc(nm(b.name))}</div>
              <div class="kd">${esc(nm(b.kind))}</div>
              <div class="st"><span class="sync-dot ${b.calendar_linked ? "" : "err"}"></span>${esc(b.calendar_linked ? L().linked : L().noCalendar)}</div>
            </a>`).join("")}
        </div>
      </div>`;
    bindCommon(renderPicker);
  }

  // ---------- shell ----------
  function langToggle() {
    return `<div class="seg" role="group" aria-label="Language">
      <button data-lang="mn" class="${state.lang === "mn" ? "on" : ""}">MN</button>
      <button data-lang="en" class="${state.lang === "en" ? "on" : ""}">EN</button></div>`;
  }
  function themeButton() {
    return `<button class="ctrl" data-theme-toggle title="${esc(L().theme)}" aria-label="${esc(L().theme)}" style="display:grid;place-items:center;padding:7px 9px"><span style="width:16px;height:16px;display:block">${icon("moon")}</span></button>`;
  }
  function bindCommon(rerender) {
    $app.querySelectorAll("[data-lang]").forEach((b) => b.onclick = () => { state.lang = b.dataset.lang; store.set("ajilt-lang", state.lang); document.documentElement.lang = state.lang; rerender(); });
    $app.querySelectorAll("[data-theme-toggle]").forEach((b) => b.onclick = () => {
      const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      document.documentElement.dataset.theme = dark ? "light" : "dark";
      store.set("ajilt-theme", document.documentElement.dataset.theme);
      rerender();
    });
  }

  function views() {
    return [
      ["overview", L().overview, "overview"],
      ["bookings", L().bookings, "bookings"],
      ["schedule", L().schedule, "schedule"],
      ["staff", term()[state.lang].staff, "staff"],
      ["customers", term()[state.lang].Customers, "customers"],
    ];
  }

  function render() {
    const d = state.data;
    document.title = `${nm(d.business.name)} · Ajilt-AI`;
    document.documentElement.lang = state.lang;
    $app.className = "";
    $app.innerHTML = `
      <div class="shell">
        <aside class="side">
          <div class="brand"><div class="brand-mark">${esc(d.business.emoji)}</div>
            <div>${esc(nm(d.business.name))}<small>${esc(nm(d.business.kind))}</small></div></div>
          ${views().map(([id, label, ic]) => `<button class="nav-btn ${state.view === id ? "active" : ""}" data-view="${id}">${icon(ic)}${esc(label)}</button>`).join("")}
          <div class="side-foot">
            <a href="/dashboard">← ${esc(L().back)}</a>
            <div>Ajilt-AI · Google Calendar</div>
          </div>
        </aside>
        <main class="main"><div id="top"></div><div id="view"></div></main>
      </div>`;
    $app.querySelectorAll("[data-view]").forEach((b) => b.onclick = () => { state.view = b.dataset.view; render(); });
    renderTop();
    renderView();
  }

  function renderTop() {
    const d = state.data;
    const title = views().find((v) => v[0] === state.view)[1];
    const sync = d.sync || {};
    let syncText = L().noCalendar, err = !d.calendar_linked;
    if (state.syncing) syncText = L().syncing;
    else if (sync.error) { syncText = L().syncErr; err = true; }
    else if (sync.synced_at) syncText = t("synced", { t: hhmm(new Date(sync.synced_at * 1000)) });
    const showRange = state.view === "overview" || state.view === "staff";
    document.getElementById("top").innerHTML = `
      <div class="top">
        <div><h1>${esc(title)}</h1><div class="sub">${esc(dateLabel(d.nowDate))} · ${hhmm(d.nowDate)}</div></div>
        <div class="spacer"></div>
        ${showRange ? `<div class="seg" role="group" aria-label="Range">${[7, 30, 90].map((n) => `<button data-range="${n}" class="${state.range === n ? "on" : ""}">${esc(t("lastDays", { d: n }))}</button>`).join("")}</div>` : ""}
        <span class="sub" title="${esc(sync.error || "")}"><span class="sync-dot ${err ? "err" : ""}"></span>${esc(syncText)}</span>
        <button class="ctrl primary" data-sync ${state.syncing || !d.calendar_linked ? "disabled" : ""}>${esc(L().sync)}</button>
        ${langToggle()}${themeButton()}
      </div>`;
    const top = document.getElementById("top");
    top.querySelectorAll("[data-range]").forEach((b) => b.onclick = () => { state.range = Number(b.dataset.range); store.set("ajilt-range", state.range); render(); });
    top.querySelector("[data-sync]").onclick = syncNow;
    bindCommon(render);
  }

  function renderView() {
    state.charts.forEach((c) => c.destroy());
    state.charts = [];
    const $v = document.getElementById("view");
    ({ overview: viewOverview, bookings: viewBookings, schedule: viewSchedule, staff: viewStaff, customers: viewCustomers })[state.view]($v);
  }

  // ---------- overview ----------
  function kpi({ label, value, foot, iconName, hero }) {
    return `<div class="card kpi ${hero ? "hero" : ""}">
      <div class="label"><span class="icon">${icon(iconName)}</span>${esc(label)}</div>
      <div class="value">${value}</div><div class="foot">${foot || ""}</div></div>`;
  }
  function delta(cur, prev, suffix = "") {
    if (!prev) return "";
    const pct = Math.round(((cur - prev) / prev) * 100);
    const cls = pct >= 0 ? "up" : "down";
    return `<span class="delta ${cls}">${pct >= 0 ? "▲" : "▼"} ${Math.abs(pct)}%${suffix}</span> ${esc(t("vsPrev", { d: state.range }))}`;
  }

  function viewOverview($v) {
    const d = state.data, ev = d.events;
    const [from, to] = rangeBounds(0), [pFrom, pTo] = rangeBounds(1);
    const cur = ev.filter((e) => inRange(e, from, to));
    const prev = ev.filter((e) => inRange(e, pFrom, pTo));
    const ok = cur.filter((e) => !e.isCancelled), okPrev = prev.filter((e) => !e.isCancelled);
    const today = startOfDay(d.nowDate), tomorrow = addDays(today, 1);
    const todays = ev.filter((e) => !e.isCancelled && inRange(e, today, tomorrow));
    const future = ev.filter((e) => e.isFuture && !e.isCancelled);
    const newC = ok.filter((e) => e.customer_type === "new").length;
    const newPrev = okPrev.filter((e) => e.customer_type === "new").length;
    const regShare = ok.length ? Math.round((100 * (ok.length - newC)) / ok.length) : 0;
    const rev = ok.reduce((s, e) => s + e.price, 0), revPrev = okPrev.reduce((s, e) => s + e.price, 0);
    const cancelled = cur.length - ok.length;

    const tiles = [
      kpi({ label: L().todayBookings, value: todays.length, iconName: "today", hero: true,
            foot: esc(t("remaining", { n: todays.filter((e) => e.isFuture).length })) }),
      kpi({ label: L().upcomingN, value: fmtNum(future.length), iconName: "bookings",
            foot: `<span class="delta up">${esc(t("newIn24", { n: future.filter((e) => e.isFresh).length }))}</span>` }),
      kpi({ label: L().bookingsN, value: fmtNum(ok.length), iconName: "trend", foot: delta(ok.length, okPrev.length) }),
      kpi({ label: t("newCustomers"), value: fmtNum(newC), iconName: "userPlus", foot: delta(newC, newPrev) }),
      kpi({ label: t("returning"), value: regShare + "%", iconName: "repeat",
            foot: esc(`${fmtNum(ok.length - newC)} / ${fmtNum(ok.length)}`) }),
    ];
    if (term().revenue) tiles.push(kpi({ label: L().revenue, value: fmtMoney(rev), iconName: "money", foot: delta(rev, revPrev) }));
    tiles.push(kpi({ label: L().cancelRate, value: (cur.length ? Math.round((100 * cancelled) / cur.length) : 0) + "%", iconName: "x",
                     foot: esc(t("cancelledN", { n: cancelled })) }));

    const upcoming = future.slice(0, 8);
    const special = term().funnel ? funnelCard() : lapsedCard();

    $v.innerHTML = `
      <div class="grid kpis">${tiles.join("")}</div>
      <div class="grid two">
        <div class="card"><h2>${esc(L().weekly)}</h2><div class="hint">${esc(L().weeklyHint)}</div>
          <div class="legend"><span><i style="background:${cssVar("--s1")}"></i>${esc(L().firstTime)}</span><span><i style="background:${cssVar("--s3")}"></i>${esc(L().regular)}</span></div>
          <div class="chart-box"><canvas id="weekly" role="img" aria-label="${esc(L().weekly)}"></canvas></div></div>
        <div class="card"><h2>${esc(L().channels)}</h2><div class="hint">${esc(L().channelsHint)} · ${esc(t("lastDays", { d: state.range }))}</div>
          ${channelBars(ok)}</div>
      </div>
      <div class="grid halves">
        <div class="card"><h2>${esc(t("byStaff"))}</h2><div class="hint">${esc(t("lastDays", { d: state.range }))}</div>${staffBars(ok)}</div>
        <div class="card"><h2>${esc(L().topServices)}</h2><div class="hint">${esc(t("lastDays", { d: state.range }))}</div>${serviceBars(ok)}</div>
      </div>
      <div class="grid two">
        <div class="card"><div class="card-head"><div><h2>${esc(L().nextUp)}</h2></div>
          <button class="ctrl" data-goto="bookings">${esc(L().viewAll)}</button></div>
          ${bookingTable(upcoming, { compact: true })}</div>
        ${special}
      </div>`;
    $v.querySelector("[data-goto]").onclick = () => { state.view = "bookings"; state.bookings.tab = "upcoming"; render(); };
    $v.querySelectorAll("[data-customer-tab]").forEach((b) => b.onclick = () => { state.view = "customers"; state.customers.tab = b.dataset.customerTab; render(); });
    drawWeekly();
  }

  function barList(items, { money = false } = {}) {
    const max = Math.max(1, ...items.map((i) => i.value));
    const total = items.reduce((s, i) => s + i.value, 0) || 1;
    if (!items.length) return `<div class="empty">${esc(L().noRows)}</div>`;
    return `<div class="bars">${items.map((i) => `
      <div class="bar-row" data-tip="${esc(i.label)}: ${esc(money ? fmtMoney(i.value) : fmtNum(i.value))} (${Math.round((100 * i.value) / total)}%)">
        <span class="name">${i.dot ? `<span class="dot" style="background:${i.color};margin-right:6px"></span>` : ""}${esc(i.label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(100 * i.value) / max}%;background:${i.color}"></div></div>
        <span class="num">${esc(money ? fmtMoney(i.value) : fmtNum(i.value))} <small>${Math.round((100 * i.value) / total)}%</small></span>
      </div>`).join("")}</div>`;
  }
  function countBy(list, key) {
    const m = {};
    for (const e of list) m[e[key]] = (m[e[key]] || 0) + 1;
    return m;
  }
  function channelBars(ok) {
    const m = countBy(ok, "source");
    const order = ["chatbot", "phone", "walk-in", "manual"];
    const vars = { chatbot: "--s1", phone: "--s2", "walk-in": "--s4", manual: "--muted" };
    return barList(order.filter((k) => m[k]).map((k) => ({ label: L()[k] || k, value: m[k], color: cssVar(vars[k]) })));
  }
  function staffBars(ok) {
    const m = countBy(ok, "staff_id");
    const items = state.data.staff.map((p) => ({ label: nm(p.name), value: m[p.id] || 0, color: staffColor(p.id), dot: true }));
    if (m[""]) items.push({ label: L().unassigned, value: m[""], color: cssVar("--muted"), dot: true });
    return barList(items.sort((a, b) => b.value - a.value));
  }
  function serviceBars(ok) {
    const m = countBy(ok, "service_id");
    return barList(Object.entries(m).filter(([k]) => k).sort((a, b) => b[1] - a[1]).slice(0, 6)
      .map(([k, v]) => ({ label: nm(state.data.serviceById[k]?.name) || k, value: v, color: cssVar("--s1") })));
  }

  function lapsedCard() {
    const days = term().lapsedDays;
    const list = state.data.customers.filter((c) => c.lapsed).sort((a, b) => b.visits - a.visits).slice(0, 6);
    return `<div class="card"><div class="card-head"><div><h2>${esc(L().lapsed)} <span class="badge lapsed">${state.data.customers.filter((c) => c.lapsed).length}</span></h2>
      <div class="hint">${esc(t("lapsedHint", { d: days }))}</div></div>
      <button class="ctrl" data-customer-tab="lapsed">${esc(L().viewAll)}</button></div>
      ${list.length ? `<table><tbody>${list.map((c) => `<tr>
        <td><div class="who"><span class="avatar" style="background:${staffColor(c.favorite)}">${esc(initials(c.name))}</span>
          <div>${esc(c.name)}<div class="sub" style="color:var(--muted);font-size:12px">${esc(c.phone)}</div></div></div></td>
        <td style="text-align:right">${c.visits}× · ${esc(dateLabel(c.last, false))}</td></tr>`).join("")}</tbody></table>`
        : `<div class="empty">—</div>`}</div>`;
  }

  function funnelCard() {
    // families (by customer) who booked a tour, and how many of them later booked a consultation
    const toured = {}, consulted = new Set();
    for (const e of state.data.events) {
      if (e.isCancelled) continue;
      if (e.service_id === "tour" && !(e.customer in toured)) toured[e.customer] = e.start;
      if (e.service_id !== "tour" && toured[e.customer] && e.start > toured[e.customer]) consulted.add(e.customer);
    }
    const n = Object.keys(toured).length, m = consulted.size;
    const items = [
      { label: nm(state.data.serviceById.tour?.name), value: n, color: cssVar("--s1") },
      { label: nm(state.data.serviceById.admissions?.name), value: m, color: cssVar("--s3") },
    ];
    return `<div class="card"><h2>${esc(L().funnel)}</h2><div class="hint">${esc(L().funnelHint)}</div>
      ${barList(items)}<div class="value" style="font-size:28px;font-weight:700;margin-top:16px">${n ? Math.round((100 * m) / n) : 0}%</div></div>`;
  }

  function drawWeekly() {
    const d = state.data;
    const weekStart = (x) => { const s = startOfDay(x); s.setDate(s.getDate() - ((s.getDay() + 6) % 7)); return s; };
    const first = addDays(weekStart(d.nowDate), -7 * 11);
    const labels = [], newCounts = Array(12).fill(0), regCounts = Array(12).fill(0);
    for (let i = 0; i < 12; i++) labels.push(dateLabel(addDays(first, 7 * i), false));
    for (const e of d.events) {
      if (e.isCancelled || e.start < first) continue;
      const i = Math.floor((startOfDay(e.start) - first) / (7 * 864e5));
      if (i < 0 || i > 11) continue;
      (e.customer_type === "new" ? newCounts : regCounts)[i]++;
    }
    const ctx = document.getElementById("weekly");
    if (!ctx || !window.Chart) return;
    const muted = cssVar("--muted"), grid = cssVar("--grid"), surface = cssVar("--surface");
    state.charts.push(new Chart(ctx, {
      type: "bar",
      data: { labels, datasets: [
        { label: L().firstTime, data: newCounts, backgroundColor: cssVar("--s1"), borderRadius: 4, borderColor: surface, borderWidth: { top: 2 }, borderSkipped: false, maxBarThickness: 28 },
        { label: L().regular, data: regCounts, backgroundColor: cssVar("--s3"), borderRadius: 4, borderColor: surface, borderWidth: { top: 2 }, borderSkipped: false, maxBarThickness: 28 },
      ] },
      options: {
        maintainAspectRatio: false, responsive: true,
        interaction: { mode: "index", intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { footer: (items) => `Σ ${items.reduce((s, i) => s + i.parsed.y, 0)}` } } },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: muted, font: { size: 11 } }, border: { color: cssVar("--axis") } },
          y: { stacked: true, grid: { color: grid }, ticks: { color: muted, precision: 0, font: { size: 11 } }, border: { display: false } },
        },
      },
    }));
  }

  // ---------- bookings ----------
  function bookingTable(rows, { compact = false } = {}) {
    if (!rows.length) return `<div class="empty">${esc(L().noRows)}</div>`;
    const d = state.data;
    return `<div class="table-wrap"><table>
      <thead><tr><th>${esc(L().date)}</th><th>${esc(L().time)}</th><th>${esc(L().customer)}</th><th>${esc(L().service)}</th>
        <th>${esc(term()[state.lang].Staff1)}</th>${compact ? "" : `<th>${esc(L().channel)}</th><th>${esc(L().status)}</th>`}</tr></thead>
      <tbody>${rows.map((e) => {
        const p = d.staffById[e.staff_id];
        const status = e.isCancelled ? "cancelled" : e.isFuture ? "upcoming" : "done";
        const statusText = e.isCancelled ? L().cancelled : e.isFuture ? L().booked : L().done;
        return `<tr class="${e.isCancelled ? "cancelled" : ""}">
          <td>${esc(dateLabel(e.start))}</td><td>${hhmm(e.start)}–${hhmm(e.end)}</td>
          <td>${e.isFresh && !e.isCancelled ? `<span class="badge fresh" style="margin:0 6px 0 0">${esc(L().justBooked)}</span>` : ""}<span class="cust">${esc(e.name || "—")}</span><span class="badge ${e.customer_type}" title="${esc(t("visit", { n: e.visit }))}">${esc(e.customer_type === "new" ? L().firstTime : L().regular)}${e.customer_type === "regular" ? ` · ${e.visit}` : ""}</span>
            ${compact ? "" : `<div style="color:var(--muted);font-size:12px">${esc(e.phone)}</div>`}</td>
          <td>${esc(nm(d.serviceById[e.service_id]?.name) || "—")}</td>
          <td>${p ? `<span class="who"><span class="dot" style="background:${staffColor(p.id)}"></span>${esc(nm(p.name))}</span>` : `<span style="color:var(--muted)">${esc(L().unassigned)}</span>`}</td>
          ${compact ? "" : `<td><span class="chip ${e.source}">${esc(L()[e.source] || e.source)}</span></td><td><span class="status ${status}">${esc(statusText)}</span></td>`}
        </tr>`;
      }).join("")}</tbody></table></div>`;
  }

  function viewBookings($v) {
    const d = state.data, f = state.bookings;
    let rows = d.events;
    if (f.tab === "upcoming") rows = rows.filter((e) => e.isFuture && !e.isCancelled);
    if (f.tab === "past") rows = rows.filter((e) => !e.isFuture && !e.isCancelled).reverse();
    if (f.tab === "cancelled") rows = rows.filter((e) => e.isCancelled).reverse();
    if (f.tab === "all") rows = [...rows].reverse();
    if (f.staff) rows = rows.filter((e) => e.staff_id === f.staff);
    if (f.service) rows = rows.filter((e) => e.service_id === f.service);
    if (f.type) rows = rows.filter((e) => e.customer_type === f.type);
    if (f.branch) rows = rows.filter((e) => e.branch_id === f.branch);
    if (f.q) { const q = f.q.toLowerCase(); rows = rows.filter((e) => (e.name || "").toLowerCase().includes(q) || (e.phone || "").includes(q)); }
    const total = rows.length, pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    f.page = Math.min(f.page, pages - 1);
    const pageRows = rows.slice(f.page * PAGE_SIZE, (f.page + 1) * PAGE_SIZE);
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(label)}</option>`;
    $v.innerHTML = `<div class="card">
      <div class="toolbar">
        <div class="tabs">${["upcoming", "past", "cancelled", "all"].map((k) => `<button data-tab="${k}" class="${f.tab === k ? "on" : ""}">${esc(L()[k])}</button>`).join("")}</div>
        <input type="search" placeholder="${esc(L().search)}" value="${esc(f.q)}" data-f="q">
        <select data-f="staff">${opt("", L().allStaff, f.staff)}${d.staff.map((p) => opt(p.id, nm(p.name), f.staff)).join("")}</select>
        <select data-f="service">${opt("", L().allServices, f.service)}${d.services.map((s) => opt(s.id, nm(s.name), f.service)).join("")}</select>
        <select data-f="type">${opt("", L().allTypes, f.type)}${opt("new", L().firstTime, f.type)}${opt("regular", L().regular, f.type)}</select>
        ${d.branches.length ? `<select data-f="branch">${opt("", L().allBranches, f.branch)}${d.branches.map((b) => opt(b.id, nm(b.name), f.branch)).join("")}</select>` : ""}
      </div>
      ${bookingTable(pageRows)}
      <div class="pager">${esc(t("shown", { a: total ? f.page * PAGE_SIZE + 1 : 0, b: Math.min(total, (f.page + 1) * PAGE_SIZE), n: total }))}
        <button class="ctrl" data-page="-1" ${f.page ? "" : "disabled"}>${esc(L().prev)}</button>
        <button class="ctrl" data-page="1" ${f.page < pages - 1 ? "" : "disabled"}>${esc(L().next)}</button></div>
    </div>`;
    $v.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { f.tab = b.dataset.tab; f.page = 0; renderView(); });
    $v.querySelectorAll("select[data-f]").forEach((s) => s.onchange = () => { f[s.dataset.f] = s.value; f.page = 0; renderView(); });
    const q = $v.querySelector("input[data-f=q]");
    q.oninput = () => { f.q = q.value; f.page = 0; clearTimeout(q._t); q._t = setTimeout(() => { renderView(); const n = document.querySelector("input[data-f=q]"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 200); };
    $v.querySelectorAll("[data-page]").forEach((b) => b.onclick = () => { f.page += Number(b.dataset.page); renderView(); });
  }

  // ---------- schedule ----------
  function viewSchedule($v) {
    const d = state.data, day = state.day;
    const spec = d.hours[WEEKDAYS[day.getDay()]];
    const branchF = state.bookings.branch;
    const staff = d.staff.filter((p) => !branchF || !p.branch || p.branch === branchF);
    const events = d.events.filter((e) => dayKey(e.start) === dayKey(day) && (!branchF || e.branch_id === branchF));
    const cols = staff.length ? staff : [{ id: "", name: { mn: "—", en: "—" } }];
    if (events.some((e) => !e.staff_id) && staff.length) cols.push({ id: "", name: { mn: L().unassigned, en: L().unassigned } });

    let body;
    if (!spec && !events.length) {
      body = `<div class="empty">${esc(L().closed)}</div>`;
    } else {
      const [o, c] = (spec || "09:00-18:00").split("-");
      let open = Number(o.split(":")[0]), close = Math.ceil(Number(c.split(":")[0]) + Number(c.split(":")[1]) / 60);
      for (const e of events) { open = Math.min(open, e.start.getHours()); close = Math.max(close, e.end.getHours() + (e.end.getMinutes() ? 1 : 0)); }
      const PX = 64; // per hour
      const height = (close - open) * PX;
      const y = (dt) => ((dt.getHours() + dt.getMinutes() / 60) - open) * PX;
      const lines = Array.from({ length: close - open + 1 }, (_, i) => `<div class="sched-line" style="top:${i * PX}px"></div>`).join("");
      const nowLine = dayKey(d.nowDate) === dayKey(day) && d.nowDate.getHours() >= open && d.nowDate.getHours() < close
        ? `<div class="now-line" style="top:${y(d.nowDate)}px"></div>` : "";
      body = `<div class="sched-wrap"><div class="sched" style="grid-template-columns:56px repeat(${cols.length}, minmax(130px, 1fr))">
        <div class="sched-head"></div>
        ${cols.map((p) => `<div class="sched-head">${p.id ? `<span class="avatar" style="width:24px;height:24px;font-size:11px;background:${staffColor(p.id)}">${esc(initials(nm(p.name)))}</span>` : ""}${esc(nm(p.name))}
          <span style="color:var(--muted);font-weight:400">${events.filter((e) => e.staff_id === p.id && !e.isCancelled).length}</span></div>`).join("")}
        <div class="sched-times" style="height:${height}px">${Array.from({ length: close - open + 1 }, (_, i) => `<div style="top:${i * PX}px">${String(open + i).padStart(2, "0")}:00</div>`).join("")}</div>
        ${cols.map((p) => `<div class="sched-col" style="height:${height}px">${lines}${nowLine}
          ${events.filter((e) => e.staff_id === p.id).map((e) => {
            const color = p.id ? staffColor(p.id) : cssVar("--muted");
            const tip = `${hhmm(e.start)}–${hhmm(e.end)} · ${nm(d.serviceById[e.service_id]?.name) || ""}\n${e.name} ${e.phone}\n${e.customer_type === "new" ? L().firstTime : L().regular + " · " + t("visit", { n: e.visit })} · ${L()[e.source] || e.source}${e.isCancelled ? " · " + L().cancelled : ""}`;
            return `<div class="appt ${e.isCancelled ? "cancelled" : ""}" data-tip="${esc(tip)}" style="top:${y(e.start) + 1}px;height:${Math.max(22, y(e.end) - y(e.start) - 2)}px;border-left-color:${color}">
              <b>${esc(e.name)}${e.customer_type === "new" ? " ✦" : ""}</b><span>${hhmm(e.start)} · ${esc(nm(d.serviceById[e.service_id]?.name) || "")}</span></div>`;
          }).join("")}</div>`).join("")}
      </div></div>`;
    }
    $v.innerHTML = `<div class="card">
      <div class="toolbar">
        <div class="day-nav">
          <button class="ctrl" data-day="-1" aria-label="${esc(L().prev)}">‹</button>
          <button class="ctrl" data-day="0">${esc(L().today)}</button>
          <button class="ctrl" data-day="1" aria-label="${esc(L().next)}">›</button>
          <input type="date" value="${dayKey(day)}" data-date>
          <b style="margin-left:6px">${esc(dateLabel(day))}</b>
        </div>
        <div class="spacer" style="flex:1"></div>
        ${d.branches.length ? `<select data-branch>${[["", L().allBranches], ...d.branches.map((b) => [b.id, nm(b.name)])].map(([v, l]) => `<option value="${esc(v)}" ${branchF === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>` : ""}
        <span class="legend" style="margin:0"><span>✦ ${esc(L().firstTime)}</span></span>
      </div>
      ${body}
    </div>`;
    $v.querySelectorAll("[data-day]").forEach((b) => b.onclick = () => {
      const n = Number(b.dataset.day);
      state.day = n === 0 ? startOfDay(d.nowDate) : addDays(state.day, n);
      renderView();
    });
    $v.querySelector("[data-date]").onchange = (e) => { if (e.target.value) { state.day = parse(e.target.value); renderView(); } };
    const br = $v.querySelector("[data-branch]");
    if (br) br.onchange = () => { state.bookings.branch = br.value; renderView(); };
  }

  // ---------- staff ----------
  function openMinutes(from, days) {
    let total = 0;
    for (let i = 0; i < days; i++) {
      const day = addDays(from, i), spec = state.data.hours[WEEKDAYS[day.getDay()]];
      if (!spec) continue;
      const [o, c] = spec.split("-").map((s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; });
      total += c - o;
    }
    return total;
  }
  function viewStaff($v) {
    const d = state.data;
    const [from, to] = rangeBounds(0);
    const today = startOfDay(d.nowDate), tomorrow = addDays(today, 1);
    const wk = startOfDay(d.nowDate); wk.setDate(wk.getDate() - ((wk.getDay() + 6) % 7));
    const weekOpen = openMinutes(wk, 7);
    $v.innerHTML = `<div class="grid staff-grid">${d.staff.map((p) => {
      const mine = d.events.filter((e) => e.staff_id === p.id && !e.isCancelled);
      const ranged = mine.filter((e) => inRange(e, from, to));
      const todays = mine.filter((e) => inRange(e, today, tomorrow));
      const week = mine.filter((e) => inRange(e, wk, addDays(wk, 7)));
      const bookedMin = week.reduce((s, e) => s + (e.end - e.start) / 6e4, 0);
      const load = weekOpen ? Math.min(100, Math.round((100 * bookedMin) / weekOpen)) : 0;
      const next = mine.find((e) => e.start >= d.nowDate);
      const reg = ranged.length ? Math.round((100 * ranged.filter((e) => e.customer_type === "regular").length) / ranged.length) : 0;
      const rev = ranged.reduce((s, e) => s + e.price, 0);
      const color = staffColor(p.id);
      const branch = d.branches.find((b) => b.id === p.branch);
      return `<div class="card staff-card">
        <div class="top-row"><span class="avatar" style="background:${color}">${esc(initials(nm(p.name)))}</span>
          <div><div class="nm">${esc(nm(p.name))}</div><div class="role">${esc(nm(p.role))}${branch ? " · " + esc(nm(branch.name)) : ""}</div></div></div>
        <div class="load-label"><span>${esc(L().load)}</span><b>${load}%</b></div>
        <div class="bar-track"><div class="bar-fill" style="width:${load}%;background:${color}"></div></div>
        <div class="stats3">
          <div><b>${todays.length}</b><span>${esc(L().today)}</span></div>
          <div><b>${ranged.length}</b><span>${esc(t("inRange", { d: state.range }))}</span></div>
          ${term().revenue ? `<div><b>${esc(fmtMoney(rev))}</b><span>${esc(L().rev)}</span></div>` : `<div><b>${reg}%</b><span>${esc(L().regShare)}</span></div>`}
        </div>
        <div class="next">${next ? esc(t("nextAppt", { t: `${dateLabel(next.start, false)} ${hhmm(next.start)}`, n: next.name })) : esc(L().noNext)}</div>
        <button class="ctrl" style="margin-top:12px;width:100%" data-staff="${esc(p.id)}">${esc(L().viewBookings)}</button>
      </div>`;
    }).join("")}</div>`;
    $v.querySelectorAll("[data-staff]").forEach((b) => b.onclick = () => {
      Object.assign(state.bookings, { staff: b.dataset.staff, tab: "upcoming", page: 0 });
      state.view = "bookings"; render();
    });
  }

  // ---------- customers ----------
  function viewCustomers($v) {
    const d = state.data, f = state.customers;
    let rows = d.customers.filter((c) => c.visits || c.next);
    if (f.tab === "new") rows = rows.filter((c) => c.type === "new");
    if (f.tab === "regular") rows = rows.filter((c) => c.type === "regular");
    if (f.tab === "lapsed") rows = rows.filter((c) => c.lapsed);
    if (f.q) { const q = f.q.toLowerCase(); rows = rows.filter((c) => (c.name || "").toLowerCase().includes(q) || (c.phone || "").includes(q)); }
    // most recent visitors first; people who have only booked ahead go last
    rows.sort((a, b) => (b.last || 0) - (a.last || 0) || (a.next || 0) - (b.next || 0));
    const total = rows.length, pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    f.page = Math.min(f.page, pages - 1);
    const counts = { all: d.customers.filter((c) => c.visits || c.next).length, new: 0, regular: 0, lapsed: 0 };
    for (const c of d.customers) { if (!(c.visits || c.next)) continue; counts[c.type]++; if (c.lapsed) counts.lapsed++; }
    const tabLabel = { all: L().all, new: L().firstTime, regular: L().regular, lapsed: L().lapsed };
    $v.innerHTML = `<div class="card">
      <div class="toolbar">
        <div class="tabs">${["all", "new", "regular", "lapsed"].map((k) => `<button data-tab="${k}" class="${f.tab === k ? "on" : ""}">${esc(tabLabel[k])} <span style="color:var(--muted)">${counts[k]}</span></button>`).join("")}</div>
        <input type="search" placeholder="${esc(L().search)}" value="${esc(f.q)}" data-q>
      </div>
      ${f.tab === "lapsed" ? `<div class="hint" style="margin-bottom:10px">${esc(t("lapsedHint", { d: term().lapsedDays }))}</div>` : ""}
      ${total ? `<div class="table-wrap"><table>
        <thead><tr><th>${esc(L().customer)}</th><th>${esc(L().customerType)}</th><th>${esc(L().visits)}</th><th>${esc(L().lastVisit)}</th>
          <th>${esc(L().nextVisit)}</th><th>${esc(L().usually)}</th>${term().revenue ? `<th>${esc(L().spent)}</th>` : ""}</tr></thead>
        <tbody>${rows.slice(f.page * PAGE_SIZE, (f.page + 1) * PAGE_SIZE).map((c) => {
          const p = d.staffById[c.favorite];
          return `<tr>
            <td><div class="who"><span class="avatar" style="background:${p ? staffColor(p.id) : cssVar("--muted")}">${esc(initials(c.name))}</span>
              <div>${esc(c.name)}<div style="color:var(--muted);font-size:12px">${esc(c.phone)}</div></div></div></td>
            <td><span class="badge ${c.lapsed ? "lapsed" : c.type}" style="margin:0">${esc(c.lapsed ? L().lapsed : c.type === "new" ? L().firstTime : L().regular)}</span></td>
            <td>${c.visits}</td>
            <td>${c.last ? esc(dateLabel(c.last, false)) : "—"}</td>
            <td>${c.next ? esc(`${dateLabel(c.next, false)} ${hhmm(c.next)}`) : "—"}</td>
            <td>${p ? `<span class="who"><span class="dot" style="background:${staffColor(p.id)}"></span>${esc(nm(p.name))}</span>` : "—"}</td>
            ${term().revenue ? `<td>${esc(fmtMoney(c.spent))}</td>` : ""}
          </tr>`;
        }).join("")}</tbody></table></div>` : `<div class="empty">${esc(L().noRows)}</div>`}
      <div class="pager">${esc(t("shown", { a: total ? f.page * PAGE_SIZE + 1 : 0, b: Math.min(total, (f.page + 1) * PAGE_SIZE), n: total }))}
        <button class="ctrl" data-page="-1" ${f.page ? "" : "disabled"}>${esc(L().prev)}</button>
        <button class="ctrl" data-page="1" ${f.page < pages - 1 ? "" : "disabled"}>${esc(L().next)}</button></div>
    </div>`;
    $v.querySelectorAll("[data-tab]").forEach((b) => b.onclick = () => { f.tab = b.dataset.tab; f.page = 0; renderView(); });
    $v.querySelectorAll("[data-page]").forEach((b) => b.onclick = () => { f.page += Number(b.dataset.page); renderView(); });
    const q = $v.querySelector("[data-q]");
    q.oninput = () => { f.q = q.value; f.page = 0; clearTimeout(q._t); q._t = setTimeout(() => { renderView(); const n = document.querySelector("[data-q]"); n.focus(); n.setSelectionRange(n.value.length, n.value.length); }, 200); };
  }

  // ---------- tooltips for bar lists and schedule blocks ----------
  document.addEventListener("mouseover", (e) => {
    const el = e.target.closest("[data-tip]");
    if (!el) { $tip.hidden = true; return; }
    $tip.textContent = el.dataset.tip;
    $tip.style.whiteSpace = "pre-line";
    $tip.hidden = false;
  });
  document.addEventListener("mousemove", (e) => {
    if ($tip.hidden) return;
    const x = Math.min(e.clientX + 14, innerWidth - $tip.offsetWidth - 8);
    $tip.style.left = x + "px";
    $tip.style.top = (e.clientY + 14) + "px";
  });

  // ---------- boot ----------
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.data && render());
  const id = decodeURIComponent(location.pathname.replace(/^\/dashboard\/?/, "").replace(/\/$/, ""));
  const fail = (e) => { $app.className = "loading"; $app.textContent = "Error: " + e.message; };
  if (!id) {
    renderPicker().catch(fail);
  } else {
    load(id, false).catch(fail);
    // pick up new chatbot bookings without a page reload
    setInterval(() => { if (!document.hidden && !state.syncing) load(id).catch(() => {}); }, 60000);
  }
})();
