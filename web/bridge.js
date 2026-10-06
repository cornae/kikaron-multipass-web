/* Multipass bridge - the vault host's half of Kikaron's own Multipass screens.
 *
 * Kikaron draws the vault itself (apps/multipass, libraries/kikaron/multipass/
 * vault.js) and does the encryption in the browser. What it cannot do from its
 * own origin is talk to the vault server: Vaultwarden answers cross-origin calls
 * from its own host only. So Kikaron keeps this page in a hidden frame
 * (multipass-bridge.html, on the vault host) and asks it, by postMessage, to
 *   - sign in through Kikaron (the vault's single sign-on, PKCE), and
 *   - make API calls with the resulting token.
 * The tokens never leave this origin; Kikaron only ever receives what the API
 * returns - and the vault's contents are ciphertext until Kikaron's page, holding
 * the key the person unlocked with, decrypts them.
 *
 * Sign-in is tried first in this same frame, silently. Kikaron's own pages refuse
 * to be framed (X-Frame-Options: DENY), so whenever the sign-in needs the person -
 * Kikaron's log-in, an approval - it cannot happen here; Kikaron then offers a
 * button that opens multipass-bridge.html#signin=<identifier> as a small popup
 * window, which runs the same sign-in at the top level and closes itself
 * (#done). Storage is shared with the frame (same site), so the frame finds the
 * session when Kikaron reloads it.
 *
 * Either way the browser navigates to the vault's authorize
 * endpoint, through Kikaron's sign-in, and comes back on sso-connector.html (the
 * one return address Vaultwarden allows a web client). That page carries this
 * script too (apply_branding.py puts it there); the state ends in
 * ":clientId=browser", which makes the stock connector hand the code to the page
 * instead of navigating on, so this script can exchange it and come back here.
 *
 * Only a Kikaron page may talk to it: every message's origin must be a
 * *.kikaron.com host (the vault's frame-ancestors list says the same).
 */
(function () {
  "use strict";

  var KIKARON = /^https:\/\/([a-z0-9-]+\.)*kikaron\.com$/;
  var STORE = "mp-bridge";
  var REDIRECT = location.origin + "/sso-connector.html";
  var CLIENT_ID = "web";
  var DEVICE_TYPE = "14"; // UnknownBrowser
  // the vault server refuses a client that does not say which version it is; this
  // is the version of the web vault the bridge ships with (apply_branding.py
  // stamps it in from version.json)
  var CLIENT_VERSION = "__MULTIPASS_CLIENT_VERSION__";
  function headers(extra) {
    var h = { "Device-Type": DEVICE_TYPE, "Bitwarden-Client-Name": "web", "Bitwarden-Client-Version": CLIENT_VERSION };
    for (var k in extra) { h[k] = extra[k]; }
    return h;
  }
  var parentOrigin = null;

  function load() {
    try { return JSON.parse(localStorage.getItem(STORE) || "{}"); } catch (e) { return {}; }
  }
  function save(data) {
    try { localStorage.setItem(STORE, JSON.stringify(data)); } catch (e) { /* private mode */ }
  }
  function b64url(bytes) {
    var s = "";
    for (var i = 0; i < bytes.length; i++) { s += String.fromCharCode(bytes[i]); }
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function random(n) {
    var a = new Uint8Array(n);
    crypto.getRandomValues(a);
    return b64url(a).replace(/[-_]/g, "x");
  }
  function deviceId() {
    var data = load();
    if (!data.device) {
      data.device = crypto.randomUUID ? crypto.randomUUID() : random(16);
      save(data);
    }
    return data.device;
  }
  function form(fields) {
    return Object.keys(fields).map(function (k) {
      return encodeURIComponent(k) + "=" + encodeURIComponent(fields[k]);
    }).join("&");
  }
  function jwtEmail(token) {
    try {
      var part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(escape(atob(part)))).email || "";
    } catch (e) { return ""; }
  }

  function tokenRequest(fields) {
    return fetch("/identity/connect/token", {
      method: "POST",
      headers: headers({ "Content-Type": "application/x-www-form-urlencoded; charset=utf-8" }),
      body: form(fields),
      credentials: "omit"
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (body) {
        if (!r.ok || !body.access_token) { throw new Error("token " + r.status); }
        var data = load();
        data.access = body.access_token;
        data.refresh = body.refresh_token || data.refresh;
        data.expires = Date.now() + ((body.expires_in || 3600) - 60) * 1000;
        save(data);
        return data;
      });
    });
  }

  function refresh() {
    var data = load();
    if (!data.refresh) { return Promise.reject(new Error("no session")); }
    return tokenRequest({ grant_type: "refresh_token", client_id: CLIENT_ID, refresh_token: data.refresh });
  }

  function accessToken() {
    var data = load();
    if (data.access && data.expires > Date.now()) { return Promise.resolve(data.access); }
    return refresh().then(function (d) { return d.access; });
  }

  function api(method, path, body) {
    function call(token) {
      return fetch(path, {
        method: method,
        headers: headers({ "Authorization": "Bearer " + token, "Content-Type": "application/json" }),
        body: body == null ? undefined : JSON.stringify(body),
        credentials: "omit"
      });
    }
    return accessToken().then(call).then(function (r) {
      if (r.status !== 401) { return r; }
      return refresh().then(function (d) { return call(d.access); });
    }).then(function (r) {
      return r.text().then(function (text) {
        var json = null;
        try { json = text ? JSON.parse(text) : null; } catch (e) { /* not JSON */ }
        return { status: r.status, ok: r.ok, json: json };
      });
    });
  }

  // POST without a token (prelogin: the KDF settings for an address)
  function anon(path, body) {
    return fetch(path, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
      credentials: "omit"
    }).then(function (r) { return r.json().then(function (j) { return { status: r.status, ok: r.ok, json: j }; }); });
  }

  // ---- single sign-on ----------------------------------------------------------
  function startSignIn(identifier) {
    var verifier = random(48);
    var state = random(24) + ":clientId=browser";
    return crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)).then(function (hash) {
      var data = load();
      data.sso = { verifier: verifier, state: state, at: Date.now() };
      save(data);
      location.assign("/identity/connect/authorize?" + form({
        client_id: CLIENT_ID,
        redirect_uri: REDIRECT,
        response_type: "code",
        scope: "api offline_access",
        state: state,
        code_challenge: b64url(new Uint8Array(hash)),
        code_challenge_method: "S256",
        response_mode: "query",
        domain_hint: identifier || ""
      }));
    });
  }

  // on sso-connector.html: finish the sign-in this frame started, then go home
  function finishSignIn() {
    var q = new URLSearchParams(location.search);
    var code = q.get("code"), state = q.get("state");
    var data = load();
    if (!code || !data.sso || state !== data.sso.state) { return false; }
    var verifier = data.sso.verifier;
    delete data.sso;
    save(data);
    tokenRequest({
      grant_type: "authorization_code",
      code: code,
      code_verifier: verifier,
      redirect_uri: REDIRECT,
      client_id: CLIENT_ID,
      scope: "api offline_access",
      deviceType: DEVICE_TYPE,
      deviceIdentifier: deviceId(),
      deviceName: "Kikaron"
    }).catch(function () {
      var d = load(); d.error = "signin"; save(d);
    }).then(function () {
      // a popup sign-in closes itself; the framed one goes back to being the bridge
      location.replace("/multipass-bridge.html" + (window.parent === window ? "#done" : ""));
    });
    return true;
  }

  // ---- talking to Kikaron ---------------------------------------------------------
  function reply(id, ok, value) {
    if (!parentOrigin) { return; }
    window.parent.postMessage({ mpb: "reply", id: id, ok: ok, value: value }, parentOrigin);
  }

  var OPS = {
    // who is signed in here, if anyone (no network unless a refresh is due)
    session: function () {
      var data = load();
      var error = data.error || null;
      if (error) { delete data.error; save(data); }
      return accessToken().then(function (token) {
        return { signedIn: true, email: jwtEmail(token) };
      }, function () { return { signedIn: false, error: error }; });
    },
    signIn: function (args) { return startSignIn(args && args.identifier).then(function () { return { navigating: true }; }); },
    signOut: function () {
      var data = load();
      delete data.access; delete data.refresh; delete data.expires;
      save(data);
      return Promise.resolve(true);
    },
    prelogin: function (args) { return anon("/identity/accounts/prelogin", { email: args.email }); },
    api: function (args) { return api(args.method || "GET", args.path, args.body); }
  };

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent || !KIKARON.test(event.origin)) { return; }
    var data = event.data;
    if (!data || data.mpb !== "call" || !OPS[data.op]) { return; }
    parentOrigin = event.origin;
    Promise.resolve().then(function () { return OPS[data.op](data.args || {}); }).then(
      function (value) { reply(data.id, true, value); },
      function (err) { reply(data.id, false, String(err && err.message || err)); });
  });

  if (/\/sso-connector\.html$/.test(location.pathname)) {
    finishSignIn();
    return;
  }
  if (window.parent === window) {
    // the popup: start the sign-in, or close once it is done
    var hash = location.hash || "";
    if (hash === "#done") { window.close(); return; }
    var m = /^#signin=(.*)$/.exec(hash);
    if (m) { startSignIn(decodeURIComponent(m[1])); }
    return;
  }
  if (window.parent !== window) {
    // the parent's origin is not known until it speaks; announce to any Kikaron
    // host by asking it to say hello (it answers with a "call" we can reply to)
    window.parent.postMessage({ mpb: "ready" }, "*");
  }
})();
