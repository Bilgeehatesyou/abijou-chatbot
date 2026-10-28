// Demo chat page: talks to /api/chat exactly like the website widget would.
(() => {
  const log = document.getElementById("log");
  const chips = document.getElementById("chips");
  const form = document.getElementById("form");
  const input = document.getElementById("input");

  const newSession = () => "demo" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  let session;
  try { session = localStorage.getItem("abijou-session") || newSession(); } catch { session = newSession(); }
  const remember = () => { try { localStorage.setItem("abijou-session", session); } catch {} };
  remember();

  function bubble(text, who) {
    const el = document.createElement("div");
    el.className = "msg " + who;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function showChips(replies) {
    chips.innerHTML = "";
    for (const q of replies) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = q.title;
      b.onclick = () => send(q.payload, q.title);
      chips.appendChild(b);
    }
  }

  async function send(message, shown) {
    if (shown) bubble(shown, "me");
    chips.innerHTML = "";
    const typing = bubble("…", "bot typing");
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session, message }),
      });
      typing.remove();
      if (!r.ok) { bubble(r.status === 429 ? "Too many messages, please wait a little." : "Error " + r.status, "bot"); return; }
      const data = await r.json();
      let last = [];
      for (const m of data.messages) {
        if (m.text) bubble(m.text, "bot");
        if (m.quick_replies && m.quick_replies.length) last = m.quick_replies;
      }
      showChips(last);
    } catch (e) {
      typing.remove();
      bubble("Connection error.", "bot");
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    send(text, text);
  });

  document.getElementById("restart").onclick = () => {
    session = newSession();
    remember();
    log.innerHTML = "";
    send("GET_STARTED");
  };

  send("GET_STARTED");
})();
