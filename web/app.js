/* haggle frontend: vanilla JS, no build step.
 * Consumes the hunt event stream (SSE) and renders: pipeline stepper, requirement chips, listing board,
 * approval panel, parallel negotiation panes and the deal handoff. All state is derived from events,
 * so a reconnect (which replays from seq 0) just dedupes by seq.
 */
(() => {
  "use strict";

  // ------------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (n) => Math.round(Number(n) || 0).toLocaleString("en-US");
  const kr = (n) => `${num(n)} kr`;
  const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  const show = (el, on = true) => el.classList.toggle("hidden", !on);
  const bump = (el, cls = "bump") => { el.classList.remove(cls); void el.offsetWidth; el.classList.add(cls); };
  const fmtGB = (gb) => (gb >= 1000 ? `${+(gb / 1000).toFixed(1)} TB` : `${gb} GB`);
  const clip = (s, n) => (String(s).length > n ? String(s).slice(0, n - 1).trimEnd() + "…" : String(s));
  const fmtClock = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

  const params = new URLSearchParams(location.search);
  const PHASE_STEP = { intake: 0, search: 1, extract: 2, vet: 3, rank: 4, draft: 5, awaiting_approval: 5, negotiate: 6, awaiting_confirmation: 7, done: 8 };
  const PHASE_TEXT = {
    search: "Searching Blocket, Tradera and Facebook Marketplace…",
    extract: "Reading every listing and extracting specs from messy Swedish & English text…",
    vet: "Checking each listing against your requirements and scoring scam risk…",
    rank: "Ranking the survivors…",
    draft: "Drafting an opening message for each shortlisted seller…",
    awaiting_approval: "Waiting for your approval: nothing has been sent",
    negotiate: "Negotiating with sellers in parallel…",
    awaiting_confirmation: "Deals reserved. Pick the one you want.",
    done: "Done.",
  };
  const VLABEL = { type: "PC", gpu: "GPU", ram: "RAM", storage: "SSD", price: "Price", location: "Location", works: "Works" };
  const VORDER = ["type", "gpu", "ram", "storage", "price", "location", "works"];
  const VICON = { pass: "✓", fail: "✗", uncertain: "?" };
  const REJECTED = new Set(["reject"]);
  const LIVE_STATES = new Set(["approved", "negotiating"]);
  const SRC = (s) => (/blocket/i.test(s) ? ["src-blocket", "Blocket"] : /tradera/i.test(s) ? ["src-tradera", "Tradera"] : ["src-fb", "FB Marketplace"]);
  const STATE_LABEL = {
    found: "reading…", extracted: "vetting…", matched: "match", uncertain: "needs a question", scam: "scam", error: "error",
    shortlisted: "shortlisted", approved: "approved", negotiating: "negotiating", deal_offered: "deal reserved",
    seller_declined: "declined", walked_away: "walked away", dropped: "dropped", no_deal: "no deal", confirmed: "confirmed", released: "released",
  };

  // ------------------------------------------------------------------ state
  let S;
  function reset() {
    S = {
      id: null, lastSeq: -1, phase: null, calls: 0, req: null, items: {}, order: [], shortlist: [], drafts: {},
      handoff: null, confirmed: null, t: 0, tWall: 0, panes: {}, approved: false, started: false,
    };
  }
  reset();
  let es = null;

  // ------------------------------------------------------------------ elements
  const E = {
    form: $("#hunt-form"), request: $("#request"), huntBtn: $("#hunt-btn"), echo: $("#request-echo"), replay: $("#replay"),
    stepper: $("#stepper"), status: $("#status"), statusText: $("#status-text"), calls: $("#calls"), callsN: $("#calls-n"), clock: $("#clock"),
    question: $("#question"), qText: $("#question-text"), answerForm: $("#answer-form"), answer: $("#answer"),
    reqs: $("#reqs"), reqChips: $("#req-chips"), reqQueries: $("#req-queries"),
    boardSec: $("#board-sec"), board: $("#board"), rejected: $("#rejected"), rejList: $("#rej-list"), rejN: $("#rej-n"),
    cFound: $("#c-found"), cRej: $("#c-rej"), cScam: $("#c-scam"), cShort: $("#c-short"),
    approval: $("#approval"), drafts: $("#drafts"), approveBtn: $("#approve-btn"),
    nego: $("#nego"), panes: $("#panes"), negoCount: $("#nego-count"), thoughts: $("#thoughts-toggle"),
    handoff: $("#handoff"), savings: $("#savings"), deals: $("#deals"), handoffTitle: $("#handoff-title"),
    error: $("#error"),
  };

  // ------------------------------------------------------------------ api
  async function api(path, body) {
    const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    if (!r.ok) throw new Error((await r.text().catch(() => "")) || r.statusText);
    return r.json();
  }

  function connect(id) {
    if (es) es.close();
    S.id = id;
    es = new EventSource(`/api/hunts/${id}/events?start=${S.lastSeq + 1}`);
    es.onmessage = (m) => {
      let ev;
      try { ev = JSON.parse(m.data); } catch { return; }
      if (typeof ev.seq === "number") {
        if (ev.seq <= S.lastSeq) return; // replayed after reconnect
        S.lastSeq = ev.seq;
      }
      try { handle(ev); } catch (e) { console.error("event failed", ev, e); }
    };
    es.onerror = () => {
      // the browser retries on its own; if it gave up, reconnect from where we were
      if (es.readyState === EventSource.CLOSED) setTimeout(() => S.id === id && connect(id), 1500);
    };
  }

  async function startHunt() {
    const replay = E.replay.checked;
    const request = E.request.value.trim();
    if (!replay && !request) { E.request.focus(); return; }
    E.huntBtn.disabled = true;
    try {
      const { id } = await api("/api/hunts", { request: replay ? "" : request, replay });
      resetUI();
      S.started = true;
      E.echo.textContent = replay ? "Replaying a recorded hunt…" : request;
      document.body.classList.add("running");
      const p = new URLSearchParams(location.search);
      p.set("h", id);
      history.replaceState(null, "", `?${p}`);
      setPhase("intake");
      connect(id);
    } catch (e) {
      showError(`Couldn't start the hunt: ${e.message}`);
    } finally {
      E.huntBtn.disabled = false;
    }
  }

  // ------------------------------------------------------------------ event dispatch
  function handle(ev) {
    if (typeof ev.t === "number") { S.t = ev.t; S.tWall = performance.now(); }
    if (typeof ev.calls === "number") setCalls(ev.calls);
    switch (ev.type) {
      case "status": setStatus(ev.text); break;
      case "phase": setPhase(ev.phase, ev.calls); break;
      case "question": onQuestion(ev.text); break;
      case "requirements": onRequirements(ev.req); break;
      case "found": onFound(ev); break;
      case "listing": onListing(ev); break;
      case "shortlist": onShortlist(ev.ids); break;
      case "draft": onDraft(ev); break;
      case "message": onMessage(ev); break;
      case "guardrail": onGuardrail(ev); break;
      case "handoff": onHandoff(ev); break;
      case "error": showError(ev.message); break;
    }
  }

  // ------------------------------------------------------------------ header: phase, status, calls, clock
  function setCalls(n) {
    if (typeof n !== "number" || n <= S.calls) return; // monotonic (replay confirm reports 0)
    S.calls = n;
    E.callsN.textContent = n;
    bump(E.calls);
  }

  function setPhase(phase, calls) {
    S.phase = phase;
    setCalls(calls);
    const step = PHASE_STEP[phase] ?? 0;
    [...E.stepper.children].forEach((li, i) => {
      li.classList.toggle("done", i < step || phase === "done");
      li.classList.toggle("active", i === step && !phase.startsWith("awaiting") && phase !== "done");
      li.classList.toggle("waiting", i === step && phase.startsWith("awaiting"));
    });
    if (phase === "negotiate") {
      const n = Object.values(S.items).filter((it) => it.state === "approved" || it.state === "negotiating").length;
      setStatus(n ? `Negotiating with ${n} sellers in parallel…` : PHASE_TEXT.negotiate);
    } else if (PHASE_TEXT[phase]) setStatus(PHASE_TEXT[phase]);
    E.status.classList.toggle("idle", phase.startsWith("awaiting") || phase === "done");

    if (phase === "awaiting_approval") openApproval();
    if (phase === "negotiate") closeApproval();
    if (phase === "awaiting_confirmation" || phase === "done") renderHandoff();
    if (phase !== "intake") show(E.question, false);
  }

  function setStatus(text) {
    show(E.status, true);
    E.statusText.innerHTML = `<span class="status-text-in">${esc(text)}</span>`;
  }

  setInterval(() => {
    if (!S.started) return;
    const live = S.phase && !S.phase.startsWith("awaiting") && S.phase !== "done";
    const t = S.t + (live ? (performance.now() - S.tWall) / 1000 : 0);
    show(E.clock, true);
    E.clock.textContent = fmtClock(Math.max(0, t));
  }, 250);

  // ------------------------------------------------------------------ question + requirements
  function onQuestion(text) {
    E.qText.textContent = text;
    show(E.question, true);
    E.answer.value = "";
    setTimeout(() => E.answer.focus(), 50);
    scrollToEl(E.question);
  }

  function onRequirements(req) {
    S.req = req;
    const chips = [];
    if (req.budget_max_sek) chips.push(["Budget", `≤ ${kr(req.budget_max_sek)}`]);
    if (req.target_price_sek) chips.push(["Target", `~${kr(req.target_price_sek)}`]);
    if (req.gpu_min) chips.push(["GPU", `${req.gpu_min}+`]);
    if (req.ram_gb_min) chips.push(["RAM", `${req.ram_gb_min} GB+`]);
    if (req.storage_gb_min) chips.push(["Storage", `${fmtGB(req.storage_gb_min)}${req.storage_ssd_required ? " SSD" : ""}`]);
    if (req.city || req.shipping_ok) chips.push(["Where", [req.city, req.shipping_ok ? "shipping" : ""].filter(Boolean).join(" / ")]);
    if (req.used_ok) chips.push(["Condition", "used OK"]);
    E.reqChips.innerHTML = chips.map(([k, v], i) => `<span class="req-chip" style="animation-delay:${i * 70}ms"><span class="k">${esc(k)}</span>${esc(v)}</span>`).join("");
    const qs = req.search_queries || [];
    E.reqQueries.innerHTML = qs.length ? `<span>Searching for</span>` + qs.map((q, i) => `<span class="q" style="animation-delay:${300 + i * 60}ms">${esc(q)}</span>`).join("") : "";
    show(E.reqs, true);
  }

  // ------------------------------------------------------------------ listing board
  function onFound(ev) {
    const it = S.items[ev.id] || (S.items[ev.id] = { id: ev.id, state: "found" });
    it.listing = ev.listing;
    if (!S.order.includes(ev.id)) S.order.push(ev.id);
    show(E.boardSec, true);
    renderCard(ev.id);
    updateCounters();
  }

  function onListing(ev) {
    const it = S.items[ev.id] || (S.items[ev.id] = { id: ev.id, state: "found" });
    const prev = it.state;
    for (const [k, v] of Object.entries(ev)) {
      if (k === "seq" || k === "t" || k === "type" || v === undefined || v === null) continue;
      it[k] = v;
    }
    renderCard(ev.id, prev);
    updateCounters();
    if (S.panes[ev.id] || LIVE_STATES.has(it.state)) updatePane(ev.id, prev);
    if (S.handoff) renderHandoff();
  }

  function onShortlist(ids) {
    S.shortlist = ids;
    ids.forEach((id) => renderCard(id));
    updateCounters();
  }

  function cardOrder(it) {
    const rank = S.shortlist.indexOf(it.id);
    if (rank >= 0) return rank;
    const base = { matched: 100, uncertain: 200, scam: 300, error: 500 }[it.state] ?? 400;
    return base + S.order.indexOf(it.id) / 1000;
  }

  function mainFail(it) {
    const v = it.verdicts || {};
    for (const k of VORDER) if (v[k]?.status === "fail") return `${VLABEL[k]}: ${v[k].reason}`;
    return it.reason || "doesn't match your requirements";
  }

  function specsLine(sp) {
    if (!sp) return "";
    const unk = (s) => `<span class="unk">${s}</span>`;
    const parts = [
      sp.gpu ? esc(sp.gpu) + (sp.gpu_is_laptop_variant ? " (laptop)" : "") : unk("GPU ?"),
      sp.cpu ? esc(sp.cpu) : null,
      sp.ram_gb > 0 ? `${sp.ram_gb} GB` : unk("RAM ?"),
      sp.ssd_gb > 0 ? `${fmtGB(sp.ssd_gb)} SSD` : sp.hdd_gb > 0 ? unk(`${fmtGB(sp.hdd_gb)} HDD`) : sp.storage_type_unclear_gb > 0 ? unk(`${fmtGB(sp.storage_type_unclear_gb)} ?`) : unk("storage ?"),
    ].filter(Boolean);
    return parts.join(" · ");
  }

  function riskColor(r) { return r >= 60 ? "var(--red)" : r >= 25 ? "var(--amber)" : "var(--green)"; }

  function renderCard(id, prevState) {
    const it = S.items[id];
    if (!it || !it.listing) return;
    const l = it.listing;

    // rejects leave the board and collapse into the "Rejected" group
    if (REJECTED.has(it.state)) {
      const card = document.getElementById(`card-${id}`);
      if (card && !card.classList.contains("leaving")) {
        card.classList.add("leaving");
        setTimeout(() => card.remove(), 450);
      }
      if (!document.getElementById(`rej-${id}`)) {
        E.rejList.prepend(h(`<li id="rej-${esc(id)}"><span class="t">${esc(l.title)}</span><span class="p">${kr(l.price_sek)}</span><span class="why">✗ ${esc(mainFail(it))}</span></li>`));
        show(E.rejected, true);
        bump(E.rejected);
      } else {
        $(".why", document.getElementById(`rej-${id}`)).textContent = `✗ ${mainFail(it)}`;
      }
      return;
    }

    let card = document.getElementById(`card-${id}`);
    if (!card) {
      const [cls, name] = SRC(l.source);
      card = h(`<article class="card" id="card-${esc(id)}">
        <div class="card-top"><span class="src ${cls}">${name}</span><span class="state-tag"></span></div>
        <div class="card-title" title="${esc(l.title)}">${esc(l.title)}</div>
        <div class="card-meta"><span class="price">${kr(l.price_sek)}</span><span class="loc">📍 ${esc(l.location)}${l.shipping ? " · ships" : ""}</span></div>
        <div class="specs hidden"></div>
        <div class="vchips"></div>
        <div class="vreason"></div>
        <ul class="scam-reasons hidden"></ul>
        <div class="risk hidden"><span>risk</span><span class="risk-bar"><i></i></span><span class="risk-n"></span></div>
      </article>`);
      card.addEventListener("click", (e) => {
        const chip = e.target.closest(".vchip");
        if (!chip) return;
        card.querySelectorAll(".vchip.sel").forEach((c) => c !== chip && c.classList.remove("sel"));
        chip.classList.toggle("sel");
        $(".vreason", card).textContent = chip.classList.contains("sel") ? chip.dataset.reason : "";
      });
      card.style.animationDelay = `${(S.order.indexOf(id) % 8) * 40}ms`;
      E.board.appendChild(card);
    }

    // state classes
    card.className = card.className.split(" ").filter((c) => !c.startsWith("st-")).join(" ") + ` st-${it.state}`;
    if (S.shortlist.includes(id)) card.classList.add("ranked");
    card.style.order = String(Math.round(cardOrder(it) * 1000));
    const busy = it.state === "found" || it.state === "extracted";
    $(".state-tag", card).innerHTML = `${busy ? '<span class="spin"></span>' : ""}${esc(STATE_LABEL[it.state] || it.state)}`;

    // extracted specs
    if (it.specs) { const sp = $(".specs", card); sp.innerHTML = specsLine(it.specs); show(sp, true); }

    // verdict chips
    if (it.verdicts) {
      const vc = $(".vchips", card);
      const sig = JSON.stringify(it.verdicts);
      if (vc.dataset.sig !== sig) {
        vc.dataset.sig = sig;
        vc.innerHTML = VORDER.filter((k) => it.verdicts[k]).map((k, i) => {
          const v = it.verdicts[k];
          return `<button type="button" class="vchip ${esc(v.status)}" style="animation-delay:${i * 45}ms" title="${esc(v.reason)}" data-reason="${esc(`${VLABEL[k]}: ${v.reason}`)}">${VICON[v.status] || "·"} ${VLABEL[k]}</button>`;
        }).join("");
      }
    }

    // risk meter
    if (typeof it.risk === "number") {
      const r = $(".risk", card);
      show(r, true);
      const bar = $("i", r);
      requestAnimationFrame(() => { bar.style.width = `${Math.max(3, it.risk)}%`; bar.style.background = riskColor(it.risk); });
      $(".risk-n", r).textContent = it.risk;
      $(".risk-n", r).style.color = riskColor(it.risk);
    }

    // scam stamp + reasons
    if (it.state === "scam") {
      if (!$(".stamp", card)) card.appendChild(h(`<div class="stamp">SCAM RISK ${esc(it.risk ?? "")}</div>`));
      const ul = $(".scam-reasons", card);
      ul.innerHTML = (it.risk_reasons || []).slice(0, 4).map((r) => `<li>${esc(r)}</li>`).join("");
      show(ul, true);
    }

    // rank ribbon for shortlisted
    const rank = S.shortlist.indexOf(id);
    if (rank >= 0) {
      let rb = $(".rank", card);
      if (!rb) {
        rb = h(`<div class="rank"></div>`);
        card.classList.add("ranked");
        card.appendChild(rb);
        bump(card, "shortlist-in");
      }
      rb.textContent = `#${rank + 1}${it.score != null ? ` · ${Math.round(it.score)}` : ""}`;
    }
  }

  function updateCounters() {
    const all = Object.values(S.items).filter((it) => it.listing);
    const set = (el, n) => { if (el.textContent !== String(n)) { el.textContent = n; bump(el.parentElement); } };
    set(E.cFound, all.length);
    const rej = all.filter((it) => REJECTED.has(it.state)).length;
    set(E.cRej, rej);
    E.rejN.textContent = rej;
    set(E.cScam, all.filter((it) => it.state === "scam").length);
    set(E.cShort, S.shortlist.length);
  }

  // ------------------------------------------------------------------ approval
  function onDraft(ev) {
    S.drafts[ev.id] = ev;
    show(E.approval, true);
    E.approveBtn.disabled = S.phase !== "awaiting_approval";
    if (S.phase !== "awaiting_approval") E.approveBtn.textContent = "Drafting…";
    const it = S.items[ev.id] || {};
    const l = it.listing || {};
    let d = document.getElementById(`draft-${ev.id}`);
    const html = `<label class="draft" id="draft-${esc(ev.id)}">
      <div class="draft-head"><input type="checkbox" checked data-id="${esc(ev.id)}"><span class="tt">${esc(l.title || ev.id)}</span><span class="ask-p">${l.price_sek ? kr(l.price_sek) : ""}</span></div>
      <div class="draft-msg">${esc(ev.message)}</div>
      <div class="draft-foot">${ev.offer_sek ? `<span class="offer-pill">Opening offer ${kr(ev.offer_sek)}</span>` : `<span class="offer-pill ask-q">Asks a question first</span>`}<span class="muted">${esc(SRC(l.source || "")[1])} · ${esc(l.seller?.name || "")}</span></div>
      ${ev.private_thoughts ? `<p class="thought"><span class="tl">agent's reasoning</span>${esc(ev.private_thoughts)}</p>` : ""}
    </label>`;
    if (d) d.replaceWith(h(html)); else E.drafts.appendChild(h(html));
    // keep the shortlist order
    S.shortlist.forEach((id) => { const n = document.getElementById(`draft-${id}`); if (n) E.drafts.appendChild(n); });
    updateApproveBtn();
  }

  function selectedIds() { return [...E.drafts.querySelectorAll("input[type=checkbox]:checked")].map((c) => c.dataset.id); }
  function updateApproveBtn() {
    if (S.phase !== "awaiting_approval") return;
    const n = selectedIds().length;
    E.approveBtn.disabled = n === 0;
    E.approveBtn.textContent = n ? `Approve & send ${n} message${n > 1 ? "s" : ""}` : "Select at least one seller";
  }
  E.drafts.addEventListener("change", (e) => {
    const cb = e.target.closest("input[type=checkbox]");
    if (cb) cb.closest(".draft").classList.toggle("off", !cb.checked);
    updateApproveBtn();
  });

  function openApproval() {
    show(E.approval, true);
    E.approval.classList.remove("sent");
    $(".lock-note", E.approval).textContent = "🔒 Nothing has been sent yet";
    updateApproveBtn();
    scrollToEl(E.approval);
  }

  function closeApproval() {
    if (E.approval.classList.contains("hidden")) return;
    E.approval.classList.add("sent");
    const n = Object.values(S.items).filter((it) => it.state === "approved" || it.state === "negotiating").length || selectedIds().length;
    $(".lock-note", E.approval).textContent = `✓ Approved: ${n || ""} opening message${n === 1 ? "" : "s"} sent`;
  }

  E.approveBtn.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length || !S.id) return;
    E.approveBtn.disabled = true;
    E.approveBtn.textContent = "Sending…";
    try { await api(`/api/hunts/${S.id}/approve`, { ids }); S.approved = true; }
    catch (e) { showError(`Approve failed: ${e.message}`); updateApproveBtn(); }
  });

  // ------------------------------------------------------------------ negotiation panes
  function ensurePane(id) {
    if (S.panes[id]) return S.panes[id];
    const it = S.items[id] || { id };
    const l = it.listing || {};
    const [cls, name] = SRC(l.source || "");
    const el = h(`<div class="pane" id="pane-${esc(id)}">
      <div class="pane-head">
        <div class="pane-row"><span class="src ${cls}">${name}</span><span class="badge neg">negotiating</span></div>
        <div class="pane-title" title="${esc(l.title)}">${esc(l.title || id)}</div>
        <div class="pane-sub"><span>asking <b class="mono askv">${kr(l.price_sek)}</b></span><span>· ${esc(l.seller?.name || "")}</span></div>
        <div class="ticker">
          <div class="tick-nums"><span class="you">you <b class="tb">–</b></span><span class="them">seller <b class="ts">${kr(l.price_sek)}</b></span></div>
          <div class="track2"><span class="gap"></span><span class="askmk"></span><span class="cap"></span><span class="mk s"></span><span class="mk b hidden"></span></div>
        </div>
      </div>
      <div class="chat"></div>
    </div>`);
    E.panes.appendChild(el);
    const pane = { el, chat: $(".chat", el), buyer: null, seller: l.price_sek || null, typing: null };
    S.panes[id] = pane;
    show(E.nego, true);
    const n = Object.keys(S.panes).length;
    E.negoCount.textContent = `· ${n} seller${n > 1 ? "s" : ""} in parallel`;
    E.panes.style.setProperty("--n", n);
    if (n === 1) scrollToEl(E.nego);
    updateTicker(id);
    return pane;
  }

  function nearBottom(chat) { return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120; }
  function appendChat(pane, node) {
    const stick = nearBottom(pane.chat);
    if (pane.typing) { pane.typing.remove(); pane.typing = null; }
    pane.chat.appendChild(node);
    if (stick) requestAnimationFrame(() => { pane.chat.scrollTop = pane.chat.scrollHeight; });
  }
  function setTyping(id, who) {
    const pane = S.panes[id];
    if (!pane) return;
    if (pane.typing) { pane.typing.remove(); pane.typing = null; }
    const st = S.items[id]?.state;
    if (!who || !LIVE_STATES.has(st)) return;
    pane.typing = h(`<div class="typing ${who === "buyer" ? "buyer-t" : ""}"><i></i><i></i><i></i></div>`);
    const stick = nearBottom(pane.chat);
    pane.chat.appendChild(pane.typing);
    if (stick) pane.chat.scrollTop = pane.chat.scrollHeight;
  }

  function onMessage(ev) {
    const pane = ensurePane(ev.id);
    const role = ev.role === "seller" ? "seller" : "buyer";
    const rel = ev.action === "release";
    const accept = ev.action === "accept";
    const who = role === "buyer" ? (rel ? "your agent · release" : "your agent") : esc(S.items[ev.id]?.listing?.seller?.name || "seller");
    const pill = ev.price_sek ? `<span class="ppill ${accept ? "accept" : ""}">${accept ? "✓ " : ""}${kr(ev.price_sek)}</span>` : "";
    const act = ev.action && !["offer", "counter", "reply", "release"].includes(ev.action) ? `<span class="act">${esc(ev.action.replace(/_/g, " "))}</span>` : "";
    const node = h(`<div class="msg ${role} ${rel ? "release" : ""}">
      <span class="who">${who}</span>
      <div class="bubble">${esc(ev.text)}</div>
      ${pill || act ? `<div>${pill}${act}</div>` : ""}
      ${ev.thoughts ? `<div class="thought"><span class="tl">🧠 ${role}'s private thoughts</span>${esc(ev.thoughts)}</div>` : ""}
      ${(ev.checks && ev.checks.length) ? `<div class="checks">🛡️ ${ev.checks.map(c => `<span>✓ ${esc(c)}</span>`).join("")}</div>` : ""}
    </div>`);
    appendChat(pane, node);
    if (ev.price_sek && !rel) {
      if (role === "buyer") pane.buyer = ev.price_sek; else pane.seller = ev.price_sek;
      updateTicker(ev.id, role);
    }
    if (!rel) setTyping(ev.id, role === "buyer" ? "seller" : "buyer");
  }

  function onGuardrail(ev) {
    const pane = ensurePane(ev.id);
    const meta = {
      budget_cap: ["Budget cap enforced", ""],
      false_claim: ["False claim blocked", ""],
      message_limit: ["Message limit reached", "amber"],
    }[ev.rule] || [String(ev.rule || "guardrail").replace(/_/g, " "), ""];
    appendChat(pane, h(`<div class="guard ${meta[1]}"><span class="shield">🛡️</span><div><b>${esc(meta[0])} · enforced in code</b>${esc(ev.detail)}</div></div>`));
    bump(pane.el, "guard-hit");
  }

  function updateTicker(id, flashRole) {
    const pane = S.panes[id];
    const it = S.items[id] || {};
    const ask = it.listing?.price_sek || pane.seller || 0;
    const cap = S.req?.budget_max_sek || 0;
    const tb = $(".tb", pane.el), ts = $(".ts", pane.el);
    tb.textContent = pane.buyer ? kr(pane.buyer) : "–";
    ts.textContent = pane.seller ? kr(pane.seller) : "–";
    if (flashRole) bump(flashRole === "buyer" ? tb : ts, "flash");
    const vals = [ask, cap, pane.buyer, pane.seller].filter((v) => v > 0);
    if (!vals.length) return;
    const lo = Math.min(...vals) * 0.9, hi = Math.max(...vals) * 1.04;
    const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
    const tr = $(".track2", pane.el);
    const mb = $(".mk.b", tr), ms = $(".mk.s", tr), gap = $(".gap", tr), capEl = $(".cap", tr), askEl = $(".askmk", tr);
    if (cap) { capEl.style.left = pos(cap); capEl.dataset.l = `max ${num(cap)}`; } else capEl.remove();
    askEl.style.left = pos(ask);
    if (pane.seller) ms.style.left = pos(pane.seller);
    if (pane.buyer) { show(mb, true); mb.style.left = pos(pane.buyer); }
    if (pane.buyer && pane.seller) {
      const a = Math.min(pane.buyer, pane.seller), b = Math.max(pane.buyer, pane.seller);
      gap.style.left = pos(a); gap.style.width = `${((b - a) / (hi - lo)) * 100}%`;
    } else gap.style.width = "0";
  }

  function updatePane(id, prev) {
    const pane = ensurePane(id);
    const it = S.items[id];
    const badge = $(".badge", pane.el);
    const st = it.state;
    const set = (cls, txt) => { badge.className = `badge ${cls}`; badge.textContent = txt; };
    pane.el.classList.toggle("is-deal", st === "deal_offered" || st === "confirmed");
    pane.el.classList.toggle("is-dead", ["walked_away", "dropped", "seller_declined", "no_deal", "released"].includes(st));
    if (st === "approved" || st === "negotiating") set("neg", "negotiating");
    else if (st === "deal_offered") set("b-deal", `DEAL ${kr(it.deal?.price_sek)}`);
    else if (st === "confirmed") set("gold", `★ CONFIRMED ${kr(it.deal?.price_sek)}`);
    else if (st === "walked_away") set("bad", "walked away");
    else if (st === "dropped") set("bad", "dropped");
    else if (st === "seller_declined") set("bad", "declined");
    else if (st === "no_deal") set("meh", "no deal");
    else if (st === "released") set("meh", "released");

    if (st !== prev) {
      const sys = {
        deal_offered: () => ["good", `🤝 Deal at ${kr(it.deal?.price_sek)} · reserved pending your confirmation`],
        confirmed: () => ["good", "★ You confirmed this deal"],
        walked_away: () => ["bad", `Walked away${it.reason ? `: ${clip(it.reason, 130)}` : ""}`],
        dropped: () => ["bad", `Dropped${it.reason ? `: ${it.reason}` : ""}`],
        seller_declined: () => ["bad", "Seller declined"],
        no_deal: () => ["bad", `No deal${it.reason ? `: ${it.reason}` : ""}`],
        released: () => ["", "Seller released politely"],
      }[st];
      if (sys) {
        const [cls, txt] = sys();
        appendChat(pane, h(`<div class="sys ${cls}">${esc(txt)}</div>`));
      }
      if (!LIVE_STATES.has(st)) setTyping(id, null);
      if (st === "deal_offered" && it.deal?.price_sek) { pane.buyer = pane.seller = it.deal.price_sek; updateTicker(id); }
    }
  }

  E.thoughts.addEventListener("change", () => document.body.classList.toggle("hide-thoughts", !E.thoughts.checked));

  // ------------------------------------------------------------------ handoff
  function onHandoff(ev) {
    S.handoff = ev;
    setCalls(ev.calls);
    renderHandoff();
    scrollToEl(E.handoff);
  }

  function renderHandoff() {
    if (!S.handoff) return;
    show(E.handoff, true);
    const ids = S.handoff.ids || [];
    const best = S.handoff.best;
    const confirmed = Object.values(S.items).find((it) => it.state === "confirmed");
    const all = Object.values(S.items).filter((it) => it.listing);
    const nego = Object.keys(S.panes).length;
    const released = Object.values(S.items).filter((it) => it.state === "released").length;
    const focus = confirmed || S.items[best];
    const saved = focus?.deal?.saved_sek || 0;
    const pct = focus?.deal?.asking_sek ? Math.round((saved / focus.deal.asking_sek) * 100) : 0;

    if (!ids.length) {
      E.savings.innerHTML = `<div><div class="big" style="color:var(--amber)">No deal yet</div><div class="lbl">None of the sellers agreed within your limits. Your agent didn't overpay.</div></div>`;
    } else {
      E.savings.innerHTML = `<div><div class="big">${kr(saved)}</div><div class="lbl">${confirmed ? `You saved ${pct}% vs the asking price` : `saved vs asking on the recommended deal (${pct}%)`}</div></div>
        <div class="stats">
          <div class="stat"><b>${all.length}</b><span>listings read</span></div>
          <div class="stat"><b>${all.filter((x) => x.state === "scam").length}</b><span>scams caught</span></div>
          <div class="stat"><b>${nego}</b><span>sellers haggled</span></div>
          <div class="stat"><b>${S.calls}</b><span>Gemini calls</span></div>
          <div class="stat"><b>${fmtClock(S.t)}</b><span>start to deal</span></div>
        </div>`;
    }
    E.handoffTitle.textContent = confirmed ? "Done" : ids.length ? `${ids.length} deal${ids.length > 1 ? "s" : ""} reserved: pick one` : "Your deals";

    const sorted = [...ids].sort((a, b) => (a === best ? -1 : b === best ? 1 : 0));
    E.deals.innerHTML = "";
    if (confirmed) {
      const others = released ? `Your agent politely released the other ${released} seller${released > 1 ? "s" : ""}.` : "";
      E.deals.appendChild(h(`<div class="success"><div class="ok">🎉</div><h3>Deal confirmed: ${esc(confirmed.listing.title)} for ${kr(confirmed.deal?.price_sek)}</h3><p>${esc(confirmed.deal?.logistics ? `Logistics: ${confirmed.deal.logistics}. ` : "")}${others}</p></div>`));
    }
    sorted.forEach((id, i) => {
      const it = S.items[id];
      if (!it?.listing) return;
      const d = it.deal || {};
      const isBest = id === best;
      const chosen = confirmed && confirmed.id === id;
      const card = h(`<div class="deal ${isBest && !confirmed ? "best" : ""} ${chosen ? "chosen" : ""} ${confirmed && !chosen ? "faded" : ""}" style="animation-delay:${i * 90}ms">
        ${isBest && !confirmed ? `<span class="ribbon">★ Recommended</span>` : ""}
        <div class="tt">${esc(it.listing.title)}</div>
        <div class="specs">${specsLine(it.specs)}</div>
        <div class="prices"><span class="final">${kr(d.price_sek)}</span><span class="was">${kr(d.asking_sek || it.listing.price_sek)}</span></div>
        <div class="saved">saved ${kr(d.saved_sek || 0)}</div>
        <div class="logi">📍 ${esc(d.logistics || it.listing.location)} · ${esc(SRC(it.listing.source)[1])} · ${esc(it.listing.seller?.name || "")}</div>
        ${chosen ? `<span class="done-badge">✓ Confirmed</span>` : confirmed ? `<span class="released">${it.state === "released" ? "Released politely" : ""}</span>` : `<button class="btn ${isBest ? "btn-primary" : ""}" data-confirm="${esc(id)}">Confirm this one</button>`}
      </div>`);
      E.deals.appendChild(card);
    });
  }

  E.deals.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-confirm]");
    if (!b || !S.id) return;
    E.deals.querySelectorAll("[data-confirm]").forEach((x) => (x.disabled = true));
    b.textContent = "Confirming…";
    try { await api(`/api/hunts/${S.id}/confirm`, { id: b.dataset.confirm }); confetti(); }
    catch (err) { showError(`Confirm failed: ${err.message}`); E.deals.querySelectorAll("[data-confirm]").forEach((x) => (x.disabled = false)); }
  });

  function confetti() {
    const box = h(`<div class="confetti"></div>`);
    const colors = ["#22c55e", "#7c5cff", "#22d3ee", "#f59e0b", "#f43f5e", "#fff"];
    for (let i = 0; i < 90; i++) {
      const p = document.createElement("i");
      p.style.left = `${Math.random() * 100}%`;
      p.style.background = colors[i % colors.length];
      p.style.animationDuration = `${1.8 + Math.random() * 1.8}s`;
      p.style.animationDelay = `${Math.random() * 0.4}s`;
      p.style.transform = `rotate(${Math.random() * 360}deg)`;
      box.appendChild(p);
    }
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 4200);
  }

  // ------------------------------------------------------------------ misc
  function showError(msg) {
    E.error.textContent = `⚠ ${msg}`;
    show(E.error, true);
  }

  let scrollTimer = null;
  function scrollToEl(el) {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 250);
  }

  function resetUI() {
    if (es) es.close();
    reset();
    E.board.innerHTML = ""; E.rejList.innerHTML = ""; E.drafts.innerHTML = ""; E.panes.innerHTML = ""; E.deals.innerHTML = "";
    E.reqChips.innerHTML = ""; E.reqQueries.innerHTML = ""; E.callsN.textContent = "0";
    [E.question, E.reqs, E.boardSec, E.rejected, E.approval, E.nego, E.handoff, E.error].forEach((el) => show(el, false));
    E.approval.classList.remove("sent");
    updateCounters();
  }

  E.form.addEventListener("submit", (e) => { e.preventDefault(); startHunt(); });
  E.request.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); startHunt(); } });
  E.answerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = E.answer.value.trim();
    if (!text || !S.id) return;
    try { await api(`/api/hunts/${S.id}/answer`, { text }); show(E.question, false); setStatus("Thanks, continuing…"); }
    catch (err) { showError(`Couldn't send the answer: ${err.message}`); }
  });

  // replay toggle: ?replay=1 or the footer checkbox
  E.replay.checked = params.get("replay") === "1";
  const syncReplay = () => {
    E.request.readOnly = E.replay.checked;
    E.form.classList.toggle("is-replay", E.replay.checked);
    if (E.replay.checked) E.request.value = "I want a gaming PC for under 8,000 SEK. At least an RTX 3060 or equivalent, 16 GB RAM, 1 TB SSD. Pickup in Stockholm or shipping. Used is fine.";
  };
  E.replay.addEventListener("change", () => {
    syncReplay();
    const p = new URLSearchParams(location.search);
    if (E.replay.checked) p.set("replay", "1"); else p.delete("replay");
    history.replaceState(null, "", p.toString() ? `?${p}` : location.pathname);
  });
  syncReplay();
  const autosize = () => { E.request.style.height = "auto"; E.request.style.height = `${E.request.scrollHeight}px`; };
  E.request.addEventListener("input", autosize);
  E.replay.addEventListener("change", autosize);
  window.addEventListener("resize", autosize);
  requestAnimationFrame(autosize);

  // resume a hunt after a page reload (?h=<id>)
  const resume = params.get("h");
  if (resume) {
    api(`/api/hunts/${resume}`).then((snap) => {
      S.started = true;
      document.body.classList.add("running");
      E.echo.textContent = snap?.request || "Replaying a recorded hunt…";
      connect(resume);
    }).catch(() => {
      params.delete("h");
      history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
    });
  }

  // tiny debug hook for testing in the console
  window.__haggle = { state: () => S, handle };
})();
