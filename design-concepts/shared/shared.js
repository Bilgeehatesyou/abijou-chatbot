/* ajiltAI design concepts — shared data + helpers (MN).
   Module / tier data copied from ajiltai.tech assets/app.js. */

const IC = {
  chat:'<path d="M4 5h16v11H9l-5 4z"/>',
  book:'<path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4z"/><path d="M5 16a4 4 0 0 1 4-4h10"/>',
  users:'<circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0"/><path d="M16 4.5a3.2 3.2 0 0 1 0 6.4M21 20a6 6 0 0 0-3.5-5.4"/>',
  cal:'<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  bag:'<path d="M5 8h14l-1.2 12H6.2z"/><path d="M9 8V6.5a3 3 0 0 1 6 0V8"/>',
  card:'<rect x="3" y="5.5" width="18" height="13" rx="2.5"/><path d="M3 10h18M7 15h4"/>',
  web:'<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M6.5 6.5h.01M9 6.5h.01"/>',
  chart:'<path d="M5 20v-9M11 20V5M17 20v-7M3 20h18"/>',
  mega:'<path d="M3 10v4h3l8 5V5l-8 5z"/><path d="M18 9a4 4 0 0 1 0 6"/>',
  badge:'<rect x="5" y="3" width="14" height="18" rx="2.5"/><circle cx="12" cy="10" r="2.8"/><path d="M8.5 17a3.5 3.5 0 0 1 7 0"/>',
  phone:'<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>',
  plug:'<path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5"/>',
  user:'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'
};
const icon = n => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n]}</svg>`;

/* n: name, sn: short name, d: description, r: role replaced, s: monthly salary,
   t: status per tier, k: KPIs, f: live feed rows [tag, text, status] */
const MODS = [
 {id:1,ic:"chat",sn:"AI чат",n:"AI чат ба олон суваг",d:"Facebook, Instagram, вэб, Telegram дээрх чатад AI хариулж, шаардлагатай үед хүнд шилжүүлнэ.",r:"Чатын оператор",s:800000,t:{starter:"full",pro:"full",premium:"full"},
  k:[["Өнөөдөр хариулсан","284"],["Дундаж хариу","3 сек"],["Хүнд шилжүүлсэн","6%"]],
  f:[["FB","Анударь: «Маргааш 15:00 сул уу?»","AI · 3с"],["IG","Ганбат: «Будалт хэд вэ?»","AI · 2с"],["Web","Сарнай: гомдол бичлээ","→ Ажилтан"],["TG","Хулан: «Хаана байрладаг вэ?»","AI · 4с"]]},
 {id:2,ic:"book",sn:"Мэдлэгийн сан",n:"AI мэдлэгийн сан",d:"Компанийн мэдээлэл, түгээмэл асуулт, үйлчилгээ, журмын талаар тэр даруй хариулна.",r:"Лавлагааны ажилтан",s:500000,t:{starter:"full",pro:"full",premium:"full"},
  k:[["Асуулт","1,120"],["Шууд хариулсан","94%"],["Баримт бичиг","38"]],
  f:[["Асуулт","«Буцаалтын нөхцөл?»","Журам §4"],["Асуулт","«Ажлын цаг?»","10–18 цаг"],["Асуулт","«Хүргэлт хэд хоног?»","1–3 хоног"],["Шинэ","Үнийн жагсаалт шинэчлэгдсэн","Сурсан ✓"]]},
 {id:3,ic:"users",sn:"Лид ба CRM",n:"Лид ба CRM",d:"Лид бүртгэж, харилцагчийн профайл, түүх, борлуулалтын юүлүүрийг нэг дор хөтөлнө.",r:"Борлуулалтын админ",s:900000,t:{starter:"basic",pro:"full",premium:"custom"},
  k:[["Шинэ лид","47"],["Хөрвүүлэлт","32%"],["Идэвхтэй харилцагч","1,380"]],
  f:[["Лид","Анударь · FB-ээс","Шинэ"],["Санал","Ганбат · үнийн санал","Хэлэлцээр"],["Давтан","Болормаа · 5 дахь удаа","VIP"],["Сэрэмж","Тэмүүжин · 30 хоног ирээгүй","→ Маркетинг"]]},
 {id:4,ic:"cal",sn:"Цаг захиалга",n:"Цаг захиалга",d:"Сул цаг, захиалга, өөрчлөлт, цуцлалт, ажилтны хуваарийг автоматаар зохицуулна.",r:"Ресепшн / цаг товлогч",s:650000,t:{starter:"basic",pro:"full",premium:"custom"},
  k:[["Өнөөдрийн захиалга","18"],["Цагийн дүүргэлт","91%"],["Ирээгүй","−64%"]],
  f:[["10:00","Номин · Үс засалт · Энхжин","✓"],["15:00","Номин · Будалт · Анударь","✓ Шинэ"],["16:00","Цуцлалт → сул цаг нээгдсэн","Дүүрсэн"],["17:30","Тэмүүлэн · Эрэгтэй засалт","✓"]]},
 {id:5,ic:"bag",sn:"Борлуулалт",n:"Борлуулалт ба захиалга",d:"Бараа санал болгож, захиалга үүсгэж, дараа нь хянаж, төлөвийг мэдэгдэнэ.",r:"Захиалга боловсруулагч",s:850000,t:{starter:"addon",pro:"full",premium:"full"},
  k:[["Захиалга","37"],["Нэмэлт борлуулалт","+18%"],["Дундаж сагс","86,000₮"]],
  f:[["#1042","Пүүз ×1 · Төлөгдсөн","Савлаж буй"],["#1043","Hoodie ×2","Хүргэлтэнд"],["#1044","Шампунь · санал болгосон","Нэмсэн ✓"],["#1045","Арьс арчилгааны багц","Хүлээгдэж буй"]]},
 {id:6,ic:"card",sn:"Төлбөр · и-Баримт",n:"Төлбөр ба и-Баримт",d:"QPay, төлбөрийн линк, урьдчилгаа, төлөв, и-Баримтыг автоматжуулна.",r:"Тооцооны ажилтан",s:700000,t:{starter:"addon",pro:"full",premium:"advanced"},
  k:[["Өнөөдөр орсон","2.35 сая₮"],["и-Баримт","38"],["Хугацаа хэтэрсэн","0"]],
  f:[["QPay","Анударь · 75,000₮","и-Баримт ✓"],["Линк","Урьдчилгаа · 30,000₮","Төлөгдсөн"],["QPay","Ганбат · 159,000₮","Сануулга →"],["Тулгалт","Банкны хуулга","Таарсан ✓"]]},
 {id:7,ic:"web",sn:"Вэбсайт",n:"Вэбсайт ба вэб апп",d:"Доод багцад бэлэн загвар; Premium-д захиалгат дизайн, ажлын урсгалтай.",r:"Веб хөгжүүлэгч",s:1000000,t:{starter:"template",pro:"template",premium:"custom"},
  k:[["Өнөөдрийн зочин","1,240"],["Ачаалах хурд","0.9 сек"],["Форм → захиалга","11%"]],
  f:[["/","Нүүр хуудас","1,240 зочин"],["/booking","Захиалгын форм","→ Цаг захиалга"],["chat","Чат bubble","→ AI чат"],["/menu","Үйлчилгээний жагсаалт","Шинэчлэгдсэн"]]},
 {id:8,ic:"chart",sn:"Самбар · тайлан",n:"Хяналтын самбар ба тайлан",d:"Лид, захиалга, борлуулалт, орлого, ажилтан, AI-н гүйцэтгэлийг нэг самбарт харуулна.",r:"Тайлангийн шинжээч",s:1100000,t:{starter:"addon",pro:"full",premium:"advanced"},
  k:[["Өнөөдрийн орлого","2.35 сая₮"],["7 хоногт","+18%"],["AI-н гүйцэтгэл","86%"]],
  f:[["Орлого","Даваа → Ням","↑ 18%"],["Салбар","Зайсан тэргүүлж байна","1.2 сая₮"],["Ажилтан","Номин · 9 үйлчилгээ","Шилдэг"],["Тайлан","7 хоногийн тайлан","PDF ✓"]]},
 {id:9,ic:"mega",sn:"Маркетинг",n:"Маркетингийн автоматжуулалт",d:"Сануулга, дараах хяналт, дахин идэвхжүүлэлт, кампанит ажлыг автоматжуулна.",r:"Маркетингийн зохицуулагч",s:900000,t:{starter:"addon",pro:"full",premium:"advanced"},
  k:[["Сануулга","42"],["Эргэж ирсэн","18"],["Кампанит хүрэлт","1,120"]],
  f:[["Сануулга","Маргаашийн 42 захиалга","Илгээсэн"],["Эргүүлэх","30 хоног ирээгүй · 18 хүн","Илгээсэн"],["Кампанит","«Намрын −15%»","1,120 хүрсэн"],["Үнэлгээ","Үйлчилгээний дараах асуулга","4.8 / 5"]]},
 {id:10,ic:"badge",sn:"Дотоод AI",n:"Дотоод AI ажилтан",d:"Дотоод журам, СОП, мэдлэгийн талаар ажилчдад тэр даруй хариулна.",r:"Дотоод үйл ажиллагааны туслах",s:900000,t:{starter:"none",pro:"addon",premium:"full"},
  k:[["Ажилтны асуулт","64"],["СОП баримт","52"],["Сургалтын хугацаа","−40%"]],
  f:[["HR","«Амралтын хүсэлт яаж өгөх вэ?»","Журам §2"],["СОП","«Кассын хаалт?»","СОП-07"],["Сургалт","Шинэ ажилтан · 5 алхам","3/5"],["Эрх","«Буцаалт хийх эрх хэнд?»","Менежер"]]},
 {id:11,ic:"phone",sn:"Дуу хоолой AI",n:"Дуу хоолойн AI",d:"Утсаар ярьдаг AI агент. Ашиглалтын төлбөрийг тусад нь тооцно.",r:"Утасны оператор",s:800000,t:{starter:"none",pro:"addon",premium:"addon"},
  k:[["Хүлээн авсан дуудлага","73"],["Дундаж хугацаа","1:12"],["Алдсан дуудлага","0"]],
  f:[["☎ 9911","Цаг захиалсан","1:42"],["☎ 8850","Үнэ асуусан","0:58"],["☎ 9502","Ажилтанд шилжүүлсэн","2:10"],["☎ 9134","Хаяг асуусан","0:31"]]},
 {id:12,ic:"plug",sn:"Интеграц · BI",n:"Захиалгат интеграц ба BI",d:"API/ERP өгөгдлийн холболт, дэвшилтэт BI шинжилгээ, захиалгат урсгал.",r:"Бизнес шинжээч",s:1500000,t:{starter:"none",pro:"addon",premium:"full"},
  k:[["Холбогдсон систем","6"],["Синк","2 мин тутам"],["BI тайлан","14"]],
  f:[["ERP","Барааны үлдэгдэл","Синк ✓"],["Банк","Төлбөрийн тулгалт","Таарсан ✓"],["BI","Салбар хоорондын харьцуулалт","Шинэ"],["Webhook","Хүргэлтийн компани","Төлөв ✓"]]}
];
const MOD = {}; MODS.forEach(m => MOD[m.id] = m);
const TOTAL = MODS.reduce((a, m) => a + m.s, 0);

const TIERS = [
 {k:"starter",tag:"STARTER",n:"AI туслах",d:"Харилцаа, лид, үндсэн цаг захиалга",price:500000,setup:1500000},
 {k:"pro",tag:"PRO",n:"AI автоматжуулалт",d:"Цаг захиалга, төлбөр, CRM, хяналтын самбар",price:1000000,setup:2000000,popular:true},
 {k:"premium",tag:"PREMIUM",n:"Дижитал ажилтан",d:"Захиалгат урсгал, дотоод AI, BI",price:1500000,setup:3000000}
];
const ST = {
 full:{l:"Бүрэн",w:1,c:"full"}, advanced:{l:"Дэвшилтэт",w:1,c:"full"}, custom:{l:"Захиалгат",w:1,c:"full"},
 basic:{l:"Үндсэн",w:.5,c:"half"}, template:{l:"Загвар",w:.3,c:"half"},
 addon:{l:"Нэмэлт",w:0,c:"add"}, none:{l:"—",w:0,c:"none"}
};
/* How data moves between modules (0 = the customer). */
const EDGES = [[0,7],[0,1],[0,11],[7,2],[1,2],[1,3],[11,3],[2,10],[2,4],[2,5],[3,9],[3,12],[4,6],[5,6],[6,8],[12,8],[9,0]];

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const fmt = n => Math.round(n).toLocaleString('en-US') + '₮';
const pad = n => String(n).padStart(2, '0');
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
/* 0 → 1 while a tall section scrolls past its sticky stage */
const progressOf = el => { const r = el.getBoundingClientRect(); return clamp(-r.top / Math.max(1, r.height - innerHeight)); };

function tierStats(k) {
  const t = TIERS.find(x => x.k === k); let roles = 0, value = 0;
  MODS.forEach(m => { const w = ST[m.t[k]].w; if (w > 0) { roles++; value += m.s * w; } });
  return {t, roles, value, save: value - t.price, x: (value / t.price).toFixed(1)};
}
function neighbors(id) {
  const s = new Set();
  EDGES.forEach(([a, b]) => { if (a === id && b) s.add(b); if (b === id && a) s.add(a); });
  return [...s];
}
function countTo(el, to, dur = 700) {
  const from = +el.dataset.v || 0, tok = {}; el._tok = tok; el.dataset.v = to; const t0 = performance.now();
  const step = now => { if (el._tok !== tok) return; const k = ease(clamp((now - t0) / dur)); el.textContent = fmt(lerp(from, to, k)); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function spark(id) {
  const W = 300, H = 90;
  const pts = [...Array(7)].map((_, i) => [i * W / 6, H - 8 - (0.3 + 0.6 * Math.abs(Math.sin(id * 1.3 + i * .8)) * (0.6 + i * .06)) * (H - 20)]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('');
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><defs><linearGradient id="sg${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#4ADE80" stop-opacity=".35"/><stop offset="1" stop-color="#4ADE80" stop-opacity="0"/></linearGradient></defs><path d="${d}L${W},${H}L0,${H}Z" fill="url(#sg${id})"/><path d="${d}" fill="none" stroke="#4ADE80" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

/* The "inside" of a module: the big dashboard every concept opens on click. */
function renderDash(m) {
  const rows = m.f.map((r, i) => `<div class="row" style="animation-delay:${.1 + i * .09}s"><span class="tag">${r[0]}</span><span>${r[1]}</span><span class="ok">${r[2]}</span></div>`).join('');
  const tiers = TIERS.map(t => { const st = ST[m.t[t.k]]; return `<div class="trow"><span>${t.tag}</span><em class="pill st-${st.c}">${st.l}</em></div>`; }).join('');
  const links = neighbors(m.id).map(id => `<button class="chip" data-go="${id}">${icon(MOD[id].ic)}${MOD[id].sn}</button>`).join('');
  return `<div class="dash"><div class="dash-top"><i></i><i></i><i></i><span class="url">app.ajiltai.tech/${m.ic}</span></div>
  <div class="dash-in">
    <div class="dash-head"><div class="dash-ic">${icon(m.ic)}</div>
      <div><div class="eyebrow">Модуль ${pad(m.id)}</div><h3>${m.n}</h3><p>${m.d}</p></div>
      <div class="dash-rep"><span>Орлох ажлын байр</span><b>${m.r}</b><s>${fmt(m.s)}/сар</s></div></div>
    <div class="kpis">${m.k.map(k => `<div class="kpi"><span>${k[0]}</span><b>${k[1]}</b></div>`).join('')}</div>
    <div class="dash-body">
      <div class="panel"><div class="lbl"><i class="live"></i>Шууд урсгал</div>${rows}</div>
      <div class="panel"><div class="lbl">7 хоногийн ачаалал</div>${spark(m.id)}
        <div class="lbl gap">Багц бүрт</div>${tiers}
        ${links ? `<div class="lbl gap">Өгөгдөл солилцдог</div><div class="chips">${links}</div>` : ''}</div>
    </div>
  </div></div>`;
}
const mcard = m => `<button class="mcard" data-id="${m.id}"><span class="no">${pad(m.id)}</span><span class="mi">${icon(m.ic)}</span><b>${m.n}</b><span class="rep"><span>${m.r}</span><s>${fmt(m.s)}</s></span></button>`;

function conceptBar(active) {
  const L = [["index.html","Бүгд"],["a-flow.html","A · Урсгал"],["b-stack.html","B · Давхарга"],["c-day.html","C · Нэг өдөр"]];
  document.body.insertAdjacentHTML('afterbegin', `<nav class="cbar"><span class="logo">ajilt<b>AI</b></span>${L.map(([h, t]) => `<a href="${h}"${h === active ? ' class="on"' : ''}>${t}</a>`).join('')}</nav>`);
}
