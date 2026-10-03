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
    search: "Searching mockbay",
    extract: "Reading every listing, extracting specs from messy Swedish and English text",
    vet: "Checking each listing against your requirements, scoring scam risk",
    rank: "Ranking what's left",
    draft: "Drafting an opening message to each shortlisted seller",
    awaiting_approval: "Waiting for your approval. Nothing has been sent.",
    negotiate: "Negotiating with sellers in parallel",
    awaiting_confirmation: "Deals reserved. Pick the one you want.",
    done: "Done.",
    paused: "Restored after restart. Resume to review fresh drafts.",
    error: "This hunt needs attention. Review the error and resume when ready.",
  };
  const VLABEL = { type: "Type", gpu: "GPU", ram: "RAM", storage: "Storage", attributes: "Details", condition: "Condition", price: "Price", location: "Location", works: "Works" };
  const verdictLabel = (key, value) => value?.label || VLABEL[key] || key;
  const MARKS = ["type", "attributes", "condition", "works", "price", "location"]; // ledger columns
  // listing photo (mockbay's real photos; stock PC photo for the local dataset). Hidden if it fails to load.
  const ph = (l, cls) => l && l.photo
    ? `<img class="ph ${cls}" src="${esc(l.photo)}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()">` : "";
  const VICON = { pass: "✓", fail: "✗", uncertain: "?", negotiable: "↓" };
  const REJECTED = new Set(["reject"]);
  const LIVE_STATES = new Set(["approved", "negotiating"]);
  const DEAD_STATES = new Set(["walked_away", "dropped", "seller_declined", "no_deal", "released"]);
  const SRC = (s) => (/mockbay/i.test(s) ? ["src-mockbay", "mockbay"] : /blocket/i.test(s) ? ["src-blocket", "Blocket"] : /tradera/i.test(s) ? ["src-tradera", "Tradera"] : /facebook/i.test(s) ? ["src-fb", "Facebook"] : ["src-other", String(s || "marketplace")]);
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
    status: $("#status"), statusText: $("#status-text"), calls: $("#calls"), clock: $("#clock"), barFill: $("#bar-fill"), work: $("#work"),
    question: $("#question"), qText: $("#question-text"), answerForm: $("#answer-form"), answer: $("#answer"),
    reqs: $("#reqs"), reqChips: $("#req-chips"),
    boardSec: $("#board-sec"), board: $("#board"), rejected: $("#rejected"), rejList: $("#rej-list"), rejN: $("#rej-n"),
    cFound: $("#c-found"), cRej: $("#c-rej"), cScam: $("#c-scam"), cShort: $("#c-short"),
    picks: $("#picks"), picksTitle: $("#picks-title"), picksSub: $("#picks-sub"), moreBtn: $("#more-btn"), sendBar: $("#send-bar"), sendNote: $("#send-note"), approveBtn: $("#approve-btn"), allSum: $("#all-sum"),
    nego: $("#nego"), panes: $("#panes"), threads: $("#threads"), negoCount: $("#nego-count"), thoughts: $("#thoughts-toggle"),
    handoff: $("#handoff"), savings: $("#savings"), deals: $("#deals"), handoffTitle: $("#handoff-title"),
    error: $("#error"),
  };

  // ------------------------------------------------------------------ views: home → best fits → negotiation
  // One view on screen at a time. "Negotiation" unlocks once you message a seller; both stay clickable after,
  // and a tab whose view changed while you were elsewhere gets a dot.
  const tabs = [...document.querySelectorAll("#tabs [data-go]")];
  let view = "home", negoOpen = false;
  function setView(v) {
    if (v === "nego" && !negoOpen) return;
    const moved = v !== view;
    view = v;
    document.body.dataset.view = v;
    tabs.forEach((b) => {
      b.disabled = b.dataset.go === "nego" && !negoOpen;
      b.classList.toggle("on", b.dataset.go === v);
      if (b.dataset.go === v) { b.setAttribute("aria-current", "page"); b.classList.remove("ping"); } else b.removeAttribute("aria-current");
    });
    if (moved) window.scrollTo({ top: 0 });
  }
  function openNego() {
    if (negoOpen) return;
    negoOpen = true;
    setView("nego");
  }
  function ping(v) { const b = tabs.find((t) => t.dataset.go === v); if (b && v !== view && !b.disabled) b.classList.add("ping"); }
  tabs.forEach((b) => b.addEventListener("click", () => setView(b.dataset.go)));

  // ------------------------------------------------------------------ api
  async function api(path, body) {
    const r = await fetch(path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    if (r.status === 401) { location.href = `/login?next=${encodeURIComponent(location.pathname + location.search)}`; throw new Error("Sign in required"); }
    if (!r.ok) {
      const t = await r.text().catch(() => "");
      let msg = t;
      try { msg = JSON.parse(t).detail || t; } catch {}
      throw new Error(msg || r.statusText);
    }
    return r.json();
  }

  // browser mode: poll the agent's live browser view (only shown when the server drives mockbay in a browser)
  let abTimer = null, abLast = 0;
  function watchBrowser(id) {
    clearInterval(abTimer);
    $("#agent-browser").classList.add("hidden");
    abLast = 0;
    abTimer = setInterval(async () => {
      if (S.id !== id) return clearInterval(abTimer);
      try {
        const r = await fetch(`/api/hunts/${id}/browser`);
        if (!r.ok) return;
        const b = await r.json();
        if (!b.active || b.t === abLast) return;
        abLast = b.t;
        $("#ab-label").textContent = b.label;
        $("#ab-img").src = `/api/hunts/${id}/browser.jpg?t=${b.t}`;
        $("#agent-browser").classList.remove("hidden");
      } catch { /* ignore */ }
    }, 1500);
  }

  function connect(id) {
    if (es) es.close();
    S.id = id;
    watchBrowser(id);
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
    es.onerror = async () => {
      // Is the hunt still there? (A server restart wipes hunts; don't retry a dead one forever.)
      try {
        const r = await fetch(`/api/hunts/${id}`);
        if (r.ok) {
          const snap = await r.json();
          if (snap.closed && es) { es.close(); es = null; return; }
        }
        if (r.status === 404) {
          es.close(); es = null;
          history.replaceState(null, "", location.pathname + (E.replay.checked ? "?replay=1" : ""));
          onNotice("This hunt is no longer on the server (it was restarted). Press Hunt to start a new one.");
          E.huntBtn.disabled = false; document.body.classList.remove("running");
          return;
        }
      } catch { /* server unreachable: let the browser keep retrying */ }
      if (es && es.readyState === EventSource.CLOSED) setTimeout(() => S.id === id && connect(id), 1500);
    };
  }

  // Watchdog: a server restart wipes hunts. If ours is gone, say so instead of retrying a dead stream.
  setInterval(async () => {
    if (!S.id || !S.started || S.gone) return;
    try {
      const r = await fetch(`/api/hunts/${S.id}`);
      if (r.status !== 404) return;
      S.gone = true;
      if (es) { es.close(); es = null; }
      history.replaceState(null, "", location.pathname + (E.replay.checked ? "?replay=1" : ""));
      onNotice("This hunt is no longer on the server (haggle was restarted). Press Hunt to start a new one.");
      E.huntBtn.disabled = false;
      document.body.classList.remove("running");
    } catch { /* server down for a moment: keep waiting */ }
  }, 4000);

  // ------------------------------------------------------------------ clarifying questions (before the hunt)
  // The hunt itself never asks: questions happen here (or in the agent's chat via the skill / MCP).
  const CQ = { el: $("#clarify"), qs: $("#clarify-qs"), sum: $("#clarify-sum"), form: $("#clarify-form"), list: [], request: "" };
  function hideClarify() { CQ.el.classList.add("hidden"); CQ.list = []; }
  function showClarify(request, res) {
    CQ.request = request; CQ.list = res.questions;
    CQ.sum.textContent = res.summary || "";
    CQ.qs.innerHTML = res.questions.map((q, i) => `<div class="cq">
      <label class="cq-q" for="cq-${i}">${esc(q.question)}</label>
      <div class="cq-opts">${(q.options || []).map((o) => `<button type="button" class="chip" data-q="${i}">${esc(o)}</button>`).join("")}</div>
      <input id="cq-${i}" type="text" placeholder="Or type your answer"></div>`).join("");
    CQ.el.classList.remove("hidden");
    setTimeout(() => $("#cq-0")?.focus(), 50);
  }
  CQ.qs.addEventListener("click", (e) => {
    const c = e.target.closest(".chip"); if (!c) return;
    const i = c.dataset.q;
    CQ.qs.querySelectorAll(`.chip[data-q="${i}"]`).forEach((x) => x.classList.toggle("on", x === c));
    $(`#cq-${i}`).value = c.textContent;
  });
  CQ.form.addEventListener("submit", (e) => {
    e.preventDefault();
    const answers = CQ.list.map((q, i) => ({ question: q.question, answer: $(`#cq-${i}`).value.trim() })).filter((a) => a.answer);
    const request = CQ.request;
    hideClarify();
    launch(request, { answers, clarified: true });
  });
  $("#clarify-skip").addEventListener("click", () => { const r = CQ.request; hideClarify(); launch(r, { clarified: true }); });

  async function startHunt(opts = {}) {
    const replay = E.replay.checked;
    const request = E.request.value.trim();
    if (!replay && !request) { E.request.focus(); return; }
    hideClarify();
    if (replay || opts.clarified) return launch(request, opts);
    E.huntBtn.disabled = true;
    const label = E.huntBtn.innerHTML;
    E.huntBtn.textContent = "Thinking…";  // the landing page has no status line
    setStatus("Checking what I need to know…");
    try {
      const res = await api("/api/clarify", { request });
      if (res.questions && res.questions.length) { showClarify(request, res); setStatus("A few questions first"); return; }
    } catch (e) {
      if (/limit|budget|Too many/i.test(e.message)) { showError(e.message); return; }
      // clarify unavailable: don't block the hunt
    } finally {
      E.huntBtn.disabled = false;
      E.huntBtn.innerHTML = label;
    }
    launch(request, { clarified: true });
  }

  async function launch(request, opts = {}) {
    const replay = E.replay.checked;
    E.huntBtn.disabled = true;
    try {
      const { id } = await api("/api/hunts", { request: replay ? "" : request, replay, answers: opts.answers || [], clarified: !!opts.clarified });
      resetUI();
      setView("results");
      S.started = true; S.gone = false;
      E.echo.textContent = replay ? "Replaying a recorded hunt…" : request;
      document.body.classList.add("running");
      autosize();
      const p = new URLSearchParams(location.search);
      p.delete("q"); p.delete("go");  // a deep link starts one hunt, not one per reload
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
      case "notice": onNotice(ev.text); break;
      case "watch_hit": onWatchHit(ev); break;
      case "error": showError(ev.message); break;
      case "complete": if (es) { es.close(); es = null; } break;
    }
  }

  // ------------------------------------------------------------------ header: phase, status, calls, clock
  function setCalls(n) {
    if (typeof n !== "number" || n <= S.calls) return; // monotonic (replay confirm reports 0)
    S.calls = n;  // kept for the record; the user sees what the agent did, not API calls (see meter())
  }

  // header meter: progress in the user's terms ("40 listings read · 22 ruled out" / "Talking to 5 sellers")
  function meter() {
    const all = Object.values(S.items).filter((it) => it.listing);
    const talking = all.filter((it) => LIVE_STATES.has(it.state) || S.panes[it.id]).length;
    const deals = all.filter((it) => it.state === "deal_offered" || it.state === "confirmed").length;
    const scams = all.filter((it) => it.state === "scam").length;
    const rej = all.filter((it) => REJECTED.has(it.state)).length;
    let text = "Starting…";
    if (talking) text = `Talking to ${talking} seller${talking === 1 ? "" : "s"}` + (deals ? ` · ${deals} deal${deals === 1 ? "" : "s"} so far` : "");
    else if (all.length) text = `${all.length} listings read` + (rej ? ` · ${rej} ruled out` : "") + (scams ? ` · ${scams} scam${scams === 1 ? "" : "s"} caught` : "");
    if (E.calls.textContent !== text) E.calls.textContent = text;
  }

  function setPhase(phase, calls) {
    S.phase = phase;
    setCalls(calls);
    const step = PHASE_STEP[phase] ?? 0;
    E.barFill.style.width = `${Math.min(100, ((step + (phase.startsWith("awaiting") || phase === "done" ? 1 : 0.5)) / 6) * 100)}%`;
    // the progress strip is for the search; once there's something to choose, it gets out of the way
    E.work.classList.toggle("quiet", step >= 5);
    if (phase === "negotiate") {
      const n = Object.values(S.items).filter((it) => it.state === "approved" || it.state === "negotiating").length;
      setStatus(n ? `Negotiating with ${n} sellers in parallel` : PHASE_TEXT.negotiate);
    } else if (PHASE_TEXT[phase]) setStatus(PHASE_TEXT[phase]);
    E.status.classList.toggle("idle", phase.startsWith("awaiting") || phase === "done");

    if (phase === "awaiting_approval") updateApproveBtn();
    if (phase === "negotiate" || phase === "awaiting_confirmation" || phase === "done") { if (!negoOpen) openNego(); updateApproveBtn(); }
    if (phase === "awaiting_confirmation" || phase === "done") renderHandoff();
    if (phase !== "intake") show(E.question, false);
    let resume = document.getElementById("resume-hunt");
    if (!resume) {
      resume = document.createElement("button"); resume.id = "resume-hunt";
      resume.className = "btn btn-line"; resume.textContent = "Resume hunt";
      E.status.appendChild(resume);
      resume.onclick = async () => {
        resume.disabled = true;
        try { await api(`/api/hunts/${S.id}/resume`, {}); }
        catch (e) { showError(e.message); }
        finally { resume.disabled = false; }
      };
    }
    show(resume, phase === "paused" || phase === "error");
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
    if (req.gpu_min) parts.push(`${esc(req.gpu_min)}${req.gpu_allow_equivalent ? " or better" : " (exact model)"}`);
    if (req.ram_gb_min) parts.push(`${req.ram_gb_min} GB RAM`);
    if (req.storage_gb_min) parts.push(`${fmtGB(req.storage_gb_min)}${req.storage_ssd_required ? " SSD" : ""}`);
    for (const a of req.attributes || []) parts.push(esc(a.label));
    if (req.budget_max_sek) parts.push(`under <b class="mono">${kr(req.budget_max_sek)}</b>`);
    if (req.city) parts.push(`near ${esc(req.city)}${req.shipping_ok ? " or shipped" : ""}`);
    E.reqChips.innerHTML = parts.join('<span class="sep"> · </span>');
    show(E.reqs, parts.length > 0);
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
    if (prev !== it.state && S.shortlist.includes(ev.id)) { renderPick(ev.id); updateApproveBtn(); }
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
    renderPicks();
  }

  function cardOrder(it) {
    const rank = S.shortlist.indexOf(it.id);
    if (rank >= 0) return rank;
    const base = { matched: 100, uncertain: 200, scam: 300, error: 500 }[it.state] ?? 400;
    return base + S.order.indexOf(it.id) / 1000;
  }

  function mainFail(it) {
    const v = it.verdicts || {};
    for (const [k, value] of Object.entries(v)) if (value.status === "fail") return `${verdictLabel(k, value)}: ${value.reason}`;
    return it.reason || "doesn't match your requirements";
  }

  function specsLine(sp) {
    if (!sp) return "";
    const unk = (s) => `<span class="unk">${s}</span>`;
    const req = S.req || {};
    const parts = [
      sp.gpu ? esc(sp.gpu) + (sp.gpu_is_laptop_variant ? " (laptop)" : "") : req.gpu_min ? unk("GPU ?") : null,
      sp.cpu ? esc(sp.cpu) : null,
      sp.ram_gb > 0 ? `${sp.ram_gb} GB RAM` : req.ram_gb_min ? unk("RAM ?") : null,
      sp.ssd_gb > 0 ? `${fmtGB(sp.ssd_gb)} SSD` : sp.hdd_gb > 0 ? `${fmtGB(sp.hdd_gb)} HDD` : sp.storage_type_unclear_gb > 0 ? `${fmtGB(sp.storage_type_unclear_gb)} storage` : req.storage_gb_min ? unk("storage ?") : null,
    ].filter(Boolean);
    for (const rule of req.attributes || []) {
      const fact = (sp.attributes || []).find((f) => f.key === rule.key);
      if (fact?.known) parts.push(esc(fact.value || `${fact.number} ${fact.unit || ""}`));
      else parts.push(unk(esc(rule.label) + " ?"));
    }
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
        <span class="c-title ${l.photo ? "has-ph" : ""}">${ph(l, "thumb")}
          <span class="t" title="${esc(l.title)}">${it.isNew ? `<span class="newtag mono">new</span> ` : ""}${l.url ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title)}</a>` : esc(l.title)}</span>
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
    const onlyPrice = it.state === "uncertain" && it.verdicts &&
      Object.values(it.verdicts).every((v) => v.status === "pass" || v.status === "negotiable");
    st.textContent = onlyPrice ? "over budget, negotiable" : (STATE_LABEL[it.state] || it.state);
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
          let v = it.verdicts[k];
          if (k === "attributes") {
            const details = Object.entries(it.verdicts).filter(([key]) => key.startsWith("attr_") || ["gpu", "ram", "storage"].includes(key));
            if (details.length) v = {status: details.some(([, x]) => x.status === "fail") ? "fail" : details.some(([, x]) => x.status === "uncertain") ? "uncertain" : "pass",
              reason: details.map(([key, x]) => `${verdictLabel(key, x)}: ${x.reason}`).join("; ")};
          }
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
    const scams = all.filter((it) => it.state === "scam").length;
    E.allSum.textContent = `See all ${all.length} listings we checked` + (scams ? ` · ${scams} scam${scams === 1 ? "" : "s"} avoided` : "");
    meter();
  }

  // ------------------------------------------------------------------ best fits (picks) + approval
  // The shortlist as cards: the top 3 up front, the rest behind "Show more". Tick the sellers to message,
  // then one button sends. Sellers you skip can still be messaged later (the server allows it mid-negotiation).
  const TOP = 3;
  const picked = new Set();
  let showAll = false;

  function onDraft(ev) {
    S.drafts[ev.id] = ev;
    ping("results");
    if (S.items[ev.id]?.isNew) { renderWatchHit(ev.id); return; }
    renderPick(ev.id);
    updateApproveBtn();
  }

  function renderPicks() {
    E.picks.innerHTML = "";
    const ids = S.shortlist.filter((id) => !S.items[id]?.isNew);
    if (!ids.length) return;
    ids.forEach((id, i) => { if (i < TOP && !S.touched) picked.add(id); renderPick(id); });
    E.picksTitle.textContent = ids.length === 1 ? "Your best fit" : `Your ${Math.min(TOP, ids.length)} best fits`;
    const all = Object.values(S.items).filter((it) => it.listing).length;
    E.picksSub.textContent = `Out of ${all} listings, these are the closest fits. Check any unanswered requirements before choosing. Pick who your agent should message.`;
    updateMore();
    show(E.sendBar, true);
    updateApproveBtn();
  }

  function updateMore() {
    const extra = S.shortlist.filter((id) => !S.items[id]?.isNew).length - TOP;
    show(E.moreBtn, extra > 0);
    E.moreBtn.textContent = showAll ? "Show fewer" : `Show ${extra} more option${extra === 1 ? "" : "s"}`;
    E.picks.classList.toggle("show-all", showAll);
  }
  E.moreBtn.addEventListener("click", () => { showAll = !showAll; updateMore(); });

  function riskWord(r) { return r >= 60 ? ["high", "r-hi"] : r >= 25 ? ["some", "r-mid"] : ["low", "r-lo"]; }

  function renderPick(id) {
    const rank = S.shortlist.filter((x) => !S.items[x]?.isNew).indexOf(id);
    if (rank < 0) return;
    const it = S.items[id] || {};
    const l = it.listing || {};
    const d = S.drafts[id];
    const st = it.state;
    const sent = st && st !== "shortlisted";
    const on = picked.has(id);
    const v = it.verdicts || {};
    const checks = Object.keys(v).map((k) => `<li class="${esc(v[k].status)}" title="${esc(v[k].reason)}">${VICON[v[k].status] || ""} ${esc(verdictLabel(k, v[k]))}</li>`).join("");
    const [rw, rc] = riskWord(it.risk ?? 0);
    const offer = d?.offer_sek ? `Opens at <b class="money mono">${kr(d.offer_sek)}</b>` : d ? "Asks a question first" : `<span class="muted">Writing a message…</span>`;
    let action;
    if (sent) action = `<button type="button" class="pick-go" data-view-nego>✓ Messaged · see the chat</button>`;
    else action = `<button type="button" class="pick-sel ${on ? "on" : ""}" data-pick="${esc(id)}" aria-pressed="${on}" ${d ? "" : "disabled"}>${on ? "✓ Will message" : "Message this seller"}</button>`;
    const node = h(`<article class="pick ${rank >= TOP ? "extra" : ""} ${on && !sent ? "on" : ""} ${sent ? "sent" : ""}" id="pick-${esc(id)}" style="animation-delay:${(rank % TOP) * 70}ms">
      ${ph(l, "pick-ph")}
      <div class="pick-top mono"><span class="${rank === 0 ? "best" : ""}">${rank === 0 ? "Best fit" : `#${rank + 1}`}</span><span>${esc(l.location || "")}</span></div>
      <h3 class="pick-title">${l.url ? `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.title || id)}</a>` : esc(l.title || id)}</h3>
      <p class="pick-specs mono">${specsLine(it.specs)}</p>
      <p class="pick-price"><span class="ask mono">${kr(l.price_sek)}</span><span class="offer">${offer}</span></p>
      <ul class="pick-checks">${checks}<li class="risk ${rc}">${rw} risk</li></ul>
      ${d ? `<details class="pick-msg"><summary>Read the opening message</summary><blockquote>${esc(d.message)}</blockquote></details>` : ""}
      ${action}
    </article>`);
    const old = document.getElementById(`pick-${id}`);
    if (old) old.replaceWith(node); else E.picks.appendChild(node);
  }

  E.picks.addEventListener("click", (e) => {
    if (e.target.closest("[data-view-nego]")) { setView("nego"); return; }
    const b = e.target.closest("[data-pick]");
    if (!b || b.disabled) return;
    const id = b.dataset.pick;
    S.touched = true;
    if (picked.has(id)) picked.delete(id); else picked.add(id);
    renderPick(id);
    updateApproveBtn();
  });

  function selectedIds() { return [...picked].filter((id) => S.items[id]?.state === "shortlisted" && S.drafts[id]); }
  function updateApproveBtn() {
    const n = selectedIds().length;
    const negotiating = Object.values(S.items).some((it) => it.state !== "shortlisted" && S.panes[it.id]);
    const ready = S.phase === "awaiting_approval" || (negotiating && n > 0);
    E.approveBtn.disabled = !ready || n === 0;
    if (!S.shortlist.length) return;
    if (negotiating) {
      const live = Object.keys(S.panes).length;
      E.picksSub.textContent = `Your agent is talking to ${live} of them${n || S.shortlist.some((id) => S.items[id]?.state === "shortlisted") ? ". You can still add others." : "."}`;
    }
    if (!ready && !negotiating) E.approveBtn.textContent = "Writing messages…";
    else if (n) E.approveBtn.textContent = `Message ${n} seller${n > 1 ? "s" : ""} →`;
    else E.approveBtn.textContent = negotiating ? "Pick another seller to add" : "Pick at least one seller";
    show(E.sendBar, !negotiating || selectedIds().length > 0 || S.shortlist.some((id) => S.items[id]?.state === "shortlisted"));
  }

  E.approveBtn.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length || !S.id) return;
    E.approveBtn.disabled = true;
    E.approveBtn.textContent = "Sending…";
    try {
      await api(`/api/hunts/${S.id}/approve`, { ids });
      S.approved = true;
      ids.forEach((id) => picked.delete(id));
      if (!negoOpen) openNego(); else setView("nego");
    } catch (e) { showError(`Couldn't message sellers: ${e.message}`); updateApproveBtn(); }
  });

  // ------------------------------------------------------------------ watch mode
  const E2 = { watch: $("#watch"), watchState: $("#watch-state"), watchHits: $("#watch-hits"), postTest: $("#post-test") };

  function onNotice(text) {
    setStatus(text);
    show(E.error, true);
    E.error.classList.add("notice");
    E.error.innerHTML = `<p>${esc(text)}</p>`;
  }

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
    ping(2);
    renderCard(ev.id);
    updateCounters();
    renderWatchHit(ev.id, ev.text);
    ping("results");
  }

  function renderWatchHit(id, text) {
    const it = S.items[id] || {};
    const l = it.listing || {};
    const d = S.drafts[id];
    if (!d || it.state !== "shortlisted") return;
    show(E2.watch, true);
    const offer = d.offer_sek ? `opening offer <b class="money">${kr(d.offer_sek)}</b>` : "asks a question first";
    const node = h(`<div class="whit" id="whit-${esc(id)}">${ph(l, "draft-ph")}
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
      b.replaceWith(h(`<span class="mono small">✓ Approved. See the Negotiation tab.</span>`));
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

  // ------------------------------------------------------------------ negotiation: seller list + one open chat
  // Like a messaging app: every seller is a row (status + current price in plain words); the open chat shows
  // just three numbers (asking, seller now, your offer) above the conversation.
  const ACT_PILL = { offer: "Offers", counter: "Counters with", accept: "Accepts", walk_away: "Walks away", decline: "Declines" };
  const RULE_TEXT = {
    budget_cap: "Safety check: kept the offer within your budget",
    false_claim: "Safety check: blocked a claim that wasn't true",
    message_limit: "Safety check: message limit reached",
    untrusted_input: "Safety check: ignored instructions hidden in the seller's message",
  };
  let activePane = null;

  function ensurePane(id) {
    if (S.panes[id]) return S.panes[id];
    const it = S.items[id] || { id };
    const l = it.listing || {};
    const el = h(`<article class="pane hidden" id="pane-${esc(id)}">
      <header class="pane-head">
        <div class="pane-id">${ph(l, "pane-ph")}<div><h3 class="pane-title">${esc(l.title || id)}</h3>
          <p class="pane-who muted">${esc(l.seller?.name || "Seller")} · ${esc(l.location || "")}</p></div></div>
        <div class="nums">
          <div><span>Asking</span><b class="mono">${kr(l.price_sek)}</b></div>
          <div><span>Seller now</span><b class="mono ts">${kr(l.price_sek)}</b></div>
          <div class="you"><span>Your offer</span><b class="mono tb">–</b></div>
        </div>
        <p class="badge neg">Your agent is negotiating…</p>
      </header>
      <div class="chat"></div>
    </article>`);
    E.panes.appendChild(el);
    const row = h(`<button type="button" class="thread" data-thread="${esc(id)}">
      ${ph(l, "th-ph")}
      <span class="th-main"><span class="th-title">${esc(l.seller?.name || "Seller")}</span><span class="th-item">${esc(l.title || id)}</span><span class="th-status">Negotiating…</span></span>
      <span class="th-price mono"><b>${kr(l.price_sek)}</b></span>
    </button>`);
    E.threads.appendChild(row);
    const pane = { el, row, chat: $(".chat", el), buyer: null, seller: l.price_sek || null, typing: null };
    S.panes[id] = pane;
    show(E.nego, true);
    if (!negoOpen) openNego();
    const n = Object.keys(S.panes).length;
    E.negoCount.textContent = `· ${n} seller${n > 1 ? "s" : ""}`;
    if (!activePane) selectPane(id);
    updateTicker(id);
    return pane;
  }

  function selectPane(id) {
    activePane = id;
    Object.entries(S.panes).forEach(([pid, p]) => {
      const on = pid === id;
      show(p.el, on);
      p.row.classList.toggle("on", on);
      p.row.setAttribute("aria-pressed", String(on));
      if (on) { p.row.classList.remove("unread"); requestAnimationFrame(() => { p.chat.scrollTop = p.chat.scrollHeight; }); }
    });
  }
  E.threads.addEventListener("click", (e) => {
    const r = e.target.closest("[data-thread]");
    if (r) selectPane(r.dataset.thread);
  });

  function nearBottom(chat) { return chat.scrollHeight - chat.scrollTop - chat.clientHeight < 120; }
  function appendChat(pane, node) {
    const stick = nearBottom(pane.chat);
    if (pane.typing) { pane.typing.remove(); pane.typing = null; }
    pane.chat.appendChild(node);
    if (stick) requestAnimationFrame(() => { pane.chat.scrollTop = pane.chat.scrollHeight; });
    if (pane !== S.panes[activePane]) pane.row.classList.add("unread");
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
    const who = role === "buyer" ? "Your agent" : esc(S.items[ev.id]?.listing?.seller?.name || "Seller");
    const verb = ACT_PILL[ev.action];
    const pill = ev.price_sek && !rel ? `<span class="pill ${ev.action === "accept" ? "accept" : ""}">${verb ? `${verb} ` : ""}<b>${kr(ev.price_sek)}</b></span>`
      : verb && !rel ? `<span class="pill">${verb}</span>` : "";
    const node = h(`<div class="msg ${role} ${rel ? "release" : ""}">
      <div class="bubble"><p class="txt">${esc(ev.text)}</p>${pill}</div>
      <div class="meta">${who}${typeof ev.t === "number" ? ` · ${fmtClock(ev.t)}` : ""}</div>
      ${ev.thoughts ? `<p class="thought"><span class="tl">thinking:</span> ${esc(ev.thoughts)}</p>` : ""}
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
    const text = RULE_TEXT[ev.rule] || `Safety check: ${String(ev.rule || "").replace(/_/g, " ")}`;
    appendChat(pane, h(`<div class="sys rule" title="${esc(ev.detail || "")}"><span>${esc(text)}</span></div>`));
  }

  // plain numbers instead of a chart: seller's current price, your last offer, and the same on the list row
  function updateTicker(id, flashRole) {
    const pane = S.panes[id];
    const it = S.items[id] || {};
    const ask = it.listing?.price_sek || 0;
    const tb = $(".tb", pane.el), ts = $(".ts", pane.el);
    tb.textContent = pane.buyer ? kr(pane.buyer) : "–";
    ts.textContent = pane.seller ? kr(pane.seller) : "–";
    if (flashRole) bump(flashRole === "buyer" ? tb : ts, "flash");
    const now = it.deal?.price_sek || pane.seller || ask;
    $(".th-price", pane.row).innerHTML = now && ask && now < ask ? `<s>${num(ask)}</s> <b>${kr(now)}</b>` : `<b>${kr(now || ask)}</b>`;
  }

  function updatePane(id, prev) {
    const pane = ensurePane(id);
    const it = S.items[id];
    const badge = $(".badge", pane.el);
    const st = it.state;
    const price = it.deal?.price_sek;
    const ask = it.listing?.price_sek;
    const save = price && ask && ask > price ? ` · ${kr(ask - price)} below asking` : "";
    const why = it.reason ? `: ${clip(it.reason, 90)}` : "";
    const [cls, long, short] =
      st === "approved" || st === "negotiating" ? ["neg", "Your agent is negotiating…", "Negotiating…"]
      : st === "deal_offered" ? ["b-deal", `Deal at ${kr(price)}${save}. Reserved until you confirm.`, `Deal at ${kr(price)}`]
      : st === "confirmed" ? ["b-deal", `You're buying this for ${kr(price)}`, "Confirmed"]
      : st === "walked_away" ? ["bad", `No deal, your agent walked away${why}`, "No deal"]
      : st === "dropped" ? ["bad", `Dropped${why}`, "Dropped"]
      : st === "seller_declined" ? ["bad", "The seller said no", "Seller said no"]
      : st === "no_deal" ? ["bad", `No deal${why}`, "No deal"]
      : st === "released" ? ["bad", "You chose another deal. The seller was told politely.", "Not chosen"]
      : [null, null, null];
    if (cls) {
      badge.className = `badge ${cls}`; badge.textContent = long;
      const ts = $(".th-status", pane.row); ts.textContent = short; ts.className = `th-status ${cls}`;
    }
    pane.el.classList.toggle("is-deal", st === "deal_offered" || st === "confirmed");
    pane.el.classList.toggle("is-dead", DEAD_STATES.has(st));
    pane.row.classList.toggle("is-deal", st === "deal_offered" || st === "confirmed");
    pane.row.classList.toggle("is-dead", DEAD_STATES.has(st));

    if (st !== prev) {
      const sys = { deal_offered: ["deal", `Agreed on ${kr(price)}`], confirmed: ["deal", "You confirmed this deal"] }[st];
      if (sys) appendChat(pane, h(`<div class="sys ${sys[0]}"><span>${esc(sys[1])}</span></div>`));
      if (!LIVE_STATES.has(st)) setTyping(id, null);
      if (st === "deal_offered" && price) { pane.buyer = pane.seller = price; updateTicker(id); }
    }
  }

  E.thoughts.addEventListener("change", () => document.body.classList.toggle("hide-thoughts", !E.thoughts.checked));
  document.body.classList.toggle("hide-thoughts", !E.thoughts.checked);

  // ------------------------------------------------------------------ deals: pick one
  function onHandoff(ev) {
    S.handoff = ev;
    if (!negoOpen) openNego();
    ping("nego");
    setCalls(ev.calls);
    renderHandoff();
    if (view === "nego") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function renderHandoff() {
    if (!S.handoff) return;
    show(E.handoff, true);
    const ids = S.handoff.ids || [];
    const best = S.handoff.best;
    const confirmed = Object.values(S.items).find((it) => it.state === "confirmed");
    const all = Object.values(S.items).filter((it) => it.listing);
    const scams = all.filter((x) => x.state === "scam").length;
    const facts = [`${all.length} listings checked`, scams ? `${scams} scam${scams === 1 ? "" : "s"} avoided` : null, `${Math.round(S.t)} s`].filter(Boolean).join(" · ");

    E.handoffTitle.textContent = confirmed ? "Done! You've got a deal."
      : ids.length === 1 ? "A seller agreed. Confirm it?"
      : ids.length ? `${ids.length} sellers agreed. Pick one.`
      : "No deal this time";
    E.savings.innerHTML = confirmed
      ? `<p class="save-note">You're buying <b>${esc(confirmed.listing.title)}</b> for <b class="money mono">${kr(confirmed.deal?.price_sek)}</b>${confirmed.deal?.logistics ? `. Handover: ${esc(confirmed.deal.logistics)}` : ""}. The other sellers were told politely.</p><p class="save-facts muted small">${facts}</p>`
      : ids.length
        ? `<p class="save-note">Nothing is bought until you confirm. The other sellers get a polite no.</p><p class="save-facts muted small">${facts}</p>`
        : `<p class="save-note">No seller agreed to a price within your budget, so your agent didn't overpay.</p><p class="save-facts muted small">${facts}</p>`;

    const sorted = [...ids].sort((a, b) => (a === best ? -1 : b === best ? 1 : 0));
    E.deals.innerHTML = "";
    sorted.forEach((id, i) => {
      const it = S.items[id];
      if (!it?.listing) return;
      const d = it.deal || {};
      const isBest = id === best;
      const chosen = confirmed && confirmed.id === id;
      const ask = d.asking_sek || it.listing.price_sek;
      const saved = d.saved_sek ?? Math.max(0, ask - (d.price_sek || ask));
      const card = h(`<div class="deal ${isBest && !confirmed ? "best" : ""} ${chosen ? "chosen" : ""} ${confirmed && !chosen ? "faded" : ""}" style="animation-delay:${i * 60}ms">
        ${ph(it.listing, "deal-ph")}
        <div class="deal-body">
          ${isBest && !confirmed ? `<span class="tag">Recommended</span>` : ""}
          <h3 class="deal-title">${esc(it.listing.title)}</h3>
          <p class="deal-price"><b class="mono">${kr(d.price_sek)}</b>${saved > 0 ? ` <span class="save">you save ${kr(saved)}</span>` : ""}</p>
          <p class="deal-was muted small">Was ${kr(ask)} · ${esc(it.listing.seller?.name || "seller")} · ${esc(d.logistics || it.listing.location || "")}</p>
          <div class="deal-act">${chosen ? `<span class="done-mark">✓ Confirmed</span>` : confirmed ? "" : `<button class="btn ${isBest ? "btn-ink" : "btn-line"}" data-confirm="${esc(id)}">Buy this one</button>`}
            <button type="button" class="linkbtn see-chat" data-chat="${esc(id)}">See the chat</button></div>
        </div>
      </div>`);
      E.deals.appendChild(card);
    });
  }

  E.deals.addEventListener("click", async (e) => {
    const c = e.target.closest("[data-chat]");
    if (c) { selectPane(c.dataset.chat); E.nego.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
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
    E.board.innerHTML = ""; E.board.classList.remove("has-short"); E.rejList.innerHTML = ""; E.panes.innerHTML = ""; E.threads.innerHTML = ""; activePane = null; E.deals.innerHTML = ""; E.savings.innerHTML = "";
    E.reqChips.innerHTML = ""; E.calls.textContent = "Starting…";
    [E.question, E.reqs, E.boardSec, E.rejected, E.nego, E.handoff, E.error, E.moreBtn, E.sendBar].forEach((el) => show(el, false));
    E.picks.innerHTML = '<div class="pick skel"></div><div class="pick skel"></div><div class="pick skel"></div>';
    E.picksTitle.textContent = "Finding your best fits…";
    E.picksSub.textContent = "Reading and checking every listing. This takes about half a minute.";
    E.barFill.style.width = "0"; E.work.classList.remove("quiet");
    picked.clear(); showAll = false;
    E.rejected.open = false; E.boardSec.open = false;
    negoOpen = false;
    tabs.forEach((b) => b.classList.remove("ping"));
    updateCounters();
  }

  E.form.addEventListener("submit", (e) => { e.preventDefault(); startHunt(); });

  fetch("/api/info").then((r) => r.json()).then((i) => {
    if (i.host_label) $("#hostlbl").innerHTML = ` · running on <b>${esc(i.host_label)}</b> <span class="mono">(${esc(i.hostname)})</span>`;
  }).catch(() => {});

  // ------------------------------------------------------------------ voice input (Gemini 3.5 Transcribe)
  // One recorder per Speak button: the request box and the clarifying-question answer.
  async function transcribeBlob(blob) {
    // small chunks: survives tunnels (e.g. Matrix OS port forwarding) that drop large request bodies
    const id = Math.random().toString(36).slice(2, 10), CH = 24000;
    for (let i = 0, off = 0; off < blob.size; i++, off += CH) {
      const rc = await fetch(`/api/transcribe/chunk?id=${id}&i=${i}`, { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: blob.slice(off, off + CH) });
      if (!rc.ok) throw new Error(`upload failed (${rc.status})`);
    }
    const r = await fetch(`/api/transcribe/finish?id=${id}&mime=${encodeURIComponent(blob.type)}`, { method: "POST" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    const { text } = await r.json();
    if (!text) throw new Error("didn't catch that");
    return text;
  }

  function makeMic(btn, onText) {
    if (!btn) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { btn.classList.add("hidden"); return; }
    const m = { rec: null, chunks: [], t0: 0, timer: null };
    const lbl = (t) => { const l = $(".mic-lbl", btn); if (l) l.textContent = t; };
    async function start() {
      let stream;
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
      catch (e) { showError("Microphone blocked. Allow mic access (the page must be https or localhost)."); return; }
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
      m.rec = new MediaRecorder(stream, { ...(type ? { mimeType: type } : {}), audioBitsPerSecond: 24000 });
      m.chunks = [];
      m.rec.ondataavailable = (e) => e.data.size && m.chunks.push(e.data);
      m.rec.onstop = () => { stream.getTracks().forEach((t) => t.stop()); send(); };
      m.rec.start();
      m.t0 = performance.now();
      btn.classList.add("rec");
      lbl("0:00 · stop");
      m.timer = setInterval(() => {
        const sec = (performance.now() - m.t0) / 1000;
        lbl(`${fmtClock(sec)} · stop`);
        if (sec > 30) stop();  // keep clips short
      }, 250);
    }
    function stop() {
      clearInterval(m.timer);
      btn.classList.remove("rec");
      if (m.rec && m.rec.state !== "inactive") m.rec.stop();
    }
    async function send() {
      const blob = new Blob(m.chunks, { type: m.rec.mimeType || "audio/webm" });
      m.rec = null;
      if (blob.size < 1500) { lbl("Speak"); return; }
      btn.disabled = true; lbl("Transcribing…");
      try { onText(await transcribeBlob(blob)); }
      catch (e) { showError(`Voice: ${e.message}`); }
      finally { btn.disabled = false; lbl("Speak"); }
    }
    btn.addEventListener("click", () => (m.rec ? stop() : start()));
  }

  makeMic($("#mic-btn"), (text) => {
    E.request.value = text;
    E.request.dispatchEvent(new Event("input"));
    setTimeout(() => startHunt(), 700);  // show what was heard, then go
  });
  makeMic($("#mic-answer"), (text) => {
    E.answer.value = text;
    setTimeout(() => E.answerForm.requestSubmit(), 700);
  });
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

  api("/api/hunts").then((hunts) => {
    if (!hunts.length || params.get("h")) return;
    const list = document.createElement("div");
    list.className = "saved";
    list.innerHTML = `<p class="saved-h">Earlier hunts</p>${hunts.slice(-10).reverse().map((hunt) =>
      `<p><a href="?h=${encodeURIComponent(hunt.id)}">${esc(hunt.request)} (${esc(hunt.phase)})</a></p>`).join("")}`;
    $(".home .hint").after(list);
  }).catch(() => {});

  // deep link from the Gemini app skill: /?q=<complete brief>&go=1 (questions were already asked in chat)
  const deep = params.get("q");
  if (deep && !params.get("h") && !E.replay.checked) {
    E.request.value = deep.slice(0, 2000);
    autosize();
    if (params.get("go") === "1") setTimeout(() => startHunt({ clarified: true }), 300);
  }

  // resume a hunt after a page reload (?h=<id>)
  const resume = params.get("h");
  if (resume) {
    api(`/api/hunts/${resume}`).then((snap) => {
      S.started = true;
      setView("results");
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
