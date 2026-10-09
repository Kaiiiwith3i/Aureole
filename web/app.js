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
  catch { throw new Error("Can't reach the Signet server. Is it running?"); }
  let body = null;
  try { body = await res.json(); } catch { /* non-JSON body */ }
  if (!res.ok) {
    const d = body && body.detail;
    throw new Error(typeof d === "string" ? d : d ? "The server rejected the request: " + JSON.stringify(d) : `Server error (${res.status}).`);
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
  if (t.id === "tab-registry") loadRegistry();
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

/* ---------- verify ---------- */
const MOCK = new URLSearchParams(location.search).has("mock");
let busy = false;

async function verify(file) {
  if (busy) return;
  busy = true;
  $("report").replaceChildren();
  say("v-status", "Verifying " + (file.name || "capture") + " offline…", "busy");
  try {
    const fd = new FormData();
    fd.append("file", file, file.name || "webcam.jpg");
    const r = await api("/api/verify", { method: "POST", body: fd });
    say("v-status", "");
    renderReport(r);
  } catch (e) {
    say("v-status", "Verification failed. " + e.message, "err");
  } finally { busy = false; }
}

const pick = (input) => input.addEventListener("change", () => { if (input.files[0]) verify(input.files[0]); input.value = ""; });
pick($("file-in")); pick($("cam-in"));
$("choose").onclick = () => $("file-in").click();
$("camera").onclick = () => $("cam-in").click();

const drop = $("drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => {
  e.preventDefault(); drop.classList.remove("over");
  if (e.dataTransfer.files[0]) verify(e.dataTransfer.files[0]);
});
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
    c.toBlob((b) => { stopCam(); if (b) verify(new File([b], "webcam.jpg", { type: "image/jpeg" })); }, "image/jpeg", 0.92);
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
  MISMATCH: ["Mismatch", "M6 6l12 12M18 6L6 18"],
  INCONCLUSIVE: ["Inconclusive", "M9 9a3 3 0 1 1 4.5 2.6c-1 .6-1.5 1.2-1.5 2.4M12 17.5v.5"],
  REVOKED: ["Revoked", "M5.5 5.5l13 13"],
  INVALID_SEAL: ["Invalid seal", "M12 8v5M12 16.5v.5"],
  NO_SEAL: ["No seal", "M7 12h10"],
};
const LAYERS = [["scan", "Scan"], ["expected", "Expected"], ["diff", "Differences"], ["ela", "ELA"]];
const TYPE_LABEL = { text_change: "Text change", digital_edit: "Digital edit", physical_damage: "Physical damage", handwriting: "Handwriting", stamp: "Stamp", fold: "Fold", unknown: "Unknown" };
const FIELD_LABEL = { name: "Name", student_id: "Student ID", program: "Program", award: "Award", grade: "Grade", date_issued: "Date issued" };

function icon(verdict) {
  const [, d] = VERDICTS[verdict] || VERDICTS.NO_SEAL;
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

function renderReport(r) {
  const [label] = VERDICTS[r.verdict] || [r.verdict];
  const meta = [
    ["File", r.filename], ["Doc", r.doc_id],
    ["Version", r.version != null ? "v" + r.version + (r.current_version && r.current_version !== r.version ? " (current v" + r.current_version + ")" : "") : null],
    ["Issuer", r.kid], ["Registry", r.registry_status],
    ["Time", r.timings && r.timings.total != null ? Math.round(r.timings.total) + " ms" : null],
  ].filter(([, v]) => v);

  const out = [
    el("div", { class: "banner v-" + r.verdict, role: "group", "aria-label": "Verdict: " + label },
      icon(r.verdict),
      el("div", {}, el("div", { class: "vl", text: label }), el("p", { class: "hl", text: r.headline }))),
    el("ul", { class: "meta" }, meta.map(([k, v]) => el("li", {}, k + ": ", el("b", { text: v })))),
  ];
  if (r.notes && r.notes.length) out.push(el("ul", { class: "notes" }, r.notes.map((n) => el("li", { text: n }))));
  if (r.fields && r.fields.length) out.push(el("h3", { text: "Protected fields" }), fieldTable(r.fields));
  out.push(el("h3", { text: "Where it differs" }), viewer(r));
  out.push(el("p", { class: "disclaimer", text: "Signet explains what changed. A person makes the final decision." }));
  $("report").replaceChildren(...out);
  $("report").scrollIntoView({ block: "start", behavior: "smooth" });
}

function fieldTable(fields) {
  const head = ["Field", "Signed value", "Printed value", "Status", "Confidence"];
  return el("table", { class: "stack" },
    el("thead", {}, el("tr", {}, head.map((h) => el("th", { scope: "col", text: h })))),
    el("tbody", {}, fields.map((f) => el("tr", {},
      el("td", { "data-label": head[0], text: f.label }),
      el("td", { "data-label": head[1], text: f.signed }),
      el("td", { "data-label": head[2], text: f.read || "(not read)" }),
      el("td", { "data-label": head[3] }, chip(f.status, f.status)),
      el("td", { "data-label": head[4], text: pct(f.confidence) })))));
}

function viewer(r) {
  const [w, h] = r.image_size;
  const imgs = r.images || {};
  const stage = el("div", { class: "stage", style: `aspect-ratio:${w}/${h}` });
  const boxes = {}, items = {};
  let layer = imgs.scan ? "scan" : LAYERS.map((l) => l[0]).find((k) => imgs[k]) || "scan";

  const setLayer = (k) => {
    layer = k;
    stage.querySelectorAll("img,.ph").forEach((n) => n.remove());
    stage.prepend(imgs[k]
      ? el("img", { src: imgs[k], alt: LAYERS.find((l) => l[0] === k)[1] + " layer of the certificate" })
      : el("div", { class: "ph", text: "No image for this layer. Boxes show where differences were found." }));
    toggles.forEach(([key, b]) => b.setAttribute("aria-pressed", key === k));
  };
  const toggles = LAYERS.map(([k, name]) => [k, el("button", { type: "button", disabled: imgs[k] ? null : "", "aria-pressed": "false", text: name, onclick: () => setLayer(k) })]);

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
    const label = `${TYPE_LABEL[f.type] || f.type}, ${f.field ? FIELD_LABEL[f.field] || f.field : "outside protected areas"}`;
    boxes[f.id] = el("button", { type: "button", class: "box s-" + f.severity, "aria-label": "Finding: " + label,
      style: `left:${x / w * 100}%;top:${y / h * 100}%;width:${bw / w * 100}%;height:${bh / h * 100}%`, onclick: () => select(f.id, true) });
    stage.append(boxes[f.id]);
    items[f.id] = el("button", { type: "button", class: "finding", "aria-pressed": "false", onclick: () => select(f.id, false) },
      el("span", { class: "h" }, TYPE_LABEL[f.type] || f.type, " | ", f.field ? FIELD_LABEL[f.field] || f.field : "Outside protected areas",
        chip(f.severity, f.severity), el("span", { text: pct(f.confidence) })),
      el("p", { text: f.message }));
    return el("li", {}, items[f.id]);
  };

  const all = r.findings || [];
  const main = all.filter((f) => f.type !== "unknown").map(mk);
  const minor = all.filter((f) => f.type === "unknown").map(mk);
  setLayer(layer);

  return el("div", {},
    el("div", { class: "layers", role: "group", "aria-label": "Image layer" }, toggles.map((t) => t[1])),
    stage,
    el("h3", { text: "Findings" }),
    main.length ? el("ul", { class: "findings" }, main) : el("p", { class: "muted", text: "No findings of a known type." }),
    minor.length ? el("details", {}, el("summary", { text: `Minor differences, likely capture noise (${minor.length})` }), el("ul", { class: "findings" }, minor)) : null);
}

/* ---------- issue ---------- */
const SAMPLE = { name: "Juan Dela Cruz (sample)", student_id: "2026-00001", program: "BS Computer Science", award: "With Honors", grade: "1.50", date_issued: new Date().toISOString().slice(0, 10) };
const form = $("issue-form");
let reissueOf = null;

function fillForm(v) { for (const k in v) form.elements[k].value = v[k]; }
function setReissue(entry) {
  reissueOf = entry ? entry.doc_id : null;
  $("issue-title").textContent = entry ? `Reissue ${entry.doc_id} (new version)` : "Issue a certificate";
  $("issue-sub").textContent = entry ? "Edit the fields, then submit. The old version will be superseded." : "Sample values are fictional.";
  $("issue-btn").textContent = entry ? "Reissue certificate" : "Issue certificate";
  $("issue-reset").hidden = !entry;
  fillForm(entry ? entry.fields : SAMPLE);
  say("i-status", ""); $("i-result").replaceChildren();
}
fillForm(SAMPLE);
$("issue-reset").onclick = () => setReissue(null);

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(form));
  const btn = $("issue-btn");
  btn.disabled = true;
  say("i-status", "Signing and rendering…", "busy");
  $("i-result").replaceChildren();
  try {
    const r = await post(reissueOf ? `/api/registry/${encodeURIComponent(reissueOf)}/reissue` : "/api/issue", data);
    say("i-status", "");
    $("i-result").replaceChildren(el("div", { class: "issued" },
      el("h3", { text: `Issued: ${r.doc_id}, version ${r.version}` }),
      el("img", { src: r.png_url, alt: "Preview of the issued certificate" }),
      el("div", { class: "row" },
        el("a", { class: "btn primary", href: r.png_url, download: "" , text: "Download PNG" }),
        el("a", { class: "btn", href: r.pdf_url, download: "", text: "Download PDF" }))));
    reissueOf = null;
  } catch (err) { say("i-status", "Couldn't issue the certificate. " + err.message, "err"); }
  finally { btn.disabled = false; }
});

/* ---------- registry ---------- */
async function loadRegistry() {
  say("r-status", "Loading registry…", "busy");
  try {
    const list = await api("/api/registry");
    say("r-status", list.length ? "" : "No certificates issued yet.", "muted");
    $("r-list").replaceChildren(...list.map(entryCard));
  } catch (e) {
    $("r-list").replaceChildren();
    say("r-status", "Couldn't load the registry. " + e.message, "err");
  }
}
$("reg-refresh").onclick = loadRegistry;

function entryCard(en) {
  const f = en.fields;
  const actions = en.status === "active" ? [
    el("button", { type: "button", class: "btn danger", text: "Revoke", onclick: async () => {
      if (!confirm(`Revoke ${en.doc_id} (${f.name})? Verifying it will report it as revoked.`)) return;
      try { await post(`/api/registry/${encodeURIComponent(en.doc_id)}/revoke`, {}); } catch (e) { say("r-status", "Couldn't revoke. " + e.message, "err"); return; }
      loadRegistry();
    } }),
    el("button", { type: "button", class: "btn", text: "Reissue", onclick: () => { setReissue(en); showTab($("tab-issue")); } }),
  ] : [];
  return el("article", { class: "entry" },
    el("div", { class: "row spread" }, el("span", { class: "t", text: f.name }), chip(en.status, en.status)),
    el("div", { class: "d", text: `Student ID ${f.student_id} | ${en.doc_id} v${en.version} | issued ${en.issued_at}` }),
    el("div", { class: "row" },
      el("a", { href: en.png_url, text: "PNG" }), el("a", { href: en.pdf_url, text: "PDF" }), actions));
}

/* ---------- health ---------- */
api("/api/health").then(
  (h) => { $("health").textContent = `Offline mode: on-device OCR (${h.ocr_engine})`; },
  () => { $("health").textContent = "Server status unavailable."; });
