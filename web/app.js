// The Harness Gateway app: sign in or sign up, then the tenant's providers, harnesses, requests,
// sessions and members; the deployer's dashboard, tenants and workers. Every action is a call to
// the same routes any client uses. No framework, no build step.
const $ = (s) => document.querySelector(s);
const state = { key: sessionStorage.getItem("hg.key") || "", kind: "", me: null, tab: "", health: null, window: 30 };
const h = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else if (k === "html") e.innerHTML = v; else e.setAttribute(k, v); } for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(k ?? "")); return e; };
const svg = (tag, attrs = {}, ...kids) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else e.setAttribute(k, v); } for (const k of kids.flat()) e.append(k instanceof Node ? k : document.createTextNode(k ?? "")); return e; };

async function api(method, path, body, raw) {
  const headers = { Authorization: "Bearer " + state.key };
  let payload = body;
  if (body && !(body instanceof Blob) && !(body instanceof FormData)) { headers["content-type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(path, { method, headers, body: payload });
  if (raw) return r;
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = { detail: text }; }
  if (!r.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : r.status);
  return data;
}
const fail = (e) => h("div", { class: "err" }, String(e.message || e));
const tag = (text, cls = "") => h("span", { class: "tag " + cls }, text);
const when = (t) => t ? new Date(t * 1000).toLocaleString() : "";
const num = (n) => n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(Math.round(n * 10) / 10);
const hours = (s) => s >= 3600 ? (s / 3600).toFixed(1) + " h" : s >= 60 ? Math.round(s / 60) + " min" : Math.round(s) + " s";
const bytes = (b) => b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB" : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : b + " B";

async function boot() {
  state.health = await (await fetch("/healthz")).json();
  $("#edition").textContent = state.health.signup === "open" ? "cloud" : "self-hosted";
  if (!state.key) return login();
  try {
    if (state.key.startsWith("hgd_")) { await api("GET", "/v1/fleet"); state.kind = "deployer"; state.me = { name: "deployer" }; }
    else { state.me = await api("GET", "/v1/me"); state.kind = state.me.role; }
  } catch (e) { sessionStorage.removeItem("hg.key"); state.key = ""; return login(fail(e)); }
  $("#who").textContent = state.kind === "deployer" ? "deployer" : `${state.me.name} · ${state.me.tenant} · ${state.me.role}`;
  render();
}

// sign in, sign up
function login(err) {
  $("#nav").replaceChildren();
  $("#who").replaceChildren();
  const signup = location.hash === "#signup" && state.health.signup === "open";
  const brand = h("div", { class: "brand" }, h("img", { src: "/web/picky.svg", alt: "" }), h("div", {}, h("b", {}, "Harness Gateway"), h("span", {}, "Coding agents, sandboxed, behind the OpenAI Responses API.")));
  const keyIn = h("input", { placeholder: "paste an API key (hg_… or the deployer key hgd_…)", size: "52", type: "password" });
  const go = () => { state.key = keyIn.value.trim(); sessionStorage.setItem("hg.key", state.key); boot(); };
  keyIn.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  const form = h("div", { class: "card" }, h("h2", {}, "Sign in"), err || "",
    h("div", { class: "row" }, keyIn, h("button", { class: "act", on: { click: go } }, "Sign in")),
    h("div", { class: "dim" }, "A member's key reaches their tenant; the deployer's key reaches the platform."));
  const parts = [brand];
  if (state.health.signup === "open") {
    const t = h("input", { placeholder: "tenant name (lowercase)" }), o = h("input", { placeholder: "your member name" }), out = h("div");
    const card = h("div", { class: "card" }, h("h2", {}, "Create a tenant"), h("div", { class: "dim" }, "A tenant is your organization: its providers, its packages, its members. You become its first owner."),
      h("div", { class: "row" }, t, o, h("button", { class: "act", on: { click: async () => {
        try { const r = await api("POST", "/v1/signup", { tenant: t.value.trim(), owner: o.value.trim() });
          out.replaceChildren(h("p", {}, "Your owner key, shown once. Keep it:"), h("div", { class: "secret" }, r.key.secret),
            h("p", {}, h("button", { class: "act", on: { click: () => { state.key = r.key.secret; sessionStorage.setItem("hg.key", state.key); location.hash = ""; boot(); } } }, "Continue as " + r.owner)));
        } catch (e) { out.replaceChildren(fail(e)); } } } }, "Create")), out);
    parts.push(...(signup ? [card, form] : [form, card]));
  } else parts.push(form);
  $("#main").replaceChildren(h("div", { class: "login" }, ...parts));
}

const TABS = { owner: ["Providers", "Harnesses", "Requests", "Sessions", "Members"], member: ["Providers", "Harnesses", "Requests", "Sessions", "Members"], deployer: ["Dashboard", "Tenants", "Workers"] };
const VIEWS = { Providers: providers, Harnesses: harnesses, Requests: requests, Sessions: sessions, Members: members, Dashboard: dashboard, Tenants: tenants, Workers: workers };
function render() {
  const tabs = TABS[state.kind];
  state.tab = tabs.includes(state.tab) ? state.tab : tabs[0];
  $("#nav").replaceChildren(...tabs.map(t => h("button", { class: t === state.tab ? "on" : "", on: { click: () => { state.tab = t; render(); } } }, t)),
    h("button", { on: { click: () => { sessionStorage.removeItem("hg.key"); state.key = ""; login(); } } }, "Sign out"));
  VIEWS[state.tab]().then(el => $("#main").replaceChildren(el)).catch(e => $("#main").replaceChildren(fail(e)));
}

// the tenant
async function providers() {
  const list = (await api("GET", "/v1/providers")).data;
  const name = h("input", { placeholder: "name" }), url = h("input", { placeholder: "https://api.deepseek.com/anthropic", size: "34" }),
    apiSel = h("select", {}, ...["anthropic-messages", "openai-chat", "openai-responses", "none"].map(a => h("option", {}, a))), key = h("input", { placeholder: "key (sealed on arrival)", type: "password", size: "30" }), out = h("div");
  const rows = list.map(p => h("tr", {}, h("td", {}, h("b", {}, p.name)), h("td", {}, p.url), h("td", {}, p.api), h("td", {}, state.kind === "owner" ? h("button", { class: "quiet danger", on: { click: async () => { await api("DELETE", "/v1/providers/" + p.name); render(); } } }, "remove") : "")));
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Providers"), h("div", { class: "dim" }, "A model endpoint, its API shape and its key. The key never enters a sandbox; the gateway swaps a per-turn token for it."),
      h("table", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "url"), h("th", {}, "api"), h("th")), ...rows)),
    state.kind === "owner" ? h("div", { class: "card" }, h("h2", {}, "Add a provider"), h("div", { class: "row" }, name, url, apiSel, key,
      h("button", { class: "act", on: { click: async () => { try { await api("PUT", "/v1/providers/" + name.value.trim(), { url: url.value.trim(), api: apiSel.value, key: key.value }); render(); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Add")), out,
      h("div", { class: "dim" }, "The catalog's packages expect providers named deepseek (Anthropic shape), deepseek-openai and openai (chat shape) or openai-responses; name yours in the request's model path otherwise.")) : "");
}

async function harnesses() {
  const [list, catalog] = await Promise.all([api("GET", "/v1/harnesses"), api("GET", "/v1/catalog")]);
  const rows = list.data.map(hn => h("tr", {}, h("td", {}, h("b", {}, hn.name)), h("td", {}, hn.description), h("td", {}, `${hn.defaults.provider || "—"} / ${hn.defaults.model || "—"}`),
    h("td", {}, h("span", { class: "tag" }, hn.version.slice(0, 8)), " ", h("span", { class: "dim" }, `${hn.versions.length}`)),
    h("td", {}, state.kind === "owner" ? h("button", { class: "quiet danger", on: { click: async () => { await api("DELETE", "/v1/harnesses/" + hn.name); render(); } } }, "remove") : "")));
  const pick = h("select", {}, ...catalog.data.map(c => h("option", { value: c.name }, `${c.name} — ${c.description.slice(0, 70)}`))), into = h("input", { placeholder: "name in your tenant" }), out = h("div");
  const file = h("input", { type: "file", accept: ".tgz,.tar.gz,.tar" }), upName = h("input", { placeholder: "name" }), out2 = h("div");
  const cat = h("table", {}, h("tr", {}, h("th", {}, "package"), h("th", {}, "verified"), h("th", {}, "key variable"), h("th", {}, "note")),
    ...catalog.data.map(c => h("tr", {}, h("td", {}, c.name), h("td", {}, c.verified.passed !== undefined ? tag(`${c.verified.passed}/9 checks`, c.verified.passed === 9 ? "ok" : "") : tag("template")), h("td", {}, c.provider_env.key || "—"), h("td", { class: "dim" }, c.notes?.[0] || ""))));
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Harnesses"), h("div", { class: "dim" }, "Your packages: install.sh, request.sh, response.sh and seeds. Request with model = the name, or name/provider/model."),
      h("table", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "description"), h("th", {}, "defaults"), h("th", {}, "version · count"), h("th")), ...rows)),
    state.kind === "owner" ? h("div", { class: "card" }, h("h2", {}, "Add a harness"), h("h3", {}, "fork from the catalog"), h("div", { class: "row" }, pick, into,
      h("button", { class: "act", on: { click: async () => { try { await api("PUT", "/v1/harnesses/" + (into.value.trim() || pick.value), { catalog: pick.value }); render(); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Fork")), out,
      h("h3", {}, "or upload a package archive"), h("div", { class: "row" }, upName, file, h("button", { class: "act", on: { click: async () => {
        try { const r = await api("PUT", "/v1/harnesses/" + upName.value.trim(), file.files[0], true); if (!r.ok) throw new Error((await r.json()).detail); render(); } catch (e) { out2.replaceChildren(fail(e)); } } } }, "Upload")), out2) : "",
    h("div", { class: "card" }, h("h2", {}, "Catalog"), h("div", { class: "dim" }, "Twenty-two packages, each run through nine live checks on the provider named."), cat));
}

async function requests() {
  const hs = (await api("GET", "/v1/harnesses")).data;
  const model = h("input", { placeholder: "harness or harness/provider/model", list: "hs", size: "36" }), input = h("textarea", { placeholder: "the task" }), prev = h("input", { placeholder: "previous_response_id (optional)", size: "40" }), instr = h("input", { placeholder: "instructions (optional)", size: "40" }), out = h("div");
  const dl = h("datalist", { id: "hs" }, ...hs.map(x => h("option", { value: x.name })));
  const run = async () => {
    out.replaceChildren(h("div", { class: "dim" }, "running…"), h("pre", { id: "live" }));
    const body = { model: model.value.trim(), input: input.value, stream: true };
    if (prev.value.trim()) body.previous_response_id = prev.value.trim();
    if (instr.value.trim()) body.instructions = instr.value.trim();
    const r = await api("POST", "/v1/responses", body, true);
    if (!r.ok) return out.replaceChildren(fail(new Error((await r.json()).detail)));
    const sid = r.headers.get("X-Session-Id");
    const steer = h("input", { placeholder: "steer the running turn", size: "40" }), steered = h("span", { class: "dim" });
    out.append(h("div", { class: "row" }, steer, h("button", { class: "quiet", on: { click: async () => { try { await api("POST", `/v1/sessions/${sid}/interrupt`, { input: steer.value }); steered.textContent = "steer delivered"; steer.value = ""; } catch (e) { steered.replaceChildren(fail(e)); } } } }, "Steer"), steered));
    const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "", final = null;
    while (true) { const { value, done } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true });
      let i; while ((i = buf.indexOf("\n\n")) >= 0) { const ev = buf.slice(0, i); buf = buf.slice(i + 2); const line = ev.split("\n").find(l => l.startsWith("data: ")); if (!line) continue; const d = JSON.parse(line.slice(6));
        if (d.type === "response.output_text.delta") $("#live").textContent += d.delta; if (d.type.startsWith("response.") && d.response && !["response.created", "response.in_progress"].includes(d.type)) final = d.response; } }
    if (final) { out.append(h("h3", {}, `response · ${final.status}`), h("pre", {}, final.output[0].content[0].text || "(empty)"), h("div", { class: "dim" }, `response ${final.id} · session ${final.metadata.session_id} · `, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); session(final.metadata.session_id); } } }, "open the session"))); prev.value = final.id; }
  };
  return h("div", {}, dl, h("div", { class: "card" }, h("h2", {}, "New request"), h("div", { class: "dim" }, "POST /v1/responses, streamed. The package's stdout appears as it is written; the response is what the package returned. Run again with the previous response id filled in to continue the session."),
    h("div", { class: "row" }, model, prev), h("div", { class: "row" }, instr), input, h("div", { class: "row" }, h("button", { class: "act", on: { click: run } }, "Run")), out));
}

async function sessions() {
  const list = (await api("GET", "/v1/sessions")).data.reverse();
  const rows = list.map(s => h("tr", {}, h("td", {}, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); session(s.id); } } }, s.id.slice(0, 18) + "…")), h("td", {}, s.harness), h("td", {}, s.member), h("td", {}, tag(s.status, s.status === "running" ? "run" : "")), h("td", {}, s.responses.length), h("td", {}, when(s.created_at))));
  const scope = state.kind === "owner" ? "every member's sessions in the tenant" : "your sessions";
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Sessions"), h("div", { class: "dim" }, `As ${state.me.role}, you see ${scope}. Open one for its turns, raw streams, trace and workspace.`),
    h("table", {}, h("tr", {}, h("th", {}, "session"), h("th", {}, "harness"), h("th", {}, "member"), h("th", {}, "status"), h("th", {}, "turns"), h("th", {}, "created")), ...rows)));
}

async function session(sid) {
  const s = await api("GET", "/v1/sessions/" + sid);
  const turns = await Promise.all(s.responses.map(rid => api("GET", `/v1/responses/${rid}?detail=true`)));
  const steer = h("input", { placeholder: "steer the running turn", size: "40" }), out = h("div");
  const blocks = turns.map(t => h("div", { class: "card" }, h("div", { class: "row" }, h("b", {}, `turn ${t.metadata.turn}`), tag(t.status, t.status === "completed" ? "ok" : t.status === "in_progress" ? "run" : "bad"), h("span", { class: "dim" }, t.id), h("span", { class: "dim" }, t.model),
      t.status === "in_progress" ? h("button", { class: "quiet danger", on: { click: async () => { await api("POST", `/v1/responses/${t.id}/cancel`); session(sid); } } }, "cancel") : "",
      h("a", { class: "quiet", href: "#", on: { click: async (e) => { e.preventDefault(); const caps = (await api("GET", `/v1/responses/${t.id}/captures`)).data; e.target.replaceWith(h("span", { class: "dim" }, caps.length ? "captures: " + caps.join(", ") : "no captures")); } } }, "captures")),
    h("h3", {}, "response"), h("pre", {}, t.output[0].content[0].text || "(empty)"), h("h3", {}, "request.sh stdout"), h("pre", {}, t.stdout || "(empty)"), t.stderr ? [h("h3", {}, "stderr"), h("pre", {}, t.stderr)] : "", t.error ? h("div", { class: "err" }, t.error.message) : ""));
  const trace = await api("GET", `/v1/sessions/${sid}/trace`);
  $("#main").replaceChildren(h("div", { class: "card" }, h("div", { class: "row" }, h("button", { class: "quiet", on: { click: () => { state.tab = "Sessions"; render(); } } }, "← sessions"), h("b", {}, sid), tag(s.status, s.status === "running" ? "run" : ""), h("span", { class: "dim" }, `${s.harness} · ${s.member} · version ${s.version.slice(0, 8)}`),
      s.stored ? h("a", { class: "quiet", href: `/v1/sessions/${sid}/archive`, on: { click: async (e) => { e.preventDefault(); const r = await api("GET", `/v1/sessions/${sid}/archive`, null, true); const u = URL.createObjectURL(await r.blob()); const a = h("a", { href: u, download: `${sid}.tar.gz` }); a.click(); } } }, "download workspace") : h("span", { class: "dim" }, "stateless"),
      s.status !== "running" ? h("button", { class: "quiet danger", on: { click: async () => { await api("DELETE", `/v1/sessions/${sid}`); state.tab = "Sessions"; render(); } } }, "delete") : ""),
    s.status === "running" ? h("div", { class: "row" }, steer, h("button", { class: "act", on: { click: async () => { try { await api("POST", `/v1/sessions/${sid}/interrupt`, { input: steer.value }); out.replaceChildren(h("div", { class: "dim" }, "steer delivered")); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Steer"), out) : ""),
    ...blocks, h("div", { class: "card" }, h("h2", {}, "Trace"), h("pre", {}, trace.data.map(t => `${when(t.at)}  ${t.kind.padEnd(9)} ${t.response}${t.kind === "request" || t.kind === "interrupt" ? "  " + JSON.stringify(t.body.input).slice(0, 120) : ""}`).join("\n"))));
}

async function members() {
  const [ms, ks] = await Promise.all([api("GET", "/v1/members").catch(() => ({ data: [] })), api("GET", "/v1/keys")]);
  const name = h("input", { placeholder: "member name" }), role = h("select", {}, h("option", {}, "member"), h("option", {}, "owner")), out = h("div");
  const keyFor = h("input", { placeholder: "member", value: state.me.name }), label = h("input", { placeholder: "label (laptop, ci…)" }), out2 = h("div");
  return h("div", {}, state.kind === "owner" ? h("div", { class: "card" }, h("h2", {}, "Members"), h("table", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "role"), h("th", {}, "since")), ...ms.data.map(m => h("tr", {}, h("td", {}, m.name), h("td", {}, m.role), h("td", {}, when(m.created))))),
      h("h3", {}, "add a member"), h("div", { class: "row" }, name, role, h("button", { class: "act", on: { click: async () => { try { await api("POST", "/v1/members", { name: name.value.trim(), role: role.value }); render(); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Add")), out) : "",
    h("div", { class: "card" }, h("h2", {}, "API keys"), h("table", {}, h("tr", {}, h("th", {}, "id"), h("th", {}, "member"), h("th", {}, "label"), h("th", {}, "created"), h("th")),
      ...ks.data.map(k => h("tr", {}, h("td", {}, k.id), h("td", {}, k.member), h("td", {}, k.label), h("td", {}, when(k.created)), h("td", {}, k.revoked ? tag("revoked", "bad") : h("button", { class: "quiet danger", on: { click: async () => { await api("DELETE", "/v1/keys/" + k.id); render(); } } }, "revoke"))))),
      h("h3", {}, "mint a key"), h("div", { class: "row" }, keyFor, label, h("button", { class: "act", on: { click: async () => { try { const r = await api("POST", `/v1/members/${keyFor.value.trim()}/keys`, { label: label.value }); out2.replaceChildren(h("p", {}, "Shown once:"), h("div", { class: "secret" }, r.secret)); } catch (e) { out2.replaceChildren(fail(e)); } } } }, "Mint")), out2));
}

// the deployer
const tip = (el, text) => { el.addEventListener("mousemove", (e) => { const t = $("#tip"); t.textContent = text; t.style.display = "block"; t.style.left = (e.clientX + 12) + "px"; t.style.top = (e.clientY + 12) + "px"; }); el.addEventListener("mouseleave", () => { $("#tip").style.display = "none"; }); };

function columns(rows, key, fmt, title) {
  // one series of thin columns, a hairline grid, labels on the last and the highest, a tooltip per column
  const W = 720, H = 200, L = 36, R = 8, T = 18, B = 26;
  const max = Math.max(1, ...rows.map(r => r[key]));
  const step = Math.pow(10, Math.floor(Math.log10(max))); const top = Math.ceil(max / step) * step;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": title });
  root.append(svg("title", {}, title));
  for (let i = 0; i <= 2; i++) { const y = T + (H - T - B) * (1 - i / 2); root.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y, y2: y }), svg("text", { class: "axis", x: L - 6, y: y + 3, "text-anchor": "end" }, num(top * i / 2))); }
  const slot = (W - L - R) / rows.length, bw = Math.min(24, Math.max(2, slot - 2));
  const peak = rows.reduce((b, r, i) => r[key] > rows[b][key] ? i : b, 0);
  rows.forEach((r, i) => {
    const x = L + i * slot + (slot - bw) / 2, hgt = (H - T - B) * r[key] / top, y = H - B - hgt;
    const g = svg("g", {});
    g.append(svg("path", { class: "bar", d: `M${x},${H - B} V${y + 4} a4,4 0 0 1 4,-4 h${bw - 8} a4,4 0 0 1 4,4 V${H - B} Z` }));
    g.append(svg("rect", { class: "hit", x: L + i * slot, y: T, width: slot, height: H - T - B }));
    tip(g, `${r.day}: ${fmt(r[key])}`);
    root.append(g);
    if (i === peak && r[key] > 0) root.append(svg("text", { class: "label", x: x + bw / 2, y: y - 5, "text-anchor": "middle" }, fmt(r[key])));
    if (i === 0 || i === rows.length - 1 || (rows.length > 14 && i % Math.ceil(rows.length / 6) === 0)) root.append(svg("text", { class: "axis", x: x + bw / 2, y: H - 8, "text-anchor": "middle" }, r.day.slice(5)));
  });
  return root;
}

function bars(rows, name, key, fmt) {
  const max = Math.max(1, ...rows.map(r => r[key]));
  return h("div", { class: "bars" }, ...rows.slice(0, 8).map(r => { const el = h("div", { class: "r" }, h("span", { class: "n" }, r[name]), h("div", {}, h("div", { class: "b", style: `width:${Math.max(2, 100 * r[key] / max)}%` })), h("span", { class: "v" }, fmt(r[key]))); tip(el, `${r[name]}: ${fmt(r[key])}`); return el; }),
    rows.length === 0 ? h("div", { class: "dim" }, "nothing yet") : "");
}

async function dashboard() {
  const [fleet, usage] = await Promise.all([api("GET", "/v1/fleet"), api("GET", `/v1/usage?days=${state.window}`)]);
  const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));
  const pick = (d, label) => h("button", { class: "quiet" + (state.window === d ? " on" : ""), on: { click: () => { state.window = d; render(); } } }, label);
  const t = usage.totals, st = usage.statuses;
  return h("div", {},
    h("div", { class: "card" }, h("div", { class: "row" }, h("h2", { style: "margin:0" }, "Platform"), h("span", { class: "dim" }, "counts and sizes only: never a tenant's prompts, output, packages or keys")),
      h("div", { class: "stats", style: "margin-top:12px" }, stat(fleet.tenants, "tenants"), stat(fleet.workers, "workers alive"), stat(fleet.slots, "slots"), stat(fleet.running, "running"), stat(fleet.queued, "queued"), stat(fleet.lost_recently.length, "lost recently"))),
    h("div", { class: "card" }, h("div", { class: "row" }, h("h2", { style: "margin:0" }, "Usage"), h("span", { class: "dim" }, "window:"), pick(0, "All time"), pick(30, "30 days"), pick(60, "60 days"), pick(90, "90 days")),
      h("div", { class: "stats", style: "margin-top:12px" }, stat(num(t.turns), "turns"), stat(hours(t.seconds), "sandbox time"), stat(num(t.calls), "provider calls"), stat(bytes(t.bytes_in), "sent to providers"), stat(bytes(t.bytes_out), "received"),
        stat(t.turns ? Math.round(100 * (st.completed || 0) / t.turns) + "%" : "—", "completed")),
      h("div", { class: "grid-2" },
        h("div", {}, h("h3", {}, "turns per day"), columns(usage.daily, "turns", num, "turns per day")),
        h("div", {}, h("h3", {}, "provider calls per day"), columns(usage.daily, "calls", num, "provider calls per day")),
        h("div", {}, h("h3", {}, "sandbox seconds per day"), columns(usage.daily, "seconds", hours, "sandbox seconds per day")),
        h("div", {}, h("h3", {}, "bytes received per day"), columns(usage.daily, "bytes_out", bytes, "bytes received from providers per day")))),
    h("div", { class: "grid-3" },
      h("div", { class: "card" }, h("h2", {}, "By tenant"), bars(usage.tenants, "tenant", "turns", num)),
      h("div", { class: "card" }, h("h2", {}, "By harness"), bars(usage.harnesses, "harness", "turns", num)),
      h("div", { class: "card" }, h("h2", {}, "By outcome"), bars(Object.entries(st).map(([k, v]) => ({ status: k, n: v })), "status", "n", num))),
    h("div", { class: "card" }, h("h3", {}, "as a table"), h("table", {}, h("tr", {}, h("th", {}, "day"), h("th", {}, "turns"), h("th", {}, "seconds"), h("th", {}, "calls"), h("th", {}, "bytes in"), h("th", {}, "bytes out")),
      ...usage.daily.filter(d => d.turns).slice(-14).reverse().map(d => h("tr", {}, h("td", {}, d.day), h("td", {}, d.turns), h("td", {}, d.seconds), h("td", {}, d.calls), h("td", {}, bytes(d.bytes_in)), h("td", {}, bytes(d.bytes_out)))))));
}

async function tenants() {
  const list = (await api("GET", "/v1/tenants")).data;
  const name = h("input", { placeholder: "tenant" }), owner = h("input", { placeholder: "owner member" }), limits = h("input", { placeholder: '{"max_runs": 4} (optional)', size: "30" }), out = h("div");
  const rows = list.map(t => { const lim = h("input", { value: JSON.stringify(t.limits), size: "60" }), err = h("div"); return h("tr", {}, h("td", {}, h("b", {}, t.name)), h("td", {}, tag(t.status, t.status === "active" ? "ok" : "bad")),
    h("td", {}, `${t.usage.turns} turns · ${hours(t.usage.seconds)} · ${t.usage.calls} calls · ${t.usage.running} running · ${t.usage.queued} queued`),
    h("td", {}, lim, " ", h("button", { class: "quiet", on: { click: async () => { try { await api("PATCH", "/v1/tenants/" + t.name, { limits: JSON.parse(lim.value) }); render(); } catch (e) { err.replaceChildren(fail(e)); } } } }, "save"), err),
    h("td", {}, h("button", { class: "quiet", on: { click: async () => { await api("PATCH", "/v1/tenants/" + t.name, { status: t.status === "active" ? "suspended" : "active" }); render(); } } }, t.status === "active" ? "suspend" : "activate"), " ",
      h("button", { class: "quiet danger", on: { click: async (e) => { if (e.target.dataset.sure) { await api("DELETE", "/v1/tenants/" + t.name); render(); } else { e.target.dataset.sure = "1"; e.target.textContent = "delete everything it owns?"; } } } }, "delete"))); });
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Tenants"), h("table", {}, h("tr", {}, h("th", {}, "tenant"), h("th", {}, "status"), h("th", {}, "usage"), h("th", {}, "ceilings"), h("th")), ...rows)),
    h("div", { class: "card" }, h("h2", {}, "Create a tenant"), h("div", { class: "row" }, name, owner, limits, h("button", { class: "act", on: { click: async () => {
      try { const r = await api("POST", "/v1/tenants", { name: name.value.trim(), owner: owner.value.trim(), ...(limits.value.trim() ? { limits: JSON.parse(limits.value) } : {}) });
        out.replaceChildren(h("p", {}, `Owner key for ${r.owner}, shown once. Hand it over securely:`), h("div", { class: "secret" }, r.key.secret)); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Create")), out));
}

async function workers() {
  const list = (await api("GET", "/v1/workers")).data;
  return h("div", { class: "card" }, h("h2", {}, "Workers"), h("table", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "id"), h("th", {}, "alive"), h("th", {}, "slots"), h("th", {}, "running"), h("th", {}, "version"), h("th", {}, "last seen"), h("th")),
    ...list.map(w => h("tr", {}, h("td", {}, w.name), h("td", {}, w.id), h("td", {}, tag(w.alive ? "alive" : "lost", w.alive ? "ok" : "bad")), h("td", {}, w.slots), h("td", {}, w.running), h("td", {}, w.version), h("td", {}, when(w.last_seen)),
      h("td", {}, h("button", { class: "quiet danger", on: { click: async () => { await api("DELETE", "/v1/workers/" + w.id); render(); } } }, "forget"))))),
    h("div", { class: "dim" }, "A worker joins with the join token and pulls turns. Add capacity by running the worker role on another machine."));
}
boot();
