// Staff view of chatbot bookings, filtered by country / branch, with a status picker.
(() => {
  const STATUS = { new: "🆕 Шинэ", confirmed: "✅ Баталгаажсан", done: "☑ Ирсэн",
                   cancelled: "✖ Цуцалсан", no_show: "⚠ Ирээгүй" };
  const CHANNEL = { messenger: "Facebook", instagram: "Instagram", web: "Вэб", cli: "CLI", n8n: "n8n" };
  const WEEKDAYS = ["Ням", "Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба"];
  const $ = (id) => document.getElementById(id);
  let data = null;

  const money = (n, cur) => n == null ? "—" : n === 0 ? "үнэгүй" :
    cur === "KRW" ? "₩" + n.toLocaleString("en-US") : n.toLocaleString("en-US") + "₮";

  function when(iso) {
    // shown in the branch's own time (the ISO string carries its offset)
    const [d, t] = iso.split("T");
    const day = new Date(d + "T12:00:00");
    return `${d} ${WEEKDAYS[day.getDay()]} ${t.slice(0, 5)}`;
  }

  function fillFilters() {
    const country = $("country"), branch = $("branch");
    if (country.options.length === 1) {
      for (const [id, name] of Object.entries(data.countries)) country.add(new Option(name, id));
    }
    const keep = branch.value;
    branch.length = 1;
    for (const b of data.branches) {
      if (!country.value || b.country === country.value) branch.add(new Option(b.name, b.id));
    }
    branch.value = [...branch.options].some((o) => o.value === keep) ? keep : "";
  }

  function render() {
    const names = Object.fromEntries(data.branches.map((b) => [b.id, b.name]));
    const now = new Date().toISOString();
    const rows = data.bookings.filter((b) =>
      (!$("country").value || b.country === $("country").value) &&
      (!$("branch").value || b.branch_id === $("branch").value) &&
      ($("when").value === "all" || ($("when").value === "upcoming") === (new Date(b.end_at).toISOString() >= now)));
    if ($("when").value === "upcoming") rows.reverse();          // soonest first

    $("summary").textContent = `${rows.length} захиалга`;
    const body = $("rows");
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">Захиалга алга</td></tr>`;
      return;
    }
    for (const b of rows) {
      const tr = document.createElement("tr");
      tr.className = b.status;
      const cells = [
        when(b.start_at),
        names[b.branch_id] || b.branch_id,
        data.services[b.service_id] || b.service_id,
        `${b.name}<span class="sub">${b.phone}</span>`,
        money(b.price, b.currency) + (b.payment_status !== "at_clinic" ? `<span class="sub">${b.payment_status}</span>` : ""),
        `${CHANNEL[b.channel] || b.channel}<span class="sub">${(b.lang || "").toUpperCase()}</span>`,
      ];
      for (const html of cells) {
        const td = document.createElement("td");
        td.innerHTML = html;
        tr.appendChild(td);
      }
      const td = document.createElement("td");
      const sel = document.createElement("select");
      for (const s of data.statuses) sel.add(new Option(STATUS[s] || s, s));
      sel.value = b.status || "new";
      sel.onchange = async () => {
        const r = await fetch(`/api/bookings/${b.id}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: sel.value }),
        });
        if (r.ok) { b.status = sel.value; tr.className = b.status; } else { sel.value = b.status; alert("Хадгалж чадсангүй"); }
      };
      td.appendChild(sel);
      tr.appendChild(td);
      body.appendChild(tr);
    }
  }

  async function load() {
    const r = await fetch("/api/bookings");
    data = await r.json();
    fillFilters();
    render();
  }

  $("country").onchange = () => { fillFilters(); render(); };
  $("branch").onchange = render;
  $("when").onchange = render;
  $("reload").onclick = load;
  load();
  setInterval(load, 60000);
})();
