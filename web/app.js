/* haggle frontend: vanilla JS, no build step.
 * Consumes the hunt event stream (SSE) and renders: pipeline steps, requirements line, listing ledger,
 * outbox (approval), parallel negotiation transcripts and the deal receipts. All state is derived from
 * events, so a reconnect (which replays from seq 0) just dedupes by seq.
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
  const fmtAge = (d) => (d == null ? "" : d < 14 ? `${d} day${d === 1 ? "" : "s"}` : d < 60 ? `${Math.round(d / 7)} wk` : d < 730 ? `${Math.round(d / 30)} mo` : `${Math.round(d / 365)} yr`);

  const params = new URLSearchParams(location.search);
  const PHASE_STEP = { intake: 0, search: 1, extract: 2, vet: 3, rank: 4, draft: 5, awaiting_approval: 5, negotiate: 6, awaiting_confirmation: 7, done: 8 };
  const PHASE_TEXT = {
    search: "Searching Blocket, Tradera and Facebook Marketplace",
    extract: "Reading every listing, extracting specs from messy Swedish and English text",
    vet: "Checking each listing against your requirements, scoring scam risk",
    rank: "Ranking what's left",
    draft: "Drafting an opening message to each shortlisted seller",
    awaiting_approval: "Waiting for your approval. Nothing has been sent.",
    negotiate: "Negotiating with sellers in parallel",
    awaiting_confirmation: "Deals reserved. Pick the one you want.",
    done: "Done.",
  };
  const VLABEL = { type: "Type", gpu: "GPU", ram: "RAM", storage: "SSD", price: "Price", location: "Location", works: "Works" };
  const VORDER = ["type", "gpu", "ram", "storage", "price", "location", "works"];
  const MARKS = ["type", "gpu", "ram", "storage", "price", "location"]; // ledger columns
  const VICON = { pass: "✓", fail: "✗", uncertain: "?" };
  const REJECTED = new Set(["reject"]);
  const LIVE_STATES = new Set(["approved", "negotiating"]);
  const DEAD_STATES = new Set(["walked_away", "dropped", "seller_declined", "no_deal", "released"]);
  const SRC = (s) => (/blocket/i.test(s) ? ["src-blocket", "Blocket"] : /tradera/i.test(s) ? ["src-tradera", "Tradera"] : ["src-fb", "Facebook"]);
  const STATE_LABEL = {
    found: "reading…", extracted: "vetting…", matched: "match", uncertain: "unclear, will ask", scam: "scam", error: "error", reject: "rejected",
    shortlisted: "shortlisted", approved: "approved", negotiating: "negotiating…", deal_offered: "deal reserved",
    seller_declined: "declined", walked_away: "walked away", dropped: "dropped", no_deal: "no deal", confirmed: "confirmed", released: "released",
  };
  const ACT = { offer: "offers", counter: "counters", accept: "accepts", reply: "", ask: "asks", walk_away: "walks away", decline: "declines", release: "releases" };

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
      autosize();
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
      case "watch": onWatch(ev); break;
      case "watch_hit": onWatchHit(ev); break;
      case "error": showError(ev.message); break;
    }
  }

  // ------------------------------------------------------------------ header: phase, status, calls, clock
  function setCalls(n) {
    if (typeof n !== "number" || n <= S.calls) return; // monotonic (replay confirm reports 0)
    S.calls = n;
    E.callsN.textContent = n;
  }

  function setPhase(phase, calls) {
    S.phase = phase;
    setCalls(calls);
    const step = PHASE_STEP[phase] ?? 0;
    [...E.stepper.children].forEach((li, i) => {
      const done = i < step || phase === "done";
      li.classList.toggle("done", done);
      li.classList.toggle("active", i === step && !phase.startsWith("awaiting") && phase !== "done");
      li.classList.toggle("waiting", i === step && phase.startsWith("awaiting"));
      $(".n", li).textContent = done ? "✓" : String(i + 1).padStart(2, "0");
    });
    const cur = E.stepper.children[Math.min(step, 7)];
    if (cur && E.stepper.scrollWidth > E.stepper.clientWidth) E.stepper.scrollLeft = Math.max(0, cur.offsetLeft - E.stepper.offsetLeft - 40);
    if (phase === "negotiate") {
      const n = Object.values(S.items).filter((it) => it.state === "approved" || it.state === "negotiating").length;
      setStatus(n ? `Negotiating with ${n} sellers in parallel` : PHASE_TEXT.negotiate);
    } else if (PHASE_TEXT[phase]) setStatus(PHASE_TEXT[phase]);
    E.status.classList.toggle("idle", phase.startsWith("awaiting") || phase === "done");

    if (phase === "awaiting_approval") openApproval();
    if (phase === "negotiate") closeApproval();
    if (phase === "awaiting_confirmation" || phase === "done") renderHandoff();
    if (phase !== "intake") show(E.question, false);
  }

  function setStatus(text) {
    show(E.status, true);
    E.statusText.textContent = String(text).replace(/…$/, "");
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
    const parts = [];
    if (req.budget_max_sek) parts.push(`Budget <b class="mono">≤ ${kr(req.budget_max_sek)}</b>${req.target_price_sek ? ` <span class="muted">(aiming for ~${num(req.target_price_sek)})</span>` : ""}`);
    if (req.gpu_min) parts.push(`${esc(req.gpu_min)} or better`);
    if (req.ram_gb_min) parts.push(`${req.ram_gb_min} GB RAM`);
    if (req.storage_gb_min) parts.push(`${fmtGB(req.storage_gb_min)}${req.storage_ssd_required ? " SSD" : " storage"}`);
    if (req.city || req.shipping_ok) parts.push([req.city, req.shipping_ok ? "shipping" : ""].filter(Boolean).join(" or "));
    if (req.used_ok) parts.push("used is fine");
    E.reqChips.innerHTML = parts.map((p) => `<span class="req">${p}</span>`).join('<span class="sep"> · </span>');
    const qs = req.search_queries || [];
    E.reqQueries.innerHTML = qs.length ? `<span class="muted">Searching for </span><span class="mono q">${qs.map(esc).join(", ")}</span>` : "";
    show(E.reqs, true);
  }

  // ------------------------------------------------------------------ listing ledger
  function onFound(ev) {
    const it = S.items[ev.id] || (S.items[ev.id] = { id: ev.id, state: "found" });
    it.listing = ev.listing;
    if (ev.new) it.isNew = true;
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
    E.board.classList.add("has-short");
    if (!$("#grp-short", E.board)) {
      E.board.appendChild(h(`<div class="grp" id="grp-short" style="order:-1">Shortlist, ranked</div>`));
      E.board.appendChild(h(`<div class="grp" id="grp-rest" style="order:99000">Also considered</div>`));
    }
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

  function riskClass(r) { return r >= 60 ? "r-hi" : r >= 25 ? "r-mid" : "r-lo"; }

  function renderCard(id) {
    const it = S.items[id];
    if (!it || !it.listing) return;
    const l = it.listing;
    const rejected = REJECTED.has(it.state);

    let card = document.getElementById(`card-${id}`);
    if (!card) {
      const [cls, name] = SRC(l.source);
      const age = l.seller?.account_age_days;
      const sub = [esc(l.location), l.shipping ? "ships" : "", age != null ? `seller ${fmtAge(age)}` : ""].filter(Boolean).join(" · ");
      card = h(`<div class="lrow item" id="card-${esc(id)}">
        <span class="c-n mono"></span>
        <span class="c-src ${cls}">${name}</span>
        <span class="c-title">
          <span class="t" title="${esc(l.title)}">${it.isNew ? `<span class="newtag mono">new</span> ` : ""}${esc(l.title)}</span>
          <span class="sub">${sub}</span>
          <span class="specs mono hidden"></span>
          <span class="why"></span>
          <span class="scam-why hidden"></span>
        </span>
        <span class="c-ask mono">${kr(l.price_sek)}</span>
        <span class="c-marks">${MARKS.map(() => `<i class="mk none">·</i>`).join("")}</span>
        <span class="c-risk mono"></span>
        <span class="c-st"></span>
      </div>`);
      card.addEventListener("click", (e) => {
        const mk = e.target.closest("button.mk");
        if (!mk) return;
        card.querySelectorAll("button.mk.sel").forEach((c) => c !== mk && c.classList.remove("sel"));
        mk.classList.toggle("sel");
        const cur = S.items[id];
        $(".why", card).textContent = mk.classList.contains("sel") ? mk.dataset.reason : REJECTED.has(cur.state) ? mainFail(cur) : "";
      });
      card.style.animationDelay = `${(S.order.indexOf(id) % 10) * 25}ms`;
    }

    // rejects leave the board and collapse into the "Rejected" group
    const home = rejected ? E.rejList : E.board;
    if (card.parentElement !== home) {
      home.appendChild(card);
      if (rejected) show(E.rejected, true);
    }

    card.className = card.className.split(" ").filter((c) => !c.startsWith("st-")).join(" ") + ` st-${it.state}`;
    const rank = S.shortlist.indexOf(id);
    card.classList.toggle("ranked", rank >= 0);
    card.style.order = rejected ? String(S.order.indexOf(id)) : String(Math.round(cardOrder(it) * 1000));

    // number column: rank for the shortlist, otherwise blank
    $(".c-n", card).innerHTML = rank >= 0 ? `<b>${rank + 1}</b>${it.score != null ? `<small>${Math.round(it.score)}</small>` : ""}` : "";

    // status
    const st = $(".c-st", card);
    st.textContent = STATE_LABEL[it.state] || it.state;
    st.className = `c-st ${it.state === "found" || it.state === "extracted" ? "busy mono" : ""}`;
    if (it.state === "deal_offered" || it.state === "confirmed") st.innerHTML = `<span class="money">${it.state === "confirmed" ? "confirmed" : "deal"} ${kr(it.deal?.price_sek)}</span>`;

    if (it.specs) { const sp = $(".specs", card); sp.innerHTML = specsLine(it.specs); show(sp, true); }

    // verdict marks
    if (it.verdicts) {
      const vc = $(".c-marks", card);
      const sig = JSON.stringify(it.verdicts);
      if (vc.dataset.sig !== sig) {
        vc.dataset.sig = sig;
        vc.innerHTML = MARKS.map((k) => {
          const v = it.verdicts[k];
          if (!v) return `<i class="mk none">·</i>`;
          return `<button type="button" class="mk ${esc(v.status)}" title="${esc(`${VLABEL[k]}: ${v.reason}`)}" data-reason="${esc(`${VLABEL[k]}: ${v.reason}`)}" aria-label="${esc(`${VLABEL[k]} ${v.status}: ${v.reason}`)}">${VICON[v.status] || "·"}</button>`;
        }).join("");
      }
    }
    const why = $(".why", card);
    if (rejected && !card.querySelector("button.mk.sel")) why.textContent = mainFail(it);

    // risk
    if (typeof it.risk === "number") {
      $(".c-risk", card).innerHTML = `<span class="rbar ${riskClass(it.risk)}"><i style="width:${Math.max(4, it.risk)}%"></i></span><span class="rn ${riskClass(it.risk)}">${it.risk}</span>`;
    }

    // scam stamp + reasons
    if (it.state === "scam") {
      if (!$(".stamp", card)) $(".c-title", card).appendChild(h(`<span class="stamp scam" aria-label="Scam">Scam</span>`));
      const sw = $(".scam-why", card);
      sw.textContent = (it.risk_reasons || []).slice(0, 3).join(" · ");
      show(sw, true);
    }
  }

  function updateCounters() {
    const all = Object.values(S.items).filter((it) => it.listing);
    const set = (el, n) => { if (el.textContent !== String(n)) el.textContent = n; };
    set(E.cFound, all.length);
    const rej = all.filter((it) => REJECTED.has(it.state)).length;
    set(E.cRej, rej);
    E.rejN.textContent = rej;
    set(E.cScam, all.filter((it) => it.state === "scam").length);
    set(E.cShort, S.shortlist.length);
  }

  // ------------------------------------------------------------------ approval (outbox)
  function onDraft(ev) {
    S.drafts[ev.id] = ev;
    if (S.items[ev.id]?.isNew) { renderWatchHit(ev.id); return; }
    show(E.approval, true);
    E.approveBtn.disabled = S.phase !== "awaiting_approval";
    if (S.phase !== "awaiting_approval") E.approveBtn.textContent = "Drafting…";
    const it = S.items[ev.id] || {};
    const l = it.listing || {};
    const d = document.getElementById(`draft-${ev.id}`);
    const offer = ev.offer_sek
      ? `<span class="muted">Asking ${kr(l.price_sek)}</span> <span class="arr">→</span> opening offer <b class="money">${kr(ev.offer_sek)}</b>`
      : `<span class="muted">Asking ${kr(l.price_sek)}</span> <span class="arr">→</span> asks a question first`;
    const html = `<label class="draft" id="draft-${esc(ev.id)}">
      <input type="checkbox" checked data-id="${esc(ev.id)}">
      <div class="draft-body">
        <div class="draft-to mono">To <b>${esc(l.seller?.name || "seller")}</b> · ${esc(SRC(l.source || "")[1])}</div>
        <div class="draft-title">${esc(l.title || ev.id)}</div>
        <div class="draft-offer mono">${offer}</div>
        <blockquote class="draft-msg">${esc(ev.message)}</blockquote>
        ${ev.private_thoughts ? `<p class="thought"><span class="tl">reasoning:</span> ${esc(ev.private_thoughts)}</p>` : ""}
      </div>
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
    E.approveBtn.textContent = n ? `Send ${n} message${n > 1 ? "s" : ""}` : "Select at least one seller";
  }
  E.drafts.addEventListener("change", (e) => {
    const cb = e.target.closest("input[type=checkbox]");
    if (cb) cb.closest(".draft").classList.toggle("off", !cb.checked);
    updateApproveBtn();
  });

  function openApproval() {
    show(E.approval, true);
    E.approval.classList.remove("sent");
    $(".lock-note", E.approval).textContent = "Nothing is sent until you approve.";
    updateApproveBtn();
    scrollToEl(E.approval);
  }

  function closeApproval() {
    if (E.approval.classList.contains("hidden")) return;
    E.approval.classList.add("sent");
    const n = Object.values(S.items).filter((it) => it.state === "approved" || it.state === "negotiating").length || selectedIds().length;
    $(".lock-note", E.approval).textContent = `✓ Approved by you. ${n || ""} opening message${n === 1 ? "" : "s"} sent.`;
  }

  E.approveBtn.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length || !S.id) return;
    E.approveBtn.disabled = true;
    E.approveBtn.textContent = "Sending…";
    try { await api(`/api/hunts/${S.id}/approve`, { ids }); S.approved = true; }
    catch (e) { showError(`Approve failed: ${e.message}`); updateApproveBtn(); }
  });

  // ------------------------------------------------------------------ watch mode
  const E2 = { watch: $("#watch"), watchState: $("#watch-state"), watchHits: $("#watch-hits"), postTest: $("#post-test") };

  function onWatch(ev) {
    S.watching = !!ev.active;
    show(E2.watch, true);
    E2.watch.classList.toggle("on", S.watching);
    E2.watchState.textContent = S.watching ? `watching · every ${ev.interval || 20} s` : "stopped";
    show(E2.postTest, S.watching && !S.replay);
    if (!S.watching && !E2.watchHits.children.length) show(E2.watch, false);
  }

  function onWatchHit(ev) {
    if (!S.shortlist.includes(ev.id)) S.shortlist.push(ev.id);
    renderCard(ev.id);
    updateCounters();
    renderWatchHit(ev.id, ev.text);
    scrollToEl(E2.watch);
  }

  function renderWatchHit(id, text) {
    const it = S.items[id] || {};
    const l = it.listing || {};
    const d = S.drafts[id];
    if (!d || it.state !== "shortlisted") return;
    show(E2.watch, true);
    const offer = d.offer_sek ? `opening offer <b class="money">${kr(d.offer_sek)}</b>` : "asks a question first";
    const node = h(`<div class="whit" id="whit-${esc(id)}">
      <div class="draft-to mono">New listing · ${esc(SRC(l.source || "")[1])} · ${esc(l.location || "")} · asking ${kr(l.price_sek)} <span class="arr">→</span> ${offer}</div>
      <div class="draft-title">${esc(l.title || id)}</div>
      <blockquote class="draft-msg">${esc(d.message)}</blockquote>
      ${d.private_thoughts ? `<p class="thought"><span class="tl">reasoning:</span> ${esc(d.private_thoughts)}</p>` : ""}
      <div class="whit-act"><button class="btn btn-ink" data-id="${esc(id)}">Approve and negotiate</button><span class="muted small">Vetted: ${esc(it.verdict || "match")}, risk ${it.risk ?? 0}</span></div>
    </div>`);
    const old = document.getElementById(`whit-${id}`);
    if (old) old.replaceWith(node); else E2.watchHits.prepend(node);
  }

  E2.watchHits.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-id]");
    if (!b || !S.id) return;
    b.disabled = true; b.textContent = "Sending…";
    try {
      await api(`/api/hunts/${S.id}/approve`, { ids: [b.dataset.id] });
      const w = b.closest(".whit"); w.classList.add("sent");
      b.replaceWith(h(`<span class="mono small">✓ Approved. Negotiating below.</span>`));
    } catch (err) { showError(`Approve failed: ${err.message}`); b.disabled = false; b.textContent = "Approve and negotiate"; }
  });

  const TEST_LISTINGS = [
    { title: "Speldator RTX 3060 Ti / Ryzen 5 5600 / 16GB / 1TB NVMe", price_sek: 6800, location: "Solna, Stockholm", min_price_sek: 6000,
      description: "Säljer min speldator, funkar perfekt. RTX 3060 Ti, Ryzen 5 5600, 16 GB DDR4, 1 TB NVMe SSD. Hämtas i Solna, kan mötas upp i stan. Pris kan diskuteras lite." },
    { title: "Gaming PC RX 6700 XT, 16GB RAM, 1TB SSD", price_sek: 7400, location: "Nacka, Stockholm", min_price_sek: 6600,
      description: "Selling my gaming PC because I'm moving. RX 6700 XT, Ryzen 5 3600, 16GB RAM, 1TB SSD. Pickup in Nacka, open to reasonable offers." },
  ];
  E2.postTest.addEventListener("click", async () => {
    const t = TEST_LISTINGS[(S.posted = (S.posted || 0) + 1) % TEST_LISTINGS.length];
    E2.postTest.disabled = true;
    try { await api("/api/market/listings", t); setStatus(`Posted “${t.title}” to the marketplace. Your agent will spot it on its next check.`); }
    catch (err) { showError(`Couldn't post: ${err.message}`); }
    finally { setTimeout(() => { E2.postTest.disabled = false; }, 1500); }
  });

  // ------------------------------------------------------------------ negotiation transcripts
  function ensurePane(id) {
    if (S.panes[id]) return S.panes[id];
    const it = S.items[id] || { id };
    const l = it.listing || {};
    const [cls, name] = SRC(l.source || "");
    const el = h(`<article class="pane" id="pane-${esc(id)}">
      <header class="pane-head">
        <div class="pane-meta mono"><span class="${cls}">${name}</span><span>${esc(l.seller?.name || "")}</span></div>
        <h3 class="pane-title" title="${esc(l.title)}">${esc(l.title || id)}</h3>
        <div class="pane-ask">Asking <b class="mono askv">${kr(l.price_sek)}</b></div>
        <div class="ticker">
          <div class="tick-nums mono"><span class="you">you <b class="tb">–</b></span><span class="them">seller <b class="ts">${kr(l.price_sek)}</b></span></div>
          <div class="track2"><span class="rail"></span><span class="gap"></span><span class="askmk"></span><span class="cap"></span><span class="mk s"></span><span class="mk b hidden"></span></div>
        </div>
        <div class="badge neg">negotiating…</div>
      </header>
      <div class="chat"></div>
    </article>`);
    E.panes.appendChild(el);
    const pane = { el, chat: $(".chat", el), buyer: null, seller: l.price_sek || null, typing: null };
    S.panes[id] = pane;
    show(E.nego, true);
    const n = Object.keys(S.panes).length;
    E.negoCount.textContent = `· ${n} seller${n > 1 ? "s" : ""} at once`;
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
    const name = who === "buyer" ? "you" : (S.items[id]?.listing?.seller?.name || "seller");
    pane.typing = h(`<div class="typing ${who === "buyer" ? "buyer-t" : ""}"><span class="mono">${esc(name)}</span><i></i><i></i><i></i></div>`);
    const stick = nearBottom(pane.chat);
    pane.chat.appendChild(pane.typing);
    if (stick) pane.chat.scrollTop = pane.chat.scrollHeight;
  }

  function onMessage(ev) {
    const pane = ensurePane(ev.id);
    const role = ev.role === "seller" ? "seller" : "buyer";
    const rel = ev.action === "release";
    const accept = ev.action === "accept";
    const who = role === "buyer" ? (rel ? "you · release" : "you") : esc(S.items[ev.id]?.listing?.seller?.name || "seller");
    const verb = ACT[ev.action] ?? String(ev.action || "").replace(/_/g, " ");
    const tag = ev.price_sek
      ? `<span class="ptag ${accept ? "accept" : ""}">${verb ? `${esc(verb)} ` : ""}<b>${kr(ev.price_sek)}</b></span>`
      : verb && !rel ? `<span class="ptag act">${esc(verb)}</span>` : "";
    const checks = (ev.checks && ev.checks.length) ? `<p class="checks mono">${ev.checks.map((c) => `<span>✓ ${esc(c)}</span>`).join('<span class="sep"> · </span>')}</p>` : "";
    const node = h(`<div class="msg ${role} ${rel ? "release" : ""}">
      <div class="who mono"><span>${who}</span>${typeof ev.t === "number" ? `<span class="tm">${fmtClock(ev.t)}</span>` : ""}</div>
      <p class="txt">${esc(ev.text)}</p>
      ${tag ? `<div class="tags">${tag}</div>` : ""}
      ${checks}
      ${ev.thoughts ? `<p class="thought"><span class="tl">thinks:</span> ${esc(ev.thoughts)}</p>` : ""}
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
    const name = { budget_cap: "budget cap", false_claim: "false claim blocked", message_limit: "message limit", untrusted_input: "untrusted seller input" }[ev.rule] || String(ev.rule || "guardrail").replace(/_/g, " ");
    appendChat(pane, h(`<div class="rule mono"><b>RULE</b><span>${esc(name)} — ${esc(ev.detail)} <span class="dim">(enforced in code)</span></span></div>`));
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
    const lo = Math.min(...vals) * 0.92, hi = Math.max(...vals) * 1.04;
    const pos = (v) => `${((v - lo) / (hi - lo)) * 100}%`;
    const tr = $(".track2", pane.el);
    const mb = $(".mk.b", tr), ms = $(".mk.s", tr), gap = $(".gap", tr), capEl = $(".cap", tr), askEl = $(".askmk", tr);
    if (cap && capEl) { capEl.style.left = pos(cap); capEl.dataset.l = `max ${num(cap)}`; } else if (capEl) capEl.remove();
    askEl.style.left = pos(ask);
    askEl.dataset.l = `ask`;
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
    pane.el.classList.toggle("is-dead", DEAD_STATES.has(st));
    const why = it.reason ? ` — ${clip(it.reason, 90)}` : "";
    if (st === "approved" || st === "negotiating") set("neg", "negotiating…");
    else if (st === "deal_offered") set("b-deal", `DEAL ${kr(it.deal?.price_sek)}`);
    else if (st === "confirmed") set("b-deal", `CONFIRMED ${kr(it.deal?.price_sek)}`);
    else if (st === "walked_away") set("bad", `walked away${why}`);
    else if (st === "dropped") set("bad", `dropped${why}`);
    else if (st === "seller_declined") set("bad", "seller declined");
    else if (st === "no_deal") set("bad", `no deal${why}`);
    else if (st === "released") set("bad", "released politely");

    if (st !== prev) {
      const sys = {
        deal_offered: () => ["deal", `Deal at ${kr(it.deal?.price_sek)}, reserved until you confirm`],
        confirmed: () => ["deal", "You confirmed this deal"],
        walked_away: () => ["", "Your agent walked away"],
        dropped: () => ["", "Dropped"],
        seller_declined: () => ["", "Seller declined"],
        no_deal: () => ["", "No deal"],
        released: () => ["", "Seller released politely"],
      }[st];
      if (sys) {
        const [cls, txt] = sys();
        appendChat(pane, h(`<div class="sys ${cls}"><span>${esc(txt)}</span></div>`));
      }
      if (!LIVE_STATES.has(st)) setTyping(id, null);
      if (st === "deal_offered" && it.deal?.price_sek) { pane.buyer = pane.seller = it.deal.price_sek; updateTicker(id); }
    }
  }

  E.thoughts.addEventListener("change", () => document.body.classList.toggle("hide-thoughts", !E.thoughts.checked));

  // ------------------------------------------------------------------ handoff (receipts)
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
    const scams = all.filter((x) => x.state === "scam").length;
    const facts = [`${all.length} listings read`, `${scams} scam${scams === 1 ? "" : "s"} avoided`, `${nego} seller${nego === 1 ? "" : "s"}, in parallel`, `${S.calls} Gemini calls`, `${Math.round(S.t)} s`]
      .map((f) => `<span>${f}</span>`).join(" · ");

    if (!ids.length) {
      E.savings.innerHTML = `<p class="save-big"><span class="amt none">No deal yet.</span></p><p class="save-note">None of the sellers agreed within your limits, so your agent didn't overpay.</p><p class="save-facts mono">${facts}</p>`;
    } else {
      E.savings.innerHTML = `<p class="save-big"><span class="lbl">${confirmed ? "You saved" : "Saves you"}</span> <span class="amt">${kr(saved)}</span> <span class="pct mono">${pct}% under asking</span></p>
        <p class="save-facts mono">${facts}</p>
        ${confirmed ? `<p class="save-note">Confirmed: <b>${esc(confirmed.listing.title)}</b> for <span class="money mono">${kr(confirmed.deal?.price_sek)}</span>. ${confirmed.deal?.logistics ? `Handover: ${esc(confirmed.deal.logistics)}. ` : ""}${released ? `Your agent politely released the other ${released} seller${released > 1 ? "s" : ""}.` : ""}</p>` : `<p class="save-note">Nothing is bought until you confirm one. The others are released politely.</p>`}`;
    }
    E.handoffTitle.textContent = confirmed ? "Done" : ids.length ? `${ids.length} deal${ids.length > 1 ? "s" : ""} reserved. Pick one.` : "Your deals";

    const sorted = [...ids].sort((a, b) => (a === best ? -1 : b === best ? 1 : 0));
    E.deals.innerHTML = "";
    sorted.forEach((id, i) => {
      const it = S.items[id];
      if (!it?.listing) return;
      const d = it.deal || {};
      const isBest = id === best;
      const chosen = confirmed && confirmed.id === id;
      const ask = d.asking_sek || it.listing.price_sek;
      const card = h(`<div class="receipt ${isBest && !confirmed ? "best" : ""} ${chosen ? "chosen" : ""} ${confirmed && !chosen ? "faded" : ""}" style="animation-delay:${i * 60}ms">
        <div class="r-top mono"><span>${isBest ? "Recommended" : `Deal ${i + 1}`}</span><span>${esc(SRC(it.listing.source)[1])} · ${esc(id)}</span></div>
        <h3 class="r-title">${esc(it.listing.title)}</h3>
        <div class="r-specs mono">${specsLine(it.specs)}</div>
        <div class="r-rule"></div>
        <div class="r-line mono"><span>Asking</span><span>${kr(ask)}</span></div>
        <div class="r-line mono r-agreed"><span>Agreed</span><span>${kr(d.price_sek)}</span></div>
        <div class="r-rule"></div>
        <div class="r-line mono r-save"><span>You save</span><span>${kr(d.saved_sek || 0)}</span></div>
        <div class="r-rule"></div>
        <div class="r-line mono small"><span>Seller</span><span>${esc(it.listing.seller?.name || "")}</span></div>
        <div class="r-line mono small"><span>Handover</span><span>${esc(d.logistics || it.listing.location)}</span></div>
        <div class="r-act">${chosen ? `<span class="stamp ok">Confirmed</span>` : confirmed ? `<span class="released">${it.state === "released" ? "Released politely" : ""}</span>` : `<button class="btn ${isBest ? "btn-ink" : "btn-line"}" data-confirm="${esc(id)}">Confirm this one</button>`}</div>
      </div>`);
      E.deals.appendChild(card);
    });
  }

  E.deals.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-confirm]");
    if (!b || !S.id) return;
    E.deals.querySelectorAll("[data-confirm]").forEach((x) => (x.disabled = true));
    b.textContent = "Confirming…";
    try { await api(`/api/hunts/${S.id}/confirm`, { id: b.dataset.confirm }); }
    catch (err) { showError(`Confirm failed: ${err.message}`); E.deals.querySelectorAll("[data-confirm]").forEach((x) => (x.disabled = false)); }
  });

  // ------------------------------------------------------------------ misc
  function showError(msg) {
    E.error.textContent = msg;
    show(E.error, true);
  }

  let scrollTimer = null;
  function scrollToEl(el) {
    clearTimeout(scrollTimer);
    const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scrollTimer = setTimeout(() => el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" }), 250);
  }

  function resetUI() {
    if (es) es.close();
    reset();
    E.board.innerHTML = ""; E.board.classList.remove("has-short"); E.rejList.innerHTML = ""; E.drafts.innerHTML = ""; E.panes.innerHTML = ""; E.deals.innerHTML = ""; E.savings.innerHTML = "";
    E.reqChips.innerHTML = ""; E.reqQueries.innerHTML = ""; E.callsN.textContent = "0";
    [E.question, E.reqs, E.boardSec, E.rejected, E.approval, E.nego, E.handoff, E.error].forEach((el) => show(el, false));
    E.approval.classList.remove("sent");
    E.rejected.open = false;
    updateCounters();
  }

  E.form.addEventListener("submit", (e) => { e.preventDefault(); startHunt(); });

  fetch("/api/info").then((r) => r.json()).then((i) => {
    if (i.host_label) $("#hostlbl").innerHTML = ` · running on <b>${esc(i.host_label)}</b> <span class="mono">(${esc(i.hostname)})</span>`;
  }).catch(() => {});

  // ------------------------------------------------------------------ voice input (Gemini 3.5 Transcribe)
  const mic = { btn: $("#mic-btn"), rec: null, chunks: [], t0: 0, timer: null };
  const micLbl = (t) => { $(".mic-lbl", mic.btn).textContent = t; };
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) mic.btn.classList.add("hidden");

  async function micStart() {
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { showError("Microphone blocked. Allow mic access (the page must be https or localhost)."); return; }
    const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    mic.rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    mic.chunks = [];
    mic.rec.ondataavailable = (e) => e.data.size && mic.chunks.push(e.data);
    mic.rec.onstop = () => { stream.getTracks().forEach((t) => t.stop()); micSend(); };
    mic.rec.start();
    mic.t0 = performance.now();
    mic.btn.classList.add("rec");
    micLbl("0:00 · stop");
    mic.timer = setInterval(() => {
      const s = (performance.now() - mic.t0) / 1000;
      micLbl(`${fmtClock(s)} · stop`);
      if (s > 30) micStop();  // keep clips short
    }, 250);
  }

  function micStop() {
    clearInterval(mic.timer);
    mic.btn.classList.remove("rec");
    if (mic.rec && mic.rec.state !== "inactive") mic.rec.stop();
  }

  async function micSend() {
    const blob = new Blob(mic.chunks, { type: mic.rec.mimeType || "audio/webm" });
    mic.rec = null;
    if (blob.size < 1500) { micLbl("Speak"); return; }
    mic.btn.disabled = true; micLbl("Transcribing…");
    try {
      const r = await fetch("/api/transcribe", { method: "POST", headers: { "Content-Type": blob.type }, body: blob });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
      const { text } = await r.json();
      if (!text) throw new Error("didn't catch that");
      E.request.value = text;
      E.request.dispatchEvent(new Event("input"));
      micLbl("Speak");
      setTimeout(() => startHunt(), 700);  // show what was heard, then go
    } catch (e) { showError(`Voice: ${e.message}`); micLbl("Speak"); }
    finally { mic.btn.disabled = false; }
  }

  mic.btn.addEventListener("click", () => (mic.rec ? micStop() : micStart()));
  E.request.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); startHunt(); } });
  E.answerForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = E.answer.value.trim();
    if (!text || !S.id) return;
    try { await api(`/api/hunts/${S.id}/answer`, { text }); show(E.question, false); setStatus("Thanks, continuing"); }
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
  function autosize() { E.request.style.height = "auto"; E.request.style.height = `${E.request.scrollHeight}px`; }
  E.request.addEventListener("input", autosize);
  E.replay.addEventListener("change", autosize);
  window.addEventListener("resize", autosize);
  requestAnimationFrame(autosize);
  if (document.fonts) document.fonts.ready.then(autosize);

  // resume a hunt after a page reload (?h=<id>)
  const resume = params.get("h");
  if (resume) {
    api(`/api/hunts/${resume}`).then((snap) => {
      S.started = true;
      document.body.classList.add("running");
      E.echo.textContent = snap?.request || "Replaying a recorded hunt…";
      if (snap?.request && !E.replay.checked) { E.request.value = snap.request; autosize(); }
      connect(resume);
    }).catch(() => {
      params.delete("h");
      history.replaceState(null, "", params.toString() ? `?${params}` : location.pathname);
    });
  }

  // tiny debug hook for testing in the console
  window.__haggle = { state: () => S, handle };
})();
