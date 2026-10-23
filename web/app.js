// The HarnessGateway app: sign in with an account (email and password, GitHub, Google) or an API
// key, then the tenant's requests, arena, sessions, providers, harnesses and members; the
// deployer's dashboard, tenants and workers. Every action is a call to the same routes any client
// uses. No framework, no build step.
const $ = (s) => document.querySelector(s);
const state = { health: null, auth: null, key: sessionStorage.getItem("hg.key") || "", me: null, account: null, tenants: [], kind: "", page: "", window: 30, arena: null };
const h = (tag, attrs = {}, ...kids) => { const e = document.createElement(tag); for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else if (k === "html") e.innerHTML = v; else if (v !== false && v != null) e.setAttribute(k, v); } for (const k of kids.flat()) if (k != null && k !== false) e.append(k instanceof Node ? k : document.createTextNode(k)); return e; };
const svg = (tag, attrs = {}, ...kids) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs)) { if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn); else e.setAttribute(k, v); } for (const k of kids.flat()) if (k != null) e.append(k instanceof Node ? k : document.createTextNode(k)); return e; };
const ICONS = { bolt: "M13 2L4 14h7l-1 8 9-12h-7l1-8z", swords: "M3 3l7 7M21 3l-7 7M3 21l6-6M21 21l-6-6M10 14l-3 3M14 14l3 3M3 3h5M3 3v5M21 3h-5M21 3v5", clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2", plug: "M9 2v6M15 2v6M5 8h14l-1 5a6 6 0 0 1-12 0L5 8zM12 19v3", box: "M21 8l-9-5-9 5v8l9 5 9-5V8zM3 8l9 5 9-5M12 13v8", users: "M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2M9.5 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM21 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8", user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z", chart: "M3 3v18h18M7 14v4M12 9v9M17 5v13", building: "M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2", server: "M3 5h18v6H3zM3 13h18v6H3zM7 8h.01M7 16h.01", book: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z", logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9", file: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM14 2v6h6" };
const icon = (name) => svg("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }, svg("path", { d: ICONS[name] }));

async function api(method, path, body, raw) {
  const headers = state.key ? { Authorization: "Bearer " + state.key } : {};
  let payload = body;
  if (body && !(body instanceof Blob) && !(body instanceof FormData)) { headers["content-type"] = "application/json"; payload = JSON.stringify(body); }
  const r = await fetch(path, { method, headers, body: payload });
  if (raw) return r;
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = { detail: text }; }
  if (!r.ok) throw new Error(data.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : String(r.status));
  return data;
}
const fail = (e) => h("div", { class: "err" }, String(e.message || e));
const tag = (text, cls = "") => h("span", { class: "tag " + cls }, text);
const statusTag = (s) => tag(s, { completed: "ok", failed: "bad", cancelled: "bad", incomplete: "bad", in_progress: "run", queued: "run", running: "run", active: "ok", suspended: "bad", alive: "ok", lost: "bad" }[s] || "");
const when = (t) => t ? new Date(t * 1000).toLocaleString() : "";
const ago = (t) => { const s = Math.max(0, Date.now() / 1000 - t); return s < 60 ? "just now" : s < 3600 ? Math.round(s / 60) + " min ago" : s < 86400 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago"; };
const num = (n) => n >= 1e9 ? (n / 1e9).toFixed(1) + "B" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(Math.round(n * 10) / 10);
const hours = (s) => s >= 3600 ? (s / 3600).toFixed(1) + " h" : s >= 60 ? Math.round(s / 60) + " min" : Math.round(s) + " s";
const bytes = (b) => b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB" : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : b + " B";
const field = (label, input) => h("div", { class: "field" }, h("label", {}, label), input);
const copy = (text) => h("button", { class: "ghost small", on: { click: async (e) => { try { await navigator.clipboard.writeText(text); e.target.textContent = "copied"; } catch { e.target.textContent = "select it"; } } } }, "copy");

// boot: who is here
async function boot() {
  state.health = await (await fetch("/healthz")).json();
  state.auth = await (await fetch("/auth/providers")).json();
  document.title = "HarnessGateway";
  if (location.hash.startsWith("#reset=")) return login(null, "reset", location.hash.slice(7));
  if (state.key) {
    try {
      if (state.key.startsWith("hgd_")) { await api("GET", "/v1/fleet"); state.kind = "deployer"; state.me = { name: "deployer" }; }
      else { state.me = await api("GET", "/v1/me"); state.kind = state.me.role; }
      return shell();
    } catch (e) { sessionStorage.removeItem("hg.key"); state.key = ""; return login(fail(e)); }
  }
  try {
    const me = await api("GET", "/auth/me");
    state.account = me.account; state.tenants = me.tenants; state.me = { ...me.current, name: me.current.member }; state.kind = me.current.role;
    return shell();
  } catch { /* not signed in */ }
  const error = location.hash.startsWith("#error=") ? { "sign-up-closed": "Sign-up is closed on this platform. Ask an owner for an invitation.", "sign-in-cancelled": "The sign-in was cancelled." }[location.hash.slice(7)] : "";
  login(error ? h("div", { class: "notice warn" }, error) : null, location.hash === "#signup" ? "signup" : "signin");
}

// sign in, sign up, reset
function login(note, mode = "signin", resetToken = "") {
  const a = state.auth, open = a.signup === "open";
  const email = h("input", { type: "email", placeholder: "you@company.com", autocomplete: "email" }), pw = h("input", { type: "password", placeholder: mode === "signup" ? "at least 8 characters" : "password", autocomplete: mode === "signup" ? "new-password" : "current-password" }), name = h("input", { placeholder: "your name" }), out = h("div");
  const keyIn = h("input", { placeholder: "hg_… or the deployer key hgd_…", type: "password" });
  const go = async (fn) => { out.replaceChildren(); try { await fn(); } catch (e) { out.replaceChildren(fail(e)); } };
  const signedIn = (me) => { location.hash = ""; state.account = me.account; state.tenants = me.tenants; state.me = { ...me.current, name: me.current.member }; state.kind = me.current.role; shell(); };
  const idp = h("div", { class: "idp" },
    a.github ? h("a", { class: "btn quiet", href: "/auth/github" }, svg("svg", { viewBox: "0 0 24 24", width: 16, height: 16, fill: "currentColor" }, svg("path", { d: "M12 .5C5.7.5.5 5.7.5 12c0 5.1 3.3 9.4 7.9 10.9.6.1.8-.3.8-.6v-2c-3.2.7-3.9-1.4-3.9-1.4-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.7 1.3 3.4 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.4-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.8 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.2c0 .3.2.7.8.6 4.6-1.5 7.9-5.8 7.9-10.9C23.5 5.7 18.3.5 12 .5z" })), "Continue with GitHub") : null,
    a.google ? h("a", { class: "btn quiet", href: "/auth/google" }, svg("svg", { viewBox: "0 0 24 24", width: 16, height: 16 }, svg("path", { fill: "#4285F4", d: "M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.9h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.4z" }), svg("path", { fill: "#34A853", d: "M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22z" }), svg("path", { fill: "#FBBC05", d: "M6.4 13.9a6 6 0 0 1 0-3.8V7.5H3.1a10 10 0 0 0 0 9z" }), svg("path", { fill: "#EA4335", d: "M12 6c1.5 0 2.8.5 3.8 1.5l2.8-2.8A10 10 0 0 0 3.1 7.5l3.3 2.6C7.2 7.8 9.4 6 12 6z" })), "Continue with Google") : null);
  const hasIdp = a.github || a.google;
  let body;
  if (mode === "reset") {
    body = [h("h2", {}, "Set a new password"), h("p", { class: "sub" }, "Then you are signed in."), field("New password", pw),
      h("button", { class: "act", style: "margin-top:12px", on: { click: () => go(async () => signedIn(await api("POST", "/auth/reset/confirm", { token: resetToken, password: pw.value }))) } }, "Save and sign in")];
  } else if (mode === "forgot") {
    body = [h("h2", {}, "Reset your password"), h("p", { class: "sub" }, "We email you a link that is good for an hour."), field("Email", email),
      h("button", { class: "act", style: "margin-top:12px", on: { click: () => go(async () => { await api("POST", "/auth/reset", { email: email.value.trim() }); out.replaceChildren(h("div", { class: "notice ok" }, "If an account exists for that email, the link is on its way.")); }) } }, "Send the link"),
      h("div", { class: "links" }, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); login(null, "signin"); } } }, "← Back to sign in"))];
  } else if (mode === "key") {
    body = [h("h2", {}, "Sign in with an API key"), h("p", { class: "sub" }, "A member's key opens their tenant; the deployer's key opens the platform."), field("API key", keyIn),
      h("button", { class: "act", style: "margin-top:12px", on: { click: () => { state.key = keyIn.value.trim(); sessionStorage.setItem("hg.key", state.key); boot(); } } }, "Sign in"),
      h("div", { class: "links" }, h("a", { href: "#", on: { click: (e) => { e.preventDefault(); login(null, "signin"); } } }, "← Sign in with an account"))];
    keyIn.addEventListener("keydown", (e) => { if (e.key === "Enter") { state.key = keyIn.value.trim(); sessionStorage.setItem("hg.key", state.key); boot(); } });
  } else {
    const signup = mode === "signup";
    const tabs = h("div", { class: "tabs" }, h("button", { class: signup ? "" : "on", on: { click: () => login(null, "signin") } }, "Sign in"), h("button", { class: signup ? "on" : "", on: { click: () => login(null, "signup") } }, "Create account"));
    const submit = () => go(async () => {
      if (signup) {
        const r = await api("POST", "/auth/signup", { email: email.value.trim(), password: pw.value, name: name.value.trim() });
        if (r.verify) return out.replaceChildren(h("div", { class: "notice ok" }, `Check your email. We sent a verification link to ${r.email}.`), h("p", { style: "margin-top:10px" }, h("button", { class: "ghost small", on: { click: () => api("POST", "/auth/resend", { email: r.email }) } }, "Send it again")));
        signedIn(r);
      } else signedIn(await api("POST", "/auth/login", { email: email.value.trim(), password: pw.value }));
    });
    for (const el of [email, pw, name]) el.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    body = [h("h2", {}, signup ? "Create your account" : "Welcome back"), h("p", { class: "sub" }, signup ? (open ? "A tenant of your own comes with it. Invite your team after." : "Sign-up is by invitation on this platform. Use the email an owner invited.") : "Sign in to your tenant."),
      tabs, hasIdp ? idp : null, hasIdp ? h("div", { class: "or" }, "or with email") : null,
      h("div", { class: "stack" }, signup ? field("Name", name) : null, field("Email", email), field("Password", pw)),
      h("button", { class: "act", style: "margin-top:14px", on: { click: submit } }, signup ? "Create account" : "Sign in"),
      h("div", { class: "links" }, a.mail && !signup ? h("a", { href: "#", on: { click: (e) => { e.preventDefault(); login(null, "forgot"); } } }, "Forgot your password?") : h("span"), h("a", { href: "#", on: { click: (e) => { e.preventDefault(); login(null, "key"); } } }, "Use an API key instead"))];
  }
  $("#root").replaceChildren(h("div", { class: "auth" },
    h("div", { class: "side-art" },
      h("a", { class: "brand", href: "/" }, h("img", { src: "/web/picky.png", alt: "" }), "HarnessGateway"),
      h("div", {}, h("h1", {}, "Every coding agent.", h("br"), "One API. ", h("em", {}, "Sandboxed.")), h("p", {}, "Bring your providers and your harness packages. The platform runs each turn in a sandbox it owns, relays the provider calls through a gateway that holds the keys, and keeps the complete record."), h("img", { class: "mascot", src: "/web/picky.png", alt: "" })),
      h("div", { class: "muted", style: "color:#8FA3C6" }, state.health.signup === "open" ? "harnessgateway.ai" : "self-hosted", " · v", state.health.version, " · ", h("a", { href: "/docs/", style: "color:#B7C6E0" }, "Docs"))),
    h("div", { class: "form" }, h("div", {}, note, ...body, out))));
}

// the shell
const NAV = {
  member: [["Build", [["Requests", "bolt"], ["Arena", "swords"], ["Sessions", "clock"]]], ["Setup", [["Providers", "plug"], ["Harnesses", "box"]]], ["Team", [["Members", "users"], ["Account", "user"]]]],
  deployer: [["Platform", [["Dashboard", "chart"], ["Tenants", "building"], ["Workers", "server"]]]],
};
const VIEWS = { Requests: requests, Arena: arena, Sessions: sessions, Providers: providers, Harnesses: harnesses, Members: members, Account: account, Dashboard: dashboard, Tenants: tenants, Workers: workers };
function pages() { return NAV[state.kind === "deployer" ? "deployer" : "member"].flatMap(([, items]) => items.map(([p]) => p)).filter(p => p !== "Account" || state.account); }
function signOut() { sessionStorage.removeItem("hg.key"); state.key = ""; if (state.account) api("POST", "/auth/logout").catch(() => {}); state.account = null; state.me = null; state.kind = ""; location.hash = ""; boot(); }
function shell(page) {
  const all = pages();
  state.page = all.includes(page || state.page) ? (page || state.page) : all[0];
  const groups = NAV[state.kind === "deployer" ? "deployer" : "member"];
  const item = (p, ic) => h("button", { class: "item" + (p === state.page ? " on" : ""), on: { click: () => shell(p) } }, icon(ic), p);
  const switcher = state.account ? h("div", { class: "tenant" }, h("select", { on: { change: async (e) => { if (e.target.value === "+") { e.target.value = state.me.tenant; return shell("Account"); } try { const me = await api("POST", "/auth/switch", { tenant: e.target.value }); state.tenants = me.tenants; state.me = { ...me.current, name: me.current.member }; state.kind = me.current.role; shell(state.page); } catch (err) { alert(err.message); } } } },
    ...state.tenants.map(t => h("option", { value: t.tenant, selected: t.tenant === state.me.tenant }, `${t.tenant} · ${t.role}`)), h("option", { value: "+" }, "+ new tenant"))) : null;
  const side = h("aside", { class: "side" }, h("a", { class: "brand", href: "/" }, h("img", { src: "/web/picky.png", alt: "" }), "HarnessGateway"), switcher,
    ...groups.flatMap(([label, items]) => [h("div", { class: "group" }, label), ...items.filter(([p]) => all.includes(p)).map(([p, ic]) => item(p, ic))]),
    h("div", { class: "foot" }, h("b", {}, state.kind === "deployer" ? "deployer" : `${state.me.name} · ${state.kind}`), state.account ? h("span", {}, state.account.email) : h("span", {}, state.me.tenant || "the platform"), h("a", { class: "item", href: "/docs/", style: "padding:6px 0" }, icon("book"), "Docs"), h("button", { class: "item", style: "padding:6px 0", on: { click: signOut } }, icon("logout"), "Sign out")));
  const top = h("div", { class: "topbar" }, h("img", { src: "/web/picky.png", alt: "" }), h("b", {}, "HarnessGateway"), ...all.map(p => h("button", { class: p === state.page ? "on" : "", on: { click: () => shell(p) } }, p)), h("button", { on: { click: signOut } }, "Sign out"));
  const main = h("main", { class: "page" }, h("div", { class: "empty" }, "loading…"));
  $("#root").replaceChildren(h("div", { class: "shell" }, side, h("div", {}, top, main)));
  VIEWS[state.page]().then(el => main.replaceChildren(el)).catch(e => main.replaceChildren(h("div", { class: "card" }, fail(e))));
}
const head = (title, text, ...right) => h("div", { class: "page-head" }, h("div", {}, h("h1", {}, title), text ? h("p", {}, text) : null), right.length ? h("div", { class: "row" }, ...right) : null);
const isOwner = () => state.kind === "owner";

// streaming a turn
async function streamTurn(body, onDelta) {
  const r = await api("POST", "/v1/responses", { ...body, stream: true }, true);
  if (!r.ok) throw new Error((await r.json()).detail);
  const sid = r.headers.get("X-Session-Id");
  const reader = r.body.getReader(), dec = new TextDecoder(); let buf = "", final = null, rid = "";
  while (true) {
    const { value, done } = await reader.read(); if (done) break; buf += dec.decode(value, { stream: true });
    let i; while ((i = buf.indexOf("\n\n")) >= 0) { const ev = buf.slice(0, i); buf = buf.slice(i + 2); const line = ev.split("\n").find(l => l.startsWith("data: ")); if (!line) continue; const d = JSON.parse(line.slice(6));
      if (d.type === "response.created") rid = d.response.id;
      if (d.type === "response.output_text.delta") onDelta(d.delta);
      if (d.type.startsWith("response.") && d.response && !["response.created", "response.in_progress"].includes(d.type)) final = d.response; }
  }
  return { sid, rid, final };
}
const livePane = () => { const el = h("div", { class: "live" }, h("span", { class: "cursor" })); el.push = (t) => { el.insertBefore(document.createTextNode(t), el.lastChild); el.scrollTop = el.scrollHeight; }; el.done = () => el.lastChild.remove(); return el; };

// the workspace's files, after a turn
async function filesPanel(sid) {
  const list = (await api("GET", `/v1/sessions/${sid}/files`)).data;
  if (!list.length) return h("div", { class: "empty" }, "No files in the workspace yet.");
  const viewer = h("div", { class: "viewer" }, h("div", { class: "bar" }, h("span", { class: "muted" }, "pick a file")), h("pre", { class: "light" }, ""));
  const tree = h("div", { class: "tree" });
  const byDir = {};
  for (const f of list) { const i = f.path.lastIndexOf("/"); (byDir[i < 0 ? "" : f.path.slice(0, i)] ||= []).push(f); }
  let current = null;
  const show = async (f, btn) => {
    if (current) current.classList.remove("on"); current = btn; btn.classList.add("on");
    const r = await api("GET", `/v1/sessions/${sid}/files/${f.path.split("/").map(encodeURIComponent).join("/")}`, null, true);
    if (!r.ok) return viewer.lastChild.replaceWith(h("pre", { class: "light" }, (await r.json()).detail));
    const buf = await r.arrayBuffer(), ext = f.path.split(".").pop().toLowerCase();
    const bar = h("div", { class: "bar" }, h("span", {}, f.path), h("span", { class: "row" }, h("span", { class: "muted" }, bytes(f.size)), h("a", { class: "ghost small", href: URL.createObjectURL(new Blob([buf])), download: f.path.split("/").pop() }, "download")));
    let body;
    if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) body = h("div", { style: "padding:12px;background:var(--surface-2)" }, h("img", { src: URL.createObjectURL(new Blob([buf], { type: ext === "svg" ? "image/svg+xml" : "image/" + ext })), style: "max-height:380px" }));
    else { const u8 = new Uint8Array(buf.slice(0, 8000)); const binary = u8.some(b => b === 0); body = h("pre", { class: "light" }, binary ? `binary, ${bytes(f.size)}` : new TextDecoder().decode(buf)); }
    viewer.replaceChildren(bar, body);
  };
  for (const dir of Object.keys(byDir).sort()) { tree.append(h("div", { class: "dir" }, dir || "workspace")); for (const f of byDir[dir]) { const btn = h("button", {}, f.path.split("/").pop(), h("span", {}, bytes(f.size))); btn.addEventListener("click", () => show(f, btn)); tree.append(btn); } }
  const first = tree.querySelector("button"); if (first) first.click();
  return h("div", { class: "files" }, tree, viewer);
}

// requests
async function requests() {
  const hs = (await api("GET", "/v1/harnesses")).data;
  if (!hs.length) return h("div", {}, head("Requests", "A turn against one of your harnesses, streamed."), h("div", { class: "card" }, h("div", { class: "empty" }, "No harnesses yet. ", h("a", { href: "#", on: { click: (e) => { e.preventDefault(); shell("Harnesses"); } } }, "Fork one from the catalog."))));
  const model = h("select", {}, ...hs.map(x => h("option", { value: x.name }, `${x.name} · ${x.defaults.provider || "?"} / ${x.defaults.model || "?"}`))), override = h("input", { placeholder: "provider/model (optional)" }), prev = h("input", { placeholder: "previous_response_id (optional)" }), instr = h("input", { placeholder: "standing instructions (optional)" }), input = h("textarea", { placeholder: "The task. Create a file, fix a test, explain a function…" }), out = h("div", { class: "stack", style: "margin-top:14px" });
  const runBtn = h("button", { class: "act", on: { click: () => run() } }, icon("bolt"), "Run");
  const run = async () => {
    runBtn.disabled = true;
    const live = livePane(), steer = h("input", { placeholder: "steer the running turn: a message delivered to the package" }), note = h("span", { class: "muted" }), cancelBtn = h("button", { class: "danger small" }, "cancel");
    const bar = h("div", { class: "row between" }, h("div", { class: "row" }, tag("running", "run"), h("span", { class: "muted" }, "the package's stdout, as it is written")), cancelBtn);
    out.replaceChildren(h("div", { class: "turn" }, bar, live, h("div", { class: "row", style: "margin-top:10px" }, steer, h("button", { class: "quiet small", on: { click: async () => { try { await api("POST", `/v1/sessions/${sidNow}/interrupt`, { input: steer.value }); note.textContent = "steer delivered"; steer.value = ""; } catch (e) { note.replaceChildren(fail(e)); } } } }, "Steer"), note)));
    let sidNow = "", ridNow = "";
    cancelBtn.addEventListener("click", () => ridNow && api("POST", `/v1/responses/${ridNow}/cancel`).catch(() => {}));
    try {
      const body = { model: override.value.trim() ? `${model.value}/${override.value.trim()}` : model.value, input: input.value };
      if (prev.value.trim()) body.previous_response_id = prev.value.trim();
      if (instr.value.trim()) body.instructions = instr.value.trim();
      const pending = streamTurn(body, (t) => live.push(t));
      const peek = setInterval(async () => { if (!sidNow) { try { const s = (await api("GET", "/v1/sessions")).data.find(x => x.status === "running" && x.member === state.me.name); if (s) { sidNow = s.id; ridNow = s.responses[s.responses.length - 1]; } } catch {} } }, 700);
      const { sid, rid, final } = await pending; clearInterval(peek); sidNow = sid; ridNow = rid; live.done();
      bar.replaceChildren(h("div", { class: "row" }, statusTag(final.status), h("span", { class: "muted" }, `turn ${final.metadata.turn} · ${final.model}`), final.error ? h("span", { class: "err" }, final.error.message) : null), h("div", { class: "row" }, h("button", { class: "quiet small", on: { click: () => { prev.value = final.id; input.value = ""; input.focus(); } } }, "continue this session"), h("button", { class: "quiet small", on: { click: () => session(sid) } }, "open session")));
      out.append(h("div", { class: "turn" }, h("div", { class: "head" }, h("b", {}, "Response"), h("span", { class: "muted" }, "what the package returned")), h("pre", { class: "light" }, final.output[0].content[0].text || "(empty)")),
        h("div", { class: "turn" }, h("div", { class: "head" }, h("b", {}, "Workspace"), h("span", { class: "muted" }, "after this turn"), h("a", { class: "ghost small", href: "#", on: { click: async (e) => { e.preventDefault(); const r = await api("GET", `/v1/sessions/${sid}/archive`, null, true); const a = h("a", { href: URL.createObjectURL(await r.blob()), download: `${sid}.tar.gz` }); a.click(); } } }, "download archive")), await filesPanel(sid)));
      prev.value = final.id;
    } catch (e) { live.done(); out.append(fail(e)); } finally { runBtn.disabled = false; }
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run(); });
  return h("div", {}, head("Requests", "One turn against a harness, streamed as the package writes it. Continue the session with the previous response id; the workspace is there after each turn."),
    h("div", { class: "card" }, h("div", { class: "grid-3" }, field("Harness", model), field("Provider / model override", override), field("Continue from", prev)), h("div", { style: "margin-top:10px" }, field("Instructions", instr)), h("div", { style: "margin-top:10px" }, field("Task", input)), h("div", { class: "row between", style: "margin-top:10px" }, h("span", { class: "muted" }, "⌘↵ runs · POST /v1/responses with stream: true"), runBtn), out));
}

// the arena
async function arena() {
  const [hs, board] = await Promise.all([api("GET", "/v1/harnesses"), api("GET", "/v1/arenas")]);
  const picks = h("div", { class: "picks" }, ...hs.data.map(x => h("label", {}, h("input", { type: "checkbox", value: x.name }), x.name)));
  const input = h("textarea", { placeholder: "One task for every harness you pick. Create a small program, fix a bug, write a plan…" }), cols = h("div", { class: "arena" }), verdict = h("div", { class: "row", style: "margin-top:12px" }), out = h("div");
  const runBtn = h("button", { class: "act", on: { click: () => fight() } }, icon("swords"), "Run the arena");
  const fight = async () => {
    const chosen = [...picks.querySelectorAll("input:checked")].map(i => i.value);
    if (chosen.length < 2 || chosen.length > 6) return out.replaceChildren(fail(new Error("pick two to six harnesses")));
    runBtn.disabled = true; out.replaceChildren(); verdict.replaceChildren(); cols.replaceChildren();
    const entries = chosen.map(name => { const live = livePane(); const col = h("div", { class: "col" }, h("div", { class: "row between" }, h("b", {}, name), tag("running", "run")), live); cols.append(col); return { name, live, col, started: Date.now() }; });
    const results = await Promise.all(entries.map(async (e) => {
      try { const r = await streamTurn({ model: e.name, input: input.value }, (t) => e.live.push(t)); e.live.done(); const secs = ((Date.now() - e.started) / 1000).toFixed(1);
        e.col.firstChild.replaceChildren(h("b", {}, e.name), h("span", { class: "row" }, statusTag(r.final.status), h("span", { class: "muted" }, secs + " s")));
        e.col.append(h("div", {}, h("h3", { style: "margin:4px 0 6px" }, "response"), h("pre", { class: "light", style: "max-height:200px" }, r.final.output[0].content[0].text || "(empty)")), h("div", { class: "row" }, h("button", { class: "quiet small", on: { click: () => session(r.sid) } }, "session and files")));
        return { ...e, ...r };
      } catch (err) { e.live.done(); e.col.append(fail(err)); return { ...e, final: null }; }
    }));
    const ok = results.filter(r => r.final);
    if (ok.length >= 2) {
      let saved = null;
      try { saved = await api("POST", "/v1/arenas", { prompt: input.value, entries: ok.map(r => ({ response: r.final.id })) }); } catch (e) { out.replaceChildren(fail(e)); }
      verdict.replaceChildren(h("b", {}, "Pick the winner:"), ...ok.map(r => h("button", { class: "quiet small", on: { click: async (ev) => { for (const c of cols.children) c.classList.remove("winner"); r.col.classList.add("winner"); if (saved) { await api("PATCH", `/v1/arenas/${saved.id}`, { winner: r.name }); ev.target.parentElement.append(h("span", { class: "muted" }, " saved")); } } } }, r.name)), h("button", { class: "ghost small", on: { click: () => shell("Arena") } }, "refresh the leaderboard"));
    }
    runBtn.disabled = false;
  };
  const rows = board.data.map(a => h("tr", {}, h("td", {}, when(a.created)), h("td", { class: "mono", style: "max-width:220px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis", title: a.prompt }, a.prompt.slice(0, 80)), h("td", {}, a.entries.map(e => e.harness).join(", ")), h("td", {}, a.winner ? tag(a.winner, "orange") : h("span", { class: "muted" }, "undecided")), h("td", {}, h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", `/v1/arenas/${a.id}`); shell("Arena"); } } }, "delete"))));
  return h("div", {}, head("Arena", "One task, several harnesses, side by side as they stream. Pick the winner; the leaderboard remembers."),
    h("div", { class: "card" }, h("h3", { style: "margin-top:0" }, "harnesses"), picks, h("div", { style: "margin-top:12px" }, field("Task", input)), h("div", { class: "row between", style: "margin-top:10px" }, h("span", { class: "muted" }, "each harness runs in its own session; every one is a normal request"), runBtn), out),
    h("div", { id: "arena-run", style: "margin-top:16px" }, cols, verdict),
    h("div", { class: "grid-2", style: "margin-top:16px" },
      h("div", { class: "card" }, h("h2", {}, "Leaderboard"), h("p", { class: "dim" }, "Wins per harness, across the arenas you can see."), board.leaderboard.length ? h("div", { class: "bars" }, ...board.leaderboard.map(r => h("div", { class: "r" }, h("span", { class: "n" }, r.harness), h("div", {}, h("div", { class: "b", style: `width:${Math.max(2, 100 * r.wins / Math.max(1, board.leaderboard[0].wins))}%` })), h("span", { class: "v" }, `${r.wins} / ${r.runs}`)))) : h("div", { class: "empty" }, "No arena yet.")),
      h("div", { class: "card" }, h("h2", {}, "Past arenas"), rows.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "when"), h("th", {}, "task"), h("th", {}, "harnesses"), h("th", {}, "winner"), h("th"))), h("tbody", {}, ...rows))) : h("div", { class: "empty" }, "Nothing yet."))));
}

// sessions
async function sessions() {
  const list = (await api("GET", "/v1/sessions")).data.reverse();
  const rows = list.map(s => h("tr", {}, h("td", {}, h("a", { href: "#", class: "mono", on: { click: (e) => { e.preventDefault(); session(s.id); } } }, s.id.slice(5, 17) + "…")), h("td", {}, s.harness), h("td", {}, s.member), h("td", {}, statusTag(s.status)), h("td", {}, s.responses.length), h("td", {}, s.stored ? "" : tag("stateless")), h("td", { class: "muted" }, ago(s.created_at))));
  return h("div", {}, head("Sessions", isOwner() ? "Every member's sessions in the tenant. Open one for its turns, streams, trace and workspace." : "Your sessions. Open one for its turns, streams, trace and workspace."),
    h("div", { class: "card" }, rows.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "session"), h("th", {}, "harness"), h("th", {}, "member"), h("th", {}, "status"), h("th", {}, "turns"), h("th"), h("th", {}, "created"))), h("tbody", {}, ...rows))) : h("div", { class: "empty" }, "No sessions yet. Make a request.")));
}

async function session(sid) {
  const main = $("main.page"); main.replaceChildren(h("div", { class: "empty" }, "loading…"));
  const s = await api("GET", "/v1/sessions/" + sid);
  const [turns, trace] = await Promise.all([Promise.all(s.responses.map(rid => api("GET", `/v1/responses/${rid}?detail=true`))), api("GET", `/v1/sessions/${sid}/trace`)]);
  const steer = h("input", { placeholder: "steer the running turn" }), out = h("div");
  const blocks = turns.map(t => h("div", { class: "turn" }, h("div", { class: "head" }, h("b", {}, `Turn ${t.metadata.turn}`), statusTag(t.status), h("span", { class: "muted mono" }, t.id), h("span", { class: "muted" }, t.model), h("span", { class: "muted" }, t.started ? hours((t.ended || Date.now() / 1000) - t.started) : ""),
      t.status === "in_progress" ? h("button", { class: "danger small", on: { click: async () => { await api("POST", `/v1/responses/${t.id}/cancel`); session(sid); } } }, "cancel") : null,
      h("button", { class: "ghost small", on: { click: async (e) => { const caps = (await api("GET", `/v1/responses/${t.id}/captures`)).data; e.target.replaceWith(h("span", { class: "muted" }, caps.length ? "captures: " + caps.join(", ") : "no captures")); } } }, "captures")),
    h("h3", {}, "response"), h("pre", { class: "light" }, t.output[0].content[0].text || "(empty)"), h("h3", {}, "request.sh stdout"), h("pre", {}, t.stdout || "(empty)"), t.stderr ? [h("h3", {}, "stderr"), h("pre", {}, t.stderr)] : null, t.error ? h("div", { class: "err" }, t.error.message) : null));
  main.replaceChildren(...[
    head(`Session`, `${s.harness} · ${s.member} · version ${s.version.slice(0, 8)} · ${s.responses.length} turn${s.responses.length === 1 ? "" : "s"}`,
      h("button", { class: "quiet", on: { click: () => shell("Sessions") } }, "← Sessions"), statusTag(s.status),
      s.stored ? h("a", { class: "quiet btn", href: "#", on: { click: async (e) => { e.preventDefault(); const r = await api("GET", `/v1/sessions/${sid}/archive`, null, true); const a = h("a", { href: URL.createObjectURL(await r.blob()), download: `${sid}.tar.gz` }); a.click(); } } }, "Download workspace") : tag("stateless"),
      s.status !== "running" ? h("button", { class: "danger", on: { click: async () => { await api("DELETE", `/v1/sessions/${sid}`); shell("Sessions"); } } }, "Delete") : null),
    s.status === "running" ? h("div", { class: "card" }, h("div", { class: "row" }, steer, h("button", { class: "act", on: { click: async () => { try { await api("POST", `/v1/sessions/${sid}/interrupt`, { input: steer.value }); out.replaceChildren(h("span", { class: "muted" }, "steer delivered")); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Steer"), out)) : null,
    h("div", { class: "card" }, h("h2", {}, "Workspace"), h("p", { class: "dim" }, "The files after the last turn."), await filesPanel(sid)),
    h("div", { class: "card" }, h("h2", {}, "Turns"), h("div", { style: "margin-top:10px" }, ...blocks)),
    h("div", { class: "card" }, h("h2", {}, "Trace"), h("p", { class: "dim" }, "Every request, steer, cancel and response, as sent."), h("pre", {}, trace.data.map(t => `${when(t.at)}  ${t.kind.padEnd(9)} ${t.response}${t.kind === "request" || t.kind === "interrupt" ? "  " + JSON.stringify(t.body.input).slice(0, 120) : ""}`).join("\n")))].filter(Boolean));
}

// providers
async function providers() {
  const list = (await api("GET", "/v1/providers")).data;
  const name = h("input", { placeholder: "deepseek" }), url = h("input", { placeholder: "https://api.deepseek.com/anthropic" }), apiSel = h("select", {}, ...["anthropic-messages", "openai-chat", "openai-responses", "none"].map(a => h("option", {}, a))), key = h("input", { placeholder: "sealed on arrival", type: "password" }), out = h("div");
  const rows = list.map(p => h("tr", {}, h("td", {}, h("b", {}, p.name)), h("td", { class: "mono" }, p.url), h("td", {}, tag(p.api, "blue")), h("td", {}, isOwner() ? h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", "/v1/providers/" + p.name); shell("Providers"); } } }, "remove") : null)));
  return h("div", {}, head("Providers", "A model endpoint, its API shape and its key. The key never enters a sandbox: the gateway swaps a per-turn token for it."),
    h("div", { class: "card" }, rows.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "url"), h("th", {}, "api"), h("th"))), h("tbody", {}, ...rows))) : h("div", { class: "empty" }, "No providers yet.")),
    isOwner() ? h("div", { class: "card" }, h("h2", {}, "Add a provider"), h("p", { class: "dim" }, "The catalog's packages expect a provider named deepseek (Anthropic shape), deepseek-openai or openai (chat shape), or openai-responses; name yours in the request's model path otherwise."),
      h("div", { class: "grid-4" }, field("Name", name), field("URL", url), field("API shape", apiSel), field("Key", key)), h("div", { class: "row end", style: "margin-top:10px" }, h("button", { class: "act", on: { click: async () => { try { await api("PUT", "/v1/providers/" + name.value.trim(), { url: url.value.trim(), api: apiSel.value, key: key.value }); shell("Providers"); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Add")), out) : null);
}

// harnesses
async function harnesses() {
  const [list, catalog] = await Promise.all([api("GET", "/v1/harnesses"), api("GET", "/v1/catalog")]);
  const mine = new Set(list.data.map(x => x.name));
  const rows = list.data.map(hn => h("tr", {}, h("td", {}, h("b", {}, hn.name)), h("td", {}, hn.description), h("td", { class: "muted" }, `${hn.defaults.provider || "—"} / ${hn.defaults.model || "—"}`), h("td", {}, tag(hn.version.slice(0, 8)), " ", h("span", { class: "muted" }, `${hn.versions.length} version${hn.versions.length === 1 ? "" : "s"}`)),
    h("td", {}, isOwner() ? h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", "/v1/harnesses/" + hn.name); shell("Harnesses"); } } }, "remove") : null)));
  const out = h("div"), file = h("input", { type: "file", accept: ".tgz,.tar.gz,.tar" }), upName = h("input", { placeholder: "name" });
  const fork = async (c) => { try { await api("PUT", "/v1/harnesses/" + c.name, { catalog: c.name }); shell("Harnesses"); } catch (e) { out.replaceChildren(fail(e)); } };
  const cat = h("div", { class: "cat" }, ...catalog.data.map(c => h("div", { class: "pkg" }, h("div", { class: "row between" }, h("b", {}, c.name), c.verified.passed !== undefined ? tag(`${c.verified.passed}/9`, c.verified.passed === 9 ? "ok" : "") : tag("template")), h("span", { class: "muted" }, c.description.slice(0, 110)), h("div", { class: "row between" }, h("span", { class: "muted mono" }, c.provider_env.key || ""), mine.has(c.name) ? tag("forked", "blue") : isOwner() ? h("button", { class: "quiet small", on: { click: () => fork(c) } }, "Fork") : null))));
  return h("div", {}, head("Harnesses", "Your packages: install.sh, request.sh, response.sh and seeds. Request with the name, or name/provider/model."),
    h("div", { class: "card" }, rows.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "description"), h("th", {}, "defaults"), h("th", {}, "version"), h("th"))), h("tbody", {}, ...rows))) : h("div", { class: "empty" }, "No harnesses yet. Fork one below.")),
    h("div", { class: "card" }, h("h2", {}, "Catalog"), h("p", { class: "dim" }, "Twenty-two packages, each run through nine live checks on the provider named. Fork one as it is, then change what it returns."), cat, out),
    isOwner() ? h("div", { class: "card" }, h("h2", {}, "Upload a package"), h("p", { class: "dim" }, "A tar of harness.json, install.sh, request.sh, response.sh and seeds."), h("div", { class: "row" }, upName, file, h("button", { class: "act", on: { click: async () => { try { const r = await api("PUT", "/v1/harnesses/" + upName.value.trim(), file.files[0], true); if (!r.ok) throw new Error((await r.json()).detail); shell("Harnesses"); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Upload"))) : null);
}

// members, invitations, keys
async function members() {
  const [ms, ks, inv] = await Promise.all([api("GET", "/v1/members").catch(() => ({ data: [] })), api("GET", "/v1/keys"), isOwner() ? api("GET", "/v1/invites").catch(() => ({ data: [] })) : { data: [] }]);
  const email = h("input", { type: "email", placeholder: "teammate@company.com" }), role = h("select", {}, h("option", {}, "member"), h("option", {}, "owner")), out = h("div");
  const name = h("input", { placeholder: "member name (for an API-key member)" }), role2 = h("select", {}, h("option", {}, "member"), h("option", {}, "owner")), out2 = h("div");
  const keyFor = h("input", { placeholder: "member", value: state.me.name }), label = h("input", { placeholder: "label: laptop, ci…" }), out3 = h("div");
  return h("div", {}, head("Members", "Who is in the tenant, who is invited, and the API keys."),
    isOwner() ? h("div", { class: "card" }, h("h2", {}, "Members"), h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "role"), h("th", {}, "since"))), h("tbody", {}, ...ms.data.map(m => h("tr", {}, h("td", {}, h("b", {}, m.name)), h("td", {}, tag(m.role, m.role === "owner" ? "orange" : "")), h("td", { class: "muted" }, when(m.created))))))),
      h("h3", {}, "invite by email"), h("p", { class: "muted" }, "They sign in with that email, by password, GitHub or Google, and land in this tenant."), h("div", { class: "row" }, email, role, h("button", { class: "act", on: { click: async () => { try { await api("POST", "/v1/invites", { email: email.value.trim(), role: role.value }); shell("Members"); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Invite")), out,
      inv.data.length ? h("div", { class: "table-wrap", style: "margin-top:10px" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "invited"), h("th", {}, "role"), h("th", {}, "sent"), h("th"))), h("tbody", {}, ...inv.data.map(i => h("tr", {}, h("td", {}, i.email), h("td", {}, i.role), h("td", { class: "muted" }, ago(i.created)), h("td", {}, h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", "/v1/invites/" + encodeURIComponent(i.email)); shell("Members"); } } }, "revoke"))))))) : null,
      h("h3", {}, "add a member without an account"), h("p", { class: "muted" }, "For a service that uses a key only."), h("div", { class: "row" }, name, role2, h("button", { class: "quiet", on: { click: async () => { try { await api("POST", "/v1/members", { name: name.value.trim(), role: role2.value }); shell("Members"); } catch (e) { out2.replaceChildren(fail(e)); } } } }, "Add")), out2) : null,
    h("div", { class: "card" }, h("h2", {}, "API keys"), h("p", { class: "dim" }, "Mint a key per place a key is used; revoke the one that leaks. The secret is shown once."),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "id"), h("th", {}, "member"), h("th", {}, "label"), h("th", {}, "created"), h("th"))), h("tbody", {}, ...ks.data.map(k => h("tr", {}, h("td", { class: "mono" }, k.id), h("td", {}, k.member), h("td", {}, k.label), h("td", { class: "muted" }, when(k.created)), h("td", {}, k.revoked ? tag("revoked", "bad") : h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", "/v1/keys/" + k.id); shell("Members"); } } }, "revoke"))))))),
      h("h3", {}, "mint a key"), h("div", { class: "row" }, keyFor, label, h("button", { class: "act", on: { click: async () => { try { const r = await api("POST", `/v1/members/${keyFor.value.trim()}/keys`, { label: label.value }); out3.replaceChildren(h("p", { style: "margin-top:10px" }, "Shown once:"), h("div", { class: "row" }, h("div", { class: "secret" }, r.secret), copy(r.secret))); } catch (e) { out3.replaceChildren(fail(e)); } } } }, "Mint")), out3));
}

// the account
async function account() {
  const me = await api("GET", "/auth/me");
  const name = h("input", { value: me.account.name }), cur = h("input", { type: "password", placeholder: me.account.has_password ? "current password" : "no password yet" }), pw = h("input", { type: "password", placeholder: "new password" }), tname = h("input", { placeholder: "tenant name (lowercase)" }), out = h("div"), out2 = h("div"), out3 = h("div");
  return h("div", {}, head("Account", me.account.email),
    h("div", { class: "grid-2" },
      h("div", { class: "card" }, h("h2", {}, "Profile"), h("div", { class: "stack", style: "margin-top:10px" }, field("Name", name), h("div", { class: "row" }, h("button", { class: "quiet", on: { click: async () => { try { await api("PATCH", "/auth/account", { name: name.value }); out.replaceChildren(h("span", { class: "muted" }, "saved")); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Save"), out)),
        h("h3", {}, "sign-in"), h("div", { class: "row" }, tag(me.account.verified ? "email verified" : "email not verified", me.account.verified ? "ok" : "warn"), ...me.account.providers.map(p => tag(p, "blue")), me.account.has_password ? tag("password") : null),
        h("h3", {}, "password"), h("div", { class: "stack" }, me.account.has_password ? field("Current", cur) : null, field("New", pw), h("div", { class: "row" }, h("button", { class: "quiet", on: { click: async () => { try { await api("POST", "/auth/password", { current: cur.value, password: pw.value }); out2.replaceChildren(h("span", { class: "muted" }, "changed")); } catch (e) { out2.replaceChildren(fail(e)); } } } }, "Change"), out2))),
      h("div", { class: "card" }, h("h2", {}, "Tenants"), h("p", { class: "dim" }, "Each tenant has its own providers, packages, members and sessions. You are one member in each."),
        h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "tenant"), h("th", {}, "you"), h("th", {}, "role"), h("th"))), h("tbody", {}, ...me.tenants.map(t => h("tr", {}, h("td", {}, h("b", {}, t.tenant)), h("td", {}, t.member), h("td", {}, tag(t.role, t.role === "owner" ? "orange" : "")), h("td", {}, t.tenant === state.me.tenant ? tag("current", "blue") : h("button", { class: "quiet small", on: { click: async () => { const m = await api("POST", "/auth/switch", { tenant: t.tenant }); state.tenants = m.tenants; state.me = { ...m.current, name: m.current.member }; state.kind = m.current.role; shell("Requests"); } } }, "switch"))))))),
        h("h3", {}, "new tenant"), h("div", { class: "row" }, tname, h("button", { class: "act", on: { click: async () => { try { const m = await api("POST", "/auth/tenants", { name: tname.value.trim() }); state.tenants = m.tenants; state.me = { ...m.current, name: m.current.member }; state.kind = m.current.role; shell("Providers"); } catch (e) { out3.replaceChildren(fail(e)); } } } }, "Create")), out3)));
}

// the deployer
const tip = (el, text) => { el.addEventListener("mousemove", (e) => { const t = $("#tip"); t.textContent = text; t.style.display = "block"; t.style.left = (e.clientX + 12) + "px"; t.style.top = (e.clientY + 12) + "px"; }); el.addEventListener("mouseleave", () => { $("#tip").style.display = "none"; }); };
function columns(rows, key, fmt, title) {
  const W = 720, H = 200, L = 48, R = 8, T = 18, B = 26;
  const max = Math.max(1, ...rows.map(r => r[key]));
  const step = Math.pow(10, Math.floor(Math.log10(max))); const top = Math.ceil(max / step) * step;
  const root = svg("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img", "aria-label": title });
  root.append(svg("title", {}, title));
  for (let i = 0; i <= 2; i++) { const y = T + (H - T - B) * (1 - i / 2); root.append(svg("line", { class: "grid", x1: L, x2: W - R, y1: y, y2: y }), svg("text", { class: "axis", x: L - 6, y: y + 3, "text-anchor": "end" }, i ? fmt(top * i / 2) : "0")); }
  const slot = (W - L - R) / rows.length, bw = Math.min(24, Math.max(2, slot - 2));
  const peak = rows.reduce((b, r, i) => r[key] > rows[b][key] ? i : b, 0);
  rows.forEach((r, i) => {
    const x = L + i * slot + (slot - bw) / 2, hgt = (H - T - B) * r[key] / top, y = H - B - hgt;
    const g = svg("g", {});
    if (r[key] > 0) g.append(svg("path", { class: "bar", d: `M${x},${H - B} V${Math.min(y + 4, H - B)} a4,4 0 0 1 4,-4 h${bw - 8} a4,4 0 0 1 4,4 V${H - B} Z` }));
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
  return rows.length ? h("div", { class: "bars" }, ...rows.slice(0, 8).map(r => { const el = h("div", { class: "r" }, h("span", { class: "n" }, r[name]), h("div", {}, h("div", { class: "b", style: `width:${Math.max(2, 100 * r[key] / max)}%` })), h("span", { class: "v" }, fmt(r[key]))); tip(el, `${r[name]}: ${fmt(r[key])}`); return el; })) : h("div", { class: "empty" }, "nothing yet");
}
async function dashboard() {
  const [fleet, usage] = await Promise.all([api("GET", "/v1/fleet"), api("GET", `/v1/usage?days=${state.window}`)]);
  const stat = (n, label) => h("div", { class: "stat" }, h("b", {}, n), h("span", {}, label));
  const pick = (d, label) => h("button", { class: "quiet small" + (state.window === d ? " on" : ""), on: { click: () => { state.window = d; shell("Dashboard"); } } }, label);
  const t = usage.totals, st = usage.statuses;
  return h("div", {}, head("Dashboard", "Counts and sizes across the platform. Never a tenant's prompts, output, packages or keys.", pick(0, "All time"), pick(30, "30 days"), pick(60, "60 days"), pick(90, "90 days")),
    h("div", { class: "card" }, h("div", { class: "stats" }, stat(fleet.tenants, "tenants"), stat(fleet.workers, "workers alive"), stat(fleet.slots, "slots"), stat(fleet.running, "running"), stat(fleet.queued, "queued"), stat(fleet.lost_recently.length, "lost recently"))),
    h("div", { class: "card" }, h("h2", {}, "Usage"), h("div", { class: "stats", style: "margin-top:12px" }, stat(num(t.turns), "turns"), stat(hours(t.seconds), "sandbox time"), stat(num(t.calls), "provider calls"), stat(bytes(t.bytes_in), "sent to providers"), stat(bytes(t.bytes_out), "received"), stat(t.turns ? Math.round(100 * (st.completed || 0) / t.turns) + "%" : "—", "completed")),
      h("div", { class: "grid-2" }, h("div", {}, h("h3", {}, "turns per day"), columns(usage.daily, "turns", num, "turns per day")), h("div", {}, h("h3", {}, "provider calls per day"), columns(usage.daily, "calls", num, "provider calls per day")), h("div", {}, h("h3", {}, "sandbox seconds per day"), columns(usage.daily, "seconds", hours, "sandbox seconds per day")), h("div", {}, h("h3", {}, "bytes received per day"), columns(usage.daily, "bytes_out", bytes, "bytes received from providers per day")))),
    h("div", { class: "grid-3" }, h("div", { class: "card" }, h("h2", {}, "By tenant"), bars(usage.tenants, "tenant", "turns", num)), h("div", { class: "card" }, h("h2", {}, "By harness"), bars(usage.harnesses, "harness", "turns", num)), h("div", { class: "card" }, h("h2", {}, "By outcome"), bars(Object.entries(st).map(([k, v]) => ({ status: k, n: v })), "status", "n", num))),
    h("div", { class: "card" }, h("h2", {}, "As a table"), h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "day"), h("th", {}, "turns"), h("th", {}, "seconds"), h("th", {}, "calls"), h("th", {}, "bytes in"), h("th", {}, "bytes out"))), h("tbody", {}, ...usage.daily.filter(d => d.turns).slice(-14).reverse().map(d => h("tr", {}, h("td", {}, d.day), h("td", {}, d.turns), h("td", {}, d.seconds), h("td", {}, d.calls), h("td", {}, bytes(d.bytes_in)), h("td", {}, bytes(d.bytes_out)))))))));
}
async function tenants() {
  const list = (await api("GET", "/v1/tenants")).data;
  const name = h("input", { placeholder: "tenant" }), owner = h("input", { placeholder: "owner member" }), limits = h("input", { placeholder: '{"max_runs": 4} (optional)' }), out = h("div");
  const rows = list.map(t => { const lim = h("input", { value: JSON.stringify(t.limits), style: "width:100%;font-family:var(--mono);font-size:12px" }), err = h("div"); return h("tr", {}, h("td", {}, h("b", {}, t.name)), h("td", {}, statusTag(t.status)),
    h("td", { class: "muted" }, `${t.usage.turns} turns · ${hours(t.usage.seconds)} · ${t.usage.calls} calls · ${t.usage.running} running · ${t.usage.queued} queued`),
    h("td", { style: "min-width:280px" }, lim, h("div", { class: "row", style: "margin-top:6px" }, h("button", { class: "quiet small", on: { click: async () => { try { await api("PATCH", "/v1/tenants/" + t.name, { limits: JSON.parse(lim.value) }); shell("Tenants"); } catch (e) { err.replaceChildren(fail(e)); } } } }, "save"), err)),
    h("td", {}, h("div", { class: "row" }, h("button", { class: "quiet small", on: { click: async () => { await api("PATCH", "/v1/tenants/" + t.name, { status: t.status === "active" ? "suspended" : "active" }); shell("Tenants"); } } }, t.status === "active" ? "suspend" : "activate"),
      h("button", { class: "ghost small danger", on: { click: async (e) => { if (e.target.dataset.sure) { await api("DELETE", "/v1/tenants/" + t.name); shell("Tenants"); } else { e.target.dataset.sure = "1"; e.target.textContent = "delete everything it owns?"; } } } }, "delete")))); });
  return h("div", {}, head("Tenants", "Every tenant, its usage and its ceilings."),
    h("div", { class: "card" }, h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "tenant"), h("th", {}, "status"), h("th", {}, "usage"), h("th", {}, "ceilings"), h("th"))), h("tbody", {}, ...rows)))),
    h("div", { class: "card" }, h("h2", {}, "Create a tenant"), h("p", { class: "dim" }, "With a first owner, as a member with a key. Owners invite accounts by email from inside the tenant."), h("div", { class: "grid-3" }, field("Tenant", name), field("Owner", owner), field("Limits", limits)), h("div", { class: "row end", style: "margin-top:10px" }, h("button", { class: "act", on: { click: async () => {
      try { const r = await api("POST", "/v1/tenants", { name: name.value.trim(), owner: owner.value.trim(), ...(limits.value.trim() ? { limits: JSON.parse(limits.value) } : {}) }); out.replaceChildren(h("p", { style: "margin-top:10px" }, `Owner key for ${r.owner}, shown once. Hand it over securely:`), h("div", { class: "row" }, h("div", { class: "secret" }, r.key.secret), copy(r.key.secret))); } catch (e) { out.replaceChildren(fail(e)); } } } }, "Create")), out));
}
async function workers() {
  const list = (await api("GET", "/v1/workers")).data;
  return h("div", {}, head("Workers", "A worker joins with the join token and pulls turns. Add capacity by running the worker role on another machine."),
    h("div", { class: "card" }, list.length ? h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "name"), h("th", {}, "id"), h("th", {}, "alive"), h("th", {}, "slots"), h("th", {}, "running"), h("th", {}, "version"), h("th", {}, "last seen"), h("th"))), h("tbody", {}, ...list.map(w => h("tr", {}, h("td", {}, h("b", {}, w.name)), h("td", { class: "mono" }, w.id), h("td", {}, statusTag(w.alive ? "alive" : "lost")), h("td", {}, w.slots), h("td", {}, w.running), h("td", {}, w.version), h("td", { class: "muted" }, ago(w.last_seen)), h("td", {}, h("button", { class: "ghost small danger", on: { click: async () => { await api("DELETE", "/v1/workers/" + w.id); shell("Workers"); } } }, "forget"))))))) : h("div", { class: "empty" }, "No workers have joined.")));
}
boot();
