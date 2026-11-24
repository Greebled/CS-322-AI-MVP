/*
 * FAQ Builder front end -- vanilla JavaScript, no framework.
 * All server communication goes through api() using fetch (AJAX):
 * the page never reloads; small parts of it are redrawn from JSON.
 */
"use strict";

const state = {
  docs: [],        // summaries from GET /api/docs
  current: null,   // full document from GET /api/docs/<id>
  faqs: [],        // entries from GET /api/docs/<id>/faqs
  dialogMode: "create",
};

const $ = (sel) => document.querySelector(sel);

/* ---------------- AJAX helper ---------------- */
async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, options);
  } catch (e) {
    throw new Error("Can't reach the server. Check that the containers are running.");
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `Request failed (${res.status}).`);
    err.details = data && data.details;
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ---------------- DOM helpers (textContent only: no HTML injection) ---------------- */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function plural(n, word) { return `${n} ${word}${n === 1 ? "" : "s"}`; }

function toast(message, kind = "info") {
  const t = el("div", { class: `toast toast-${kind}`, text: message });
  $("#toasts").append(t);
  setTimeout(() => { t.classList.add("leaving"); setTimeout(() => t.remove(), 300); }, 3800);
}

/* ---------------- highlighting (mirrors faq_logic.tokenize) ---------------- */
const STOPWORDS = new Set(`a an the and or but if then else of to in on at by for with from as is are was
were be been being do does did doing can could should would will shall may might must i you he she it we
they me my your our their this that these those there here what which who whom whose when where why how
not no yes so than too very just about into over under again once all any both each few more most other
some such only own same up down out off also its am have has had get got s t d ll re ve m don doesn didn
isn aren wasn weren won`.split(/\s+/));

function stem(w) { return w.length > 3 && w.endsWith("s") && !w.endsWith("ss") ? w.slice(0, -1) : w; }

function keyTerms(text) {
  const words = text.toLowerCase().match(/[a-z0-9]+/g) || [];
  return new Set(words.filter((w) => !STOPWORDS.has(w)).map(stem));
}

function highlighted(text, terms) {
  const frag = document.createDocumentFragment();
  for (const part of text.split(/([A-Za-z0-9]+)/)) {
    if (!part) continue;
    const lower = part.toLowerCase();
    const isWord = /^[A-Za-z0-9]+$/.test(part);
    if (isWord && !STOPWORDS.has(lower) && terms.has(stem(lower))) frag.append(el("mark", { text: part }));
    else frag.append(document.createTextNode(part));
  }
  return frag;
}

/* ---------------- shared answer pieces ---------------- */
const PROVIDER_LABELS = {
  claude: ["Answered by Claude", "badge badge-claude"],
  extractive: ["Quoted by keyword match", "badge"],
  manual: ["Written by you", "badge"],
  edited: ["Edited by you", "badge"],
};

function providerBadge(faq) {
  const [label, cls] = PROVIDER_LABELS[faq.provider] || [faq.provider, "badge"];
  return el("span", { class: cls, title: faq.model || null, text: label });
}

function sourcesBlock(sources, terms, open = false) {
  if (!sources || !sources.length) return null;
  return el("details", { class: "sources", open },
    el("summary", { text: `Show the ${plural(sources.length, "passage")} this came from` }),
    el("ol", { class: "source-list" },
      sources.map((s) => el("li", {},
        el("blockquote", { class: "source" },
          el("span", { class: "source-label", text: `Section ${s.index + 1} of the document` }),
          highlighted(s.text, terms))))));
}

/* ---------------- documents ---------------- */
async function loadDocs(selectId) {
  try {
    state.docs = await api("GET", "/api/docs");
  } catch (err) {
    $("#doc-list").replaceChildren(el("li", { class: "doc-list-empty", text: err.message }));
    return;
  }
  renderDocList();
  if (selectId) return openDoc(selectId);
  if (!state.docs.length) return showEmpty();
  if (!state.current) return openDoc(state.docs[0].id);
}

function renderDocList() {
  const list = $("#doc-list");
  list.replaceChildren();
  if (!state.docs.length) {
    list.append(el("li", { class: "doc-list-empty", text: "No documents yet." }));
    return;
  }
  for (const d of state.docs) {
    const active = state.current && state.current.id === d.id;
    list.append(el("li", {},
      el("button", {
        class: "doc-item" + (active ? " active" : ""),
        type: "button",
        "aria-current": active ? "page" : null,
        onclick: () => openDoc(d.id),
      },
        el("span", { class: "doc-item-title", text: d.title }),
        el("span", { class: "doc-item-meta", text: plural(d.faq_count, "saved answer") }))));
  }
}

function showEmpty() {
  state.current = null;
  $("#doc-view").hidden = true;
  $("#empty-view").hidden = false;
}

async function openDoc(id) {
  try {
    const [doc, faqs] = await Promise.all([
      api("GET", `/api/docs/${id}`),
      api("GET", `/api/docs/${id}/faqs`),
    ]);
    state.current = doc;
    state.faqs = faqs;
  } catch (err) {
    toast(err.message, "error");
    return;
  }
  $("#empty-view").hidden = true;
  $("#doc-view").hidden = false;
  $("#answer-slot").replaceChildren();
  $("#ask-error").textContent = "";
  $("#ask-input").value = "";
  $("#faq-filter").value = "";
  renderDocHeader();
  renderDocList();
  renderFaqs();
}

function renderDocHeader() {
  const d = state.current;
  $("#doc-title").textContent = d.title;
  const words = d.content.trim().split(/\s+/).length;
  $("#doc-meta").textContent =
    `${words.toLocaleString()} words, split into ${plural(d.chunk_count, "section")} for searching`;
}

function updateDocCount() {
  const summary = state.docs.find((d) => d.id === state.current.id);
  if (summary) summary.faq_count = state.faqs.length;
  renderDocList();
}

/* ---------------- asking ---------------- */
async function handleAsk(event) {
  event.preventDefault();
  const input = $("#ask-input");
  const question = input.value.trim();
  const errorBox = $("#ask-error");

  if (question.length < 3) {
    errorBox.textContent = question ? "That question is too short to answer." : "Type a question first.";
    input.setAttribute("aria-invalid", "true");
    input.focus();
    return;
  }
  errorBox.textContent = "";
  input.removeAttribute("aria-invalid");
  setAsking(true);

  $("#answer-slot").replaceChildren(
    el("div", { class: "answer-card loading" },
      el("p", { class: "answer-q", text: question }),
      el("p", { class: "loading-text", text: "Reading the document and drafting an answer…" }),
      el("div", { class: "bar", role: "progressbar", "aria-label": "Waiting for the answer" })));

  try {
    const { faq, cached, notice } = await api("POST", `/api/docs/${state.current.id}/faqs`, { question });
    renderAnswer(faq, cached, notice);
    if (!cached) {
      state.faqs.unshift(faq);
      sortFaqs();
      updateDocCount();
    }
    renderFaqs();
    input.value = "";
  } catch (err) {
    $("#answer-slot").replaceChildren();
    errorBox.textContent = (err.details && err.details.question) || err.message;
  } finally {
    setAsking(false);
    input.focus();
  }
}

function setAsking(busy) {
  $("#ask-input").disabled = busy;
  const btn = $("#ask-btn");
  btn.disabled = busy;
  btn.textContent = busy ? "Asking…" : "Ask";
}

function renderAnswer(faq, cached, notice) {
  const terms = keyTerms(faq.question);
  $("#answer-slot").replaceChildren(
    el("article", { class: "answer-card is-new" },
      el("p", { class: "answer-q", text: faq.question }),
      el("p", { class: "answer-text" + (faq.found ? "" : " not-found"), text: faq.answer }),
      el("div", { class: "answer-meta" },
        providerBadge(faq),
        cached ? el("span", { class: "badge badge-cached", text: "Already saved, no new AI call" }) : null),
      notice ? el("p", { class: "notice", text: notice }) : null,
      sourcesBlock(faq.sources, terms, true)));
}

/* ---------------- saved FAQ list ---------------- */
function sortFaqs() {
  state.faqs.sort((a, b) =>
    (b.pinned - a.pinned) || (b.created_at > a.created_at ? 1 : b.created_at < a.created_at ? -1 : 0));
}

function renderFaqs() {
  const filter = $("#faq-filter").value.trim().toLowerCase();
  const visible = state.faqs.filter((f) =>
    !filter || f.question.toLowerCase().includes(filter) || f.answer.toLowerCase().includes(filter));

  $("#faq-count").textContent = state.faqs.length ? `(${state.faqs.length})` : "";
  $("#faq-list").replaceChildren(...visible.map(faqItem));

  const empty = $("#faq-empty");
  if (!state.faqs.length) {
    empty.textContent = "No saved answers yet. Ask a question above and it will appear here.";
    empty.hidden = false;
  } else if (!visible.length) {
    empty.textContent = `No saved questions match “${filter}”.`;
    empty.hidden = false;
  } else {
    empty.hidden = true;
  }
}

function faqItem(faq) {
  const body = el("div", { class: "faq-body" });
  fillFaqBody(body, faq);
  return el("li", { class: "faq" + (faq.pinned ? " pinned" : ""), "data-id": faq.id },
    el("details", {},
      el("summary", {},
        el("span", { class: "faq-q", text: faq.question }),
        faq.pinned ? el("span", { class: "pin-badge", text: "Pinned" }) : null),
      body));
}

function fillFaqBody(body, faq) {
  const terms = keyTerms(faq.question);
  body.replaceChildren(
    el("p", { class: "faq-a" + (faq.found ? "" : " not-found"), text: faq.answer }),
    el("div", { class: "faq-meta" }, providerBadge(faq)),
    sourcesBlock(faq.sources, terms),
    el("div", { class: "faq-actions" },
      el("button", { class: "btn btn-ghost btn-small", type: "button", text: faq.pinned ? "Unpin" : "Pin to top",
        onclick: () => togglePin(faq) }),
      el("button", { class: "btn btn-ghost btn-small", type: "button", text: "Edit answer",
        onclick: () => startEdit(body, faq) }),
      faq.provider !== "manual"
        ? el("button", { class: "btn btn-ghost btn-small", type: "button", text: "Ask again",
            onclick: (e) => regenerate(faq, e.currentTarget) })
        : null,
      el("button", { class: "btn btn-ghost btn-small btn-danger", type: "button", text: "Delete",
        onclick: () => deleteFaq(faq) })));
}

function replaceFaq(updated) {
  const i = state.faqs.findIndex((f) => f.id === updated.id);
  if (i >= 0) state.faqs[i] = updated;
}

async function togglePin(faq) {
  try {
    const updated = await api("PUT", `/api/faqs/${faq.id}`, { pinned: !faq.pinned });
    replaceFaq(updated);
    sortFaqs();
    renderFaqs();
    toast(updated.pinned ? "Pinned to top." : "Unpinned.");
  } catch (err) { toast(err.message, "error"); }
}

function startEdit(body, faq) {
  const textarea = el("textarea", { "aria-label": "Answer", maxlength: "4000" });
  textarea.value = faq.answer;
  const error = el("p", { class: "field-error", role: "alert" });
  const save = el("button", { class: "btn btn-primary btn-small", type: "submit", text: "Save answer" });

  const form = el("form", { class: "faq-edit", onsubmit: async (e) => {
    e.preventDefault();
    const answer = textarea.value.trim();
    if (!answer) { error.textContent = "The answer can't be empty."; return; }
    save.disabled = true;
    save.textContent = "Saving…";
    try {
      const updated = await api("PUT", `/api/faqs/${faq.id}`, { answer });
      replaceFaq(updated);
      fillFaqBody(body, updated);
      toast("Answer saved.");
    } catch (err) {
      error.textContent = (err.details && err.details.answer) || err.message;
      save.disabled = false;
      save.textContent = "Save answer";
    }
  } },
    textarea, error,
    el("div", { class: "faq-actions" }, save,
      el("button", { class: "btn btn-ghost btn-small", type: "button", text: "Cancel",
        onclick: () => fillFaqBody(body, faq) })));
  body.replaceChildren(form);
  textarea.focus();
}

async function regenerate(faq, button) {
  button.disabled = true;
  button.textContent = "Asking…";
  try {
    const { faq: updated, notice } = await api("POST", `/api/faqs/${faq.id}/regenerate`);
    replaceFaq(updated);
    renderFaqs();
    const item = document.querySelector(`.faq[data-id="${updated.id}"] details`);
    if (item) item.open = true;
    toast(notice || "Answer refreshed.");
  } catch (err) {
    toast(err.message, "error");
    button.disabled = false;
    button.textContent = "Ask again";
  }
}

async function deleteFaq(faq) {
  if (!confirm(`Delete the saved answer to “${faq.question}”?`)) return;
  try {
    await api("DELETE", `/api/faqs/${faq.id}`);
    state.faqs = state.faqs.filter((f) => f.id !== faq.id);
    renderFaqs();
    updateDocCount();
    toast("Answer deleted.");
  } catch (err) { toast(err.message, "error"); }
}

/* ---------------- create / edit document dialog ---------------- */
const CONTENT_MIN = 50;
const CONTENT_MAX = 50000;

function openDocDialog(mode, prefill = {}) {
  state.dialogMode = mode;
  $("#doc-dialog-title").textContent = mode === "edit" ? "Edit document" : "New document";
  $("#doc-save-btn").textContent = mode === "edit" ? "Save changes" : "Save document";
  $("#doc-title-input").value = prefill.title || "";
  $("#doc-content-input").value = prefill.content || "";
  clearFieldErrors();
  updateCounter();
  $("#doc-dialog").showModal();
  $("#doc-title-input").focus();
}

function clearFieldErrors() {
  document.querySelectorAll("#doc-form [data-error-for]").forEach((p) => { p.textContent = ""; });
  document.querySelectorAll("#doc-form [aria-invalid]").forEach((f) => f.removeAttribute("aria-invalid"));
}

function showFieldErrors(errors) {
  for (const [field, message] of Object.entries(errors)) {
    const box = document.querySelector(`#doc-form [data-error-for="${field}"]`);
    if (box) box.textContent = message;
    const input = $(`#doc-${field}-input`);
    if (input) input.setAttribute("aria-invalid", "true");
  }
}

function updateCounter() {
  const n = $("#doc-content-input").value.length;
  const counter = $("#content-counter");
  counter.textContent = `${n.toLocaleString()} / ${CONTENT_MAX.toLocaleString()}`;
  counter.classList.toggle("over", n > CONTENT_MAX);
}

function validateDocForm(title, content) {
  const errors = {};
  if (!title) errors.title = "Give the document a title.";
  if (!content) errors.content = "Paste the document text.";
  else if (content.length < CONTENT_MIN) errors.content = `Paste at least ${CONTENT_MIN} characters so there is something to answer from.`;
  else if (content.length > CONTENT_MAX) errors.content = `Documents are limited to ${CONTENT_MAX.toLocaleString()} characters.`;
  return errors;
}

async function handleDocSave(event) {
  event.preventDefault();
  clearFieldErrors();
  const title = $("#doc-title-input").value.trim();
  const content = $("#doc-content-input").value.trim();

  const errors = validateDocForm(title, content);   // quick client-side check...
  if (Object.keys(errors).length) { showFieldErrors(errors); return; }

  const save = $("#doc-save-btn");
  save.disabled = true;
  const label = save.textContent;
  save.textContent = "Saving…";
  try {
    const editing = state.dialogMode === "edit";
    const doc = editing
      ? await api("PUT", `/api/docs/${state.current.id}`, { title, content })
      : await api("POST", "/api/docs", { title, content });
    $("#doc-dialog").close();
    toast(editing ? "Document updated." : "Document saved. Ask it something.");
    await loadDocs(doc.id);
    $("#ask-input").focus();
  } catch (err) {
    // ...and the server validates again, since client checks can be bypassed
    if (err.details) showFieldErrors(err.details);
    else showFieldErrors({ _form: err.message });
  } finally {
    save.disabled = false;
    save.textContent = label;
  }
}

async function deleteCurrentDoc() {
  const d = state.current;
  const count = state.faqs.length;
  const extra = count ? ` and its ${plural(count, "saved answer")}` : "";
  if (!confirm(`Delete “${d.title}”${extra}? This can't be undone.`)) return;
  try {
    await api("DELETE", `/api/docs/${d.id}`);
    state.current = null;
    toast("Document deleted.");
    await loadDocs();
  } catch (err) { toast(err.message, "error"); }
}

function showDocText() {
  $("#text-dialog-title").textContent = state.current.title;
  $("#text-dialog-body").textContent = state.current.content;
  $("#text-dialog").showModal();
}

async function loadSample() {
  try {
    const res = await fetch("/static/samples/nimbus_thermostat.txt");
    const content = await res.text();
    openDocDialog("create", { title: "Nimbus Smart Thermostat user guide", content });
  } catch (err) { toast("Couldn't load the sample document.", "error"); }
}

/* ---------------- provider status ---------------- */
async function loadHealth() {
  const box = $("#provider-status");
  try {
    const h = await api("GET", "/api/health");
    const ai = h.provider.name === "claude";
    const dbOk = h.database === "ok";
    box.replaceChildren(
      el("span", { class: "dot " + (ai ? "on" : "") }),
      "Answers by ",
      el("strong", { text: ai ? `Claude (${h.provider.model})` : "keyword matching" }),
      ai ? null : el("br"),
      ai ? null : "Add an Anthropic API key in .env to enable Claude.",
      dbOk ? null : el("br"),
      dbOk ? null : el("span", { class: "dot off" }),
      dbOk ? null : "Database unreachable");
  } catch (err) {
    box.replaceChildren(el("span", { class: "dot off" }), "Server unreachable");
  }
}

/* ---------------- wiring ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  $("#new-doc-btn").addEventListener("click", () => openDocDialog("create"));
  $("#empty-new-btn").addEventListener("click", () => openDocDialog("create"));
  $("#sample-btn").addEventListener("click", loadSample);
  $("#edit-doc-btn").addEventListener("click", () => openDocDialog("edit", state.current));
  $("#delete-doc-btn").addEventListener("click", deleteCurrentDoc);
  $("#view-doc-btn").addEventListener("click", showDocText);
  $("#text-close-btn").addEventListener("click", () => $("#text-dialog").close());
  $("#doc-cancel-btn").addEventListener("click", () => $("#doc-dialog").close());
  $("#doc-form").addEventListener("submit", handleDocSave);
  $("#doc-content-input").addEventListener("input", updateCounter);
  $("#ask-form").addEventListener("submit", handleAsk);
  $("#ask-input").addEventListener("input", () => {
    $("#ask-error").textContent = "";
    $("#ask-input").removeAttribute("aria-invalid");
  });
  $("#faq-filter").addEventListener("input", renderFaqs);

  // "/" focuses the question box (unless you're already typing somewhere)
  document.addEventListener("keydown", (e) => {
    const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
    if (e.key === "/" && !typing && !$("#doc-view").hidden) {
      e.preventDefault();
      $("#ask-input").focus();
    }
  });

  loadHealth();
  loadDocs();
});
