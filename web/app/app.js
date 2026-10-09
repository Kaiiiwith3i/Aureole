"use strict";
const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";

function el(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) e.setAttribute(k, v);
  }
  kids.flat().forEach((c) => c != null && e.append(c));
  return e;
}

async function api(path, opts) {
  let res;
  try { res = await fetch(path, opts); }
  catch { throw new Error("Can't reach the Aureole server. Is it running?"); }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const d = body && body.detail;
    const err = new Error(typeof d === "string" ? d : d ? "The server rejected the request: " + JSON.stringify(d) : `Server error (${res.status}).`);
    err.status = res.status;
    throw err;
  }
  return body;
}
const post = (path, data) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
const say = (id, text, cls) => { const n = $(id); n.replaceChildren(); if (text) n.append(el("div", { class: cls, text })); };

/* ---------- tabs ---------- */
const tabs = [...document.querySelectorAll("[role=tab]")];
function showTab(t) {
  tabs.forEach((b) => {
    const on = b === t;
    b.setAttribute("aria-selected", on);
    b.tabIndex = on ? 0 : -1;
    $(b.getAttribute("aria-controls")).hidden = !on;
  });
  if (t.id === "tab-registry" && staff) loadRegistry();
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => showTab(t));
  t.addEventListener("keydown", (e) => {
    const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!d) return;
    const n = tabs[(i + d + tabs.length) % tabs.length];
    n.focus(); showTab(n);
  });
});

/* ---------- staff sign-in ---------- */
let staff = false;
function setStaff(on) {
  const was = staff;
  staff = on;
  document.querySelectorAll("[data-gate]").forEach((g) => { g.hidden = on; });
  document.querySelectorAll("[data-staff]").forEach((g) => { g.hidden = !on; });
  $("signout").hidden = !on;
  if (was && !on) {
    $("r-list").replaceChildren(); $("i-result").replaceChildren();
    say("r-status", ""); say("i-status", ""); $("report").replaceChildren(); // reports may hold issued text
  }
  if (on && !$("registry").hidden) loadRegistry();
}
document.querySelectorAll("[data-gate]").forEach((g, n) => {
  const msg = el("div", { role: "status", "aria-live": "polite" });
  const pw = el("input", { type: "password", id: "pw" + n, autocomplete: "current-password", required: "" });
  g.append(el("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    msg.replaceChildren();
    try { await post("/api/login", { password: pw.value }); pw.value = ""; setStaff(true); }
    catch (err) { msg.replaceChildren(el("div", { class: "err", text: err.status === 401 ? "Wrong password." : "Couldn't sign in. " + err.message })); }
  } },
  el("p", { class: "muted", text: "Staff only. Sign in to continue." }),
  el("label", { for: "pw" + n, text: "Staff password" }), pw,
  el("div", { class: "row" }, el("button", { type: "submit", class: "btn primary", text: "Sign in" })), msg));
});
$("signout").onclick = async () => { try { await post("/api/logout", {}); } catch { /* cookie may already be gone */ } setStaff(false); };
// a 401 from any staff call means the session ended
const staffCall = (e) => { if (e.status === 401) setStaff(false); };
api("/api/me").then((m) => setStaff(!!m.staff), () => setStaff(false));

/* ---------- verify ---------- */
const MOCK = new URLSearchParams(location.search).has("mock");
const MAX_FILES = 10;
let busy = false;
let queue = [];

function renderQueue() {
  $("queue").hidden = !queue.length;
  $("queue-list").replaceChildren(...queue.map((f, i) => el("li", {},
    el("span", { text: f.name || "capture" }),
    el("button", { type: "button", class: "btn", "aria-label": "Remove " + (f.name || "capture"), text: "Remove", onclick: () => { queue.splice(i, 1); renderQueue(); } }))));
  $("add-page").hidden = queue.length >= MAX_FILES;
}
function addFiles(list) {
  const room = MAX_FILES - queue.length;
  const add = [...list].slice(0, room);
  queue.push(...add);
  say("v-status", list.length > room ? `Only ${MAX_FILES} files can be checked at once. Extra files were left out.` : "", "err");
  renderQueue();
  if (add.length) $("go").focus();
}

async function verify() {
  if (busy || !queue.length) return;
  busy = true;
  $("go").disabled = true;
  $("report").replaceChildren();
  const status = $("v-status");
  status.replaceChildren(el("div", { class: "verify-progress busy" },
    el("div", { class: "progress-mark", "aria-hidden": "true" }),
    el("div", {},
      el("strong", { text: "We’re verifying your document" }),
      el("span", { text: `Checking ${queue.length} file${queue.length > 1 ? "s" : ""} for its seal, pages, and printed content.` }))));
  try {
    const fd = new FormData();
    queue.forEach((f) => fd.append("files", f, f.name || "capture.jpg"));
    const r = await api("/api/verify", { method: "POST", body: fd });
    say("v-status", "");
    queue = []; renderQueue();
    renderReport(r);
  } catch (e) {
    say("v-status", "Verification failed. " + e.message, "err");
  } finally { busy = false; $("go").disabled = false; }
}
$("go").onclick = verify;
$("clear").onclick = () => { queue = []; renderQueue(); say("v-status", ""); };

const pick = (input) => input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
pick($("file-in")); pick($("cam-in"));
$("choose").onclick = () => $("file-in").click();
$("camera").onclick = () => $("cam-in").click();
$("add-page").onclick = () => $("cam-in").click();

const drop = $("drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); });
drop.addEventListener("keydown", (e) => { if (e.target === drop && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); $("file-in").click(); } });

/* webcam: only offered in a secure context (localhost) */
let stream = null;
function stopCam() { stream && stream.getTracks().forEach((t) => t.stop()); stream = null; $("cam-box").hidden = true; }
if (window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
  $("webcam").hidden = false;
  $("webcam").onclick = async () => {
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1920 } } });
      $("cam-video").srcObject = stream;
      $("cam-box").hidden = false;
    } catch (e) { say("v-status", "Couldn't open the webcam: " + e.message, "err"); }
  };
  $("cam-stop").onclick = stopCam;
  $("cam-snap").onclick = () => {
    const v = $("cam-video");
    if (!v.videoWidth) return;
    const c = el("canvas");
    c.width = v.videoWidth; c.height = v.videoHeight;
    c.getContext("2d").drawImage(v, 0, 0);
    c.toBlob((b) => { stopCam(); if (b) addFiles([new File([b], `webcam-${queue.length + 1}.jpg`, { type: "image/jpeg" })]); }, "image/jpeg", 0.92);
  };
}

if (MOCK) {
  const s = $("sample");
  s.hidden = false;
  s.onclick = async () => {
    try { renderReport(await api("mock_report.json")); say("v-status", ""); }
    catch (e) { say("v-status", "Couldn't load the sample. " + e.message, "err"); }
  };
  s.click();
}

/* ---------- report ---------- */
const VERDICTS = {
  AUTHENTIC: ["Authentic", "M5 12.5l4.5 4.5L19 7.5"],
  AUTHENTIC_WITH_NOTES: ["Authentic, with notes", "M5 12.5l4.5 4.5L19 7.5 M12 21v0"],
  MODIFIED: ["Modified", "M6 6l12 12M18 6L6 18"],
  INCONCLUSIVE: ["Inconclusive", "M9 9a3 3 0 1 1 4.5 2.6c-1 .6-1.5 1.2-1.5 2.4M12 17.5v.5"],
  REVOKED: ["Revoked", "M5.5 5.5l13 13"],
  INVALID_SEAL: ["Invalid seal", "M12 8v5M12 16.5v.5"],
  NOT_ISSUED: ["Not issued", "M7 12h10"],
};
const LAYERS = [["scan", "Scan"], ["expected", "Issued original"], ["diff", "Differences"], ["ela", "Error-level"]];
const TYPE_LABEL = { text_change: "Text change", physical_damage: "Physical damage", handwriting: "Handwriting", stamp: "Stamp", fold: "Fold", unknown: "Unknown" };

function icon(verdict) {
  const [, d] = VERDICTS[verdict] || VERDICTS.NOT_ISSUED;
  const s = document.createElementNS(NS, "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  const shield = document.createElementNS(NS, "path");
  shield.setAttribute("d", "M12 1.5 3.5 4.8v6.4c0 5.3 3.6 9.9 8.5 11.3 4.9-1.4 8.5-6 8.5-11.3V4.8z");
  const mark = document.createElementNS(NS, "path");
  mark.setAttribute("d", d);
  [shield, mark].forEach((p) => { p.setAttribute("fill", "none"); p.setAttribute("stroke", "currentColor"); p.setAttribute("stroke-width", "1.8"); p.setAttribute("stroke-linecap", "round"); p.setAttribute("stroke-linejoin", "round"); s.append(p); });
  return s;
}
const chip = (cls, text) => el("span", { class: "chip s-" + cls, text });
const pct = (x) => Math.round(x * 100) + "%";
const vlabel = (v) => (VERDICTS[v] || [v])[0];

function renderReport(r) {
  const label = vlabel(r.verdict);
  const checked = r.pages_checked && r.pages_checked.length ? r.pages_checked.join(", ") + (r.pages_total ? " of " + r.pages_total : "") : null;
  const meta = [
    ["File", r.filename], ["Doc", r.doc_id],
    ["Version", r.version != null ? "v" + r.version + (r.current_version && r.current_version !== r.version ? " (current v" + r.current_version + ")" : "") : null],
    ["Staff approval", r.approval_id],
    ["Registry", r.registry_status], ["Pages checked", checked],
    ["Time", r.timings && r.timings.total != null ? Math.round(r.timings.total) + " ms" : null],
  ].filter(([, v]) => v);

  const out = [
    el("div", { class: "banner v-" + r.verdict, role: "group", "aria-label": "Verdict: " + label },
      icon(r.verdict),
      el("div", {}, el("div", { class: "vl", text: label }), el("p", { class: "hl", text: r.headline }))),
    el("ul", { class: "meta" }, meta.map(([k, v]) => el("li", {}, k + ": ", el("b", { text: v })))),
  ];
  if (r.notes && r.notes.length) out.push(el("ul", { class: "notes" }, r.notes.map((n) => el("li", { text: n }))));
  if (r.mode === "digital" || r.mode === "approved") {
    out.push(el("p", { class: "muted", text: r.mode === "approved"
      ? r.verdict === "REVOKED" ? "This signed copy was approved by staff, but the document has since been revoked or replaced."
        : "These files match a signed copy approved by issuer staff."
      : r.verdict === "REVOKED" ? "This file is byte-identical to a file Aureole issued, but that document has since been revoked or replaced."
      : "This file is byte-identical to the issued file. No page analysis was needed." }));
  } else if (r.pages && r.pages.length) {
    out.push(pagesView(r.pages));
  }
  out.push(el("p", { class: "disclaimer", text: "Aureole explains what changed. A person makes the final decision." }));
  $("report").replaceChildren(...out);
  $("report").scrollIntoView({ block: "start", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
}

function pagesView(pages) {
  const holder = el("div", {});
  const btns = pages.map((p, i) => el("button", { type: "button", class: "pg v-" + p.verdict, "aria-pressed": "false",
    "aria-label": `Page ${p.page != null ? p.page : "unknown"}, ${vlabel(p.verdict)}`, text: p.page != null ? String(p.page) : "?",
    onclick: () => show(i) }));
  const show = (i) => {
    btns.forEach((b, k) => b.setAttribute("aria-pressed", k === i));
    holder.replaceChildren(pageView(pages[i]));
  };
  show(0);
  return el("div", {},
    pages.length > 1 ? el("div", { class: "pages", role: "group", "aria-label": "Pages" }, el("span", { class: "muted", text: "Page:" }), btns) : null,
    holder);
}

function pageView(p) {
  const hasExpected = p.lines.some((l) => l.expected != null);
  const out = [
    el("div", { class: "pagehead v-" + p.verdict },
      el("span", { class: "chip", text: vlabel(p.verdict) }),
      el("span", { class: "ph-t", text: p.headline })),
    el("p", { class: "muted", text: `${p.lines_matched} of ${p.lines_total} lines match, ${p.lines_unchecked} not machine-checkable.` }),
  ];
  if (p.notes && p.notes.length) out.push(el("ul", { class: "notes" }, p.notes.map((n) => el("li", { text: n }))));
  out.push(el("h3", { text: p.verdict === "AUTHENTIC" ? "Page review" : "Where it differs" }), viewer(p));
  if (p.lines.length) {
    const head = ["Status", "What was read"].concat(hasExpected ? ["Issued text"] : []);
    out.push(el("h3", { text: "Lines that don't match" }),
      el("table", { class: "stack" },
        el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col", text: h })))),
        el("tbody", {}, p.lines.map((l) => el("tr", {},
          el("td", { "data-label": head[0] }, chip(l.status, l.status)),
          el("td", { "data-label": head[1], text: l.read || "(not read)" }),
          hasExpected ? el("td", { "data-label": head[2], text: l.expected != null ? l.expected : "" }) : null)))));
    if (!hasExpected && !staff) out.push(el("p", { class: "muted", text: "Sign in as staff to see the issued text." }));
  }
  return el("div", {}, out);
}

function viewer(p) {
  const [w, h] = p.image_size;
  const imgs = p.images || {};
  const stage = el("div", { class: "stage", style: `aspect-ratio:${w}/${h}` });
  const boxes = {}, items = {};
  const avail = LAYERS.filter(([k]) => imgs[k]);

  const setLayer = (k) => {
    stage.querySelectorAll("img,.ph").forEach((n) => n.remove());
    stage.prepend(k
      ? el("img", { src: imgs[k], alt: LAYERS.find((l) => l[0] === k)[1] + " layer of the page" })
      : el("div", { class: "ph", text: "No image for this page. Boxes show where differences were found." }));
    toggles.forEach(([key, b]) => b.setAttribute("aria-pressed", key === k));
  };
  const toggles = avail.map(([k, name]) => [k, el("button", { type: "button", "aria-pressed": "false", text: name, onclick: () => setLayer(k) })]);

  let current = null;
  const select = (id, fromBox) => {
    current = current === id ? null : id;
    for (const k in boxes) { boxes[k].classList.toggle("on", k === current); items[k].classList.toggle("on", k === current); items[k].setAttribute("aria-pressed", k === current); }
    if (current) {
      const d = items[current].closest("details"); if (d && fromBox) d.open = true;
      (fromBox ? items[current] : stage).scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  };

  const mk = (f) => {
    const [x, y, bw, bh] = f.bbox;
    const label = `${TYPE_LABEL[f.type] || f.type}, ${f.line != null ? "line " + (f.line + 1) : "outside the text lines"}`;
    boxes[f.id] = el("button", { type: "button", class: "box s-" + f.severity, "aria-label": "Finding: " + label,
      style: `left:${x / w * 100}%;top:${y / h * 100}%;width:${bw / w * 100}%;height:${bh / h * 100}%`, onclick: () => select(f.id, true) });
    stage.append(boxes[f.id]);
    items[f.id] = el("button", { type: "button", class: "finding", "aria-pressed": "false", onclick: () => select(f.id, false) },
      el("span", { class: "h" }, TYPE_LABEL[f.type] || f.type, " | ", f.line != null ? "Line " + (f.line + 1) : "Outside the text lines",
        chip(f.severity, f.severity), el("span", { text: pct(f.confidence) })),
      el("p", { text: f.message }));
    return el("li", {}, items[f.id]);
  };

  const all = p.findings || [];
  const main = all.filter((f) => f.type !== "unknown").map(mk);
  const minor = all.filter((f) => f.type === "unknown").map(mk);
  setLayer(avail.length ? avail[0][0] : null);

  return el("div", {},
    toggles.length ? el("div", { class: "layers", role: "group", "aria-label": "Image layer" }, toggles.map((t) => t[1])) : null,
    stage,
    el("h3", { text: "Findings" }),
    main.length ? el("ul", { class: "findings" }, main) : el("p", { class: "muted", text: p.verdict === "AUTHENTIC" ? "No differences found on this page." : "No specific finding is available for this page." }),
    minor.length ? el("details", {}, el("summary", { text: `Minor differences, likely capture noise (${minor.length})` }), el("ul", { class: "findings" }, minor)) : null);
}

/* ---------- issue ---------- */
const groups4 = (s) => (s.match(/.{1,4}/g) || []).join(" ");
const issued = (r) => el("div", { class: "issued" },
  el("h3", { text: `Issued: ${r.doc_id}, version ${r.version}` }),
  el("ul", { class: "meta" },
    [["Title", r.title], ["Pages", r.pages], ["Fingerprint", groups4(r.fingerprint)]].map(([k, v]) => el("li", {}, k + ": ", el("b", { text: String(v) })))),
  el("div", { class: "row" }, el("a", { class: "btn primary", href: r.pdf_url, download: "", text: "Download sealed PDF" })));

$("issue-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("issue-btn");
  btn.disabled = true;
  say("i-status", "We’re preparing your sealed document…", "busy");
  $("i-result").replaceChildren();
  try {
    const r = await api("/api/issue", { method: "POST", body: new FormData(e.target) });
    say("i-status", "");
    $("i-result").replaceChildren(issued(r));
  } catch (err) { staffCall(err); say("i-status", "Couldn't issue the document. " + err.message, "err"); }
  finally { btn.disabled = false; }
});

/* ---------- registry ---------- */
async function loadRegistry() {
  say("r-status", "Loading registry…", "busy");
  try {
    const list = await api("/api/registry");
    say("r-status", list.length ? "" : "No documents issued yet.", "muted");
    $("r-list").replaceChildren(...list.map(entryCard));
  } catch (e) {
    staffCall(e);
    $("r-list").replaceChildren();
    say("r-status", "Couldn't load the registry. " + e.message, "err");
  }
}
$("reg-refresh").onclick = loadRegistry;

let reissueDoc = null;
let approveDoc = null;
$("reissue-in").addEventListener("change", async (e) => {
  const f = e.target.files[0]; e.target.value = "";
  if (!f || !reissueDoc) return;
  const fd = new FormData(); fd.append("file", f);
  say("r-status", "Reissuing…", "busy");
  try {
    const r = await api(`/api/registry/${encodeURIComponent(reissueDoc)}/reissue`, { method: "POST", body: fd });
    await loadRegistry();
    $("r-status").prepend(el("div", { class: "muted", text: `Reissued ${r.doc_id} as version ${r.version}.` }));
  } catch (err) { staffCall(err); say("r-status", "Couldn't reissue. " + err.message, "err"); }
});

$("approve-in").addEventListener("change", async (e) => {
  const files = [...e.target.files]; e.target.value = "";
  if (!files.length || !approveDoc) return;
  const docId = approveDoc;
  const fd = new FormData(); files.forEach((f) => fd.append("files", f));
  showTab($("tab-verify"));
  say("v-status", "Checking the signed copy against the issued document…", "busy");
  try {
    const report = await api("/api/verify", { method: "POST", body: fd });
    say("v-status", ""); renderReport(report);
    if (report.mode === "approved" && report.doc_id === docId) {
      say("v-status", `This signed copy is already approved (${report.approval_id}).`, "muted"); return;
    }
    const clean = report.doc_id === docId && report.registry_status === "active" && report.mode === "pages"
      && ["AUTHENTIC", "AUTHENTIC_WITH_NOTES"].includes(report.verdict)
      && report.pages_checked.length === report.pages_total;
    if (!clean) { say("v-status", "This copy cannot be approved: its printed content or pages did not pass verification.", "err"); return; }
    const btn = el("button", { type: "button", class: "btn primary", text: "Approve this signed copy", onclick: async () => {
      btn.disabled = true;
      try {
        const approved = await api(`/api/registry/${encodeURIComponent(docId)}/approve`, { method: "POST", body: fd });
        btn.remove(); say("v-status", `Signed copy approved (${approved.id}). The unsigned issued file remains valid.`, "muted");
      } catch (err) { staffCall(err); say("v-status", "Could not approve this copy. " + err.message, "err"); btn.disabled = false; }
    } });
    $("report").prepend(el("div", { class: "row" }, btn));
  } catch (err) { staffCall(err); say("v-status", "Could not review this copy. " + err.message, "err"); }
});

function entryCard(en) {
  const approvedList = el("div", { class: "d" });
  const actions = en.status === "active" ? [
    el("button", { type: "button", class: "btn danger", text: "Revoke", onclick: async () => {
      if (!confirm(`Revoke ${en.doc_id} (${en.title})? Verifying it will report it as revoked.`)) return;
      try { await post(`/api/registry/${encodeURIComponent(en.doc_id)}/revoke`, {}); } catch (e) { staffCall(e); say("r-status", "Couldn't revoke. " + e.message, "err"); return; }
      loadRegistry();
    } }),
    el("button", { type: "button", class: "btn", text: "Reissue", onclick: () => { reissueDoc = en.doc_id; $("reissue-in").click(); } }),
    el("button", { type: "button", class: "btn", text: "Review signed copy", onclick: () => { approveDoc = en.doc_id; $("approve-in").click(); } }),
  ] : [];
  if (en.approved_copies) actions.push(el("button", { type: "button", class: "btn", text: "Approved copies", onclick: async () => {
    try {
      const copies = await api(`/api/registry/${encodeURIComponent(en.doc_id)}/approved`);
      approvedList.replaceChildren(...copies.filter((c) => c.version === en.version).flatMap((c) => c.files.map((url, i) =>
        el("a", { class: "btn", href: url, download: "", text: `Approved ${c.id}, file ${i + 1}` }))));
    } catch (err) { staffCall(err); say("r-status", "Could not load approved copies. " + err.message, "err"); }
  } }));
  return el("article", { class: "entry" },
    el("div", { class: "row spread" }, el("span", { class: "t", text: en.title }), chip(en.status, en.status)),
    el("div", { class: "d", text: `${en.source_name} | ${en.source_type.toUpperCase()} | ${en.pages} page${en.pages === 1 ? "" : "s"}` }),
    el("div", { class: "d", text: `${en.doc_id} v${en.version} | fingerprint ${groups4(en.fingerprint)} | ${en.approved_copies} approved signed cop${en.approved_copies === 1 ? "y" : "ies"} | issued ${new Date(en.issued_at).toLocaleString()}` }),
    el("div", { class: "row" }, el("a", { class: "btn", href: en.pdf_url, download: "", text: "Download PDF" }), actions), approvedList);
}

/* ---------- health ---------- */
api("/api/health").then(
  (h) => {
    $("health").textContent = `Local verification engine: ${h.ocr_engine}`;
    $("conv-note").hidden = h.converter !== false;
  },
  () => { $("health").textContent = "Server status unavailable."; });
