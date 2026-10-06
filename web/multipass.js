/* Multipass - the small amount of script the vault needs of its own. Loaded by
 * index.html (the vault's CSP allows 'self' scripts, not inline ones).
 *
 * 1. Tell the stylesheet when the vault is framed by Kikaron (apps/multipass):
 *    the app already shows the product name and its own chrome, so the framed
 *    pages drop the vault's wordmark and footer (kikaron-theme.css, html.mp-framed).
 * 2. Tell Kikaron when the framed vault is showing a SETTLED screen. Between
 *    "opened" and "the screen you wanted" the vault passes through several
 *    transient routes and interstitials (the SSO round trip, the padlock and the
 *    spinner card); Kikaron keeps its own loading state over the frame until this
 *    says ready (libraries/kikaron/multipass/multipass.js), so none of that flashes.
 */
(function () {
  "use strict";
  try {
    if (window.top !== window.self) {
      document.documentElement.classList.add("mp-framed");
    }
  } catch (e) {
    // a cross-origin top window: framed, by definition
    document.documentElement.classList.add("mp-framed");
  }
})();

(function () {
  "use strict";
  var framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }
  if (!framed || !window.parent) { return; }

  // routes that are only ever on the way to somewhere
  var TRANSIENT = ["", "#", "#/", "#/sso", "#/sso-callback", "#/loading", "#/setup-extension"];
  var last = "", since = 0, sent = "";

  function route() {
    return (location.hash || "").split("?")[0];
  }
  function post(state) {
    try { window.parent.postMessage({ multipass: state, route: route() }, "*"); }
    catch (e) { /* nobody to tell */ }
  }
  setInterval(function () {
    var r = route(), now = Date.now();
    if (r !== last) { last = r; since = now; }
    var transient = TRANSIENT.indexOf(r) !== -1;
    if (transient) {
      if (sent !== "busy") { sent = "busy"; post("busy"); }
    } else if (now - since > 600 && sent !== "ready:" + r) {
      sent = "ready:" + r;
      post("ready");
    }
  }, 250);
})();

/* 3. A framed vault never rests on the e-mail login page. Kikaron has already said
 *    who the person is, so if the vault lands on #/login (a half-finished sign-in
 *    left in the browser - typically someone who reloaded before choosing a master
 *    password - or an expired session), clear what this origin stored and start the
 *    single sign-on again. At most once per half minute, so a sign-in that cannot
 *    succeed shows its page instead of looping. A real vault is never on #/login:
 *    it is on #/lock (unlock) or #/vault, which this leaves alone.
 */
(function () {
  "use strict";
  var framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }
  if (!framed) { return; }

  // Vaultwarden's fixed identifier for its single SSO integration (src/sso.rs)
  var SSO = "#/sso?identifier=00000000-01DC-01DC-01DC-000000000000";
  var KEY = "mp-sso-retry";
  var started = false;

  function wipe() {
    try { localStorage.clear(); } catch (e) { /* nothing to clear */ }
    if (!window.indexedDB || !indexedDB.databases) { return Promise.resolve(); }
    return indexedDB.databases().then(function (dbs) {
      return Promise.all(dbs.map(function (db) {
        return new Promise(function (done) {
          var req = indexedDB.deleteDatabase(db.name);
          req.onsuccess = req.onerror = req.onblocked = function () { done(); };
        });
      }));
    }).catch(function () { /* best effort */ });
  }

  function check() {
    if (started || (location.hash || "").split("?")[0] !== "#/login") { return; }
    var last = 0;
    try { last = parseInt(sessionStorage.getItem(KEY) || "0", 10) || 0; } catch (e) { /* ignore */ }
    if (Date.now() - last < 30000) { return; }
    started = true;
    try { sessionStorage.setItem(KEY, String(Date.now())); } catch (e) { /* ignore */ }
    wipe().then(function () {
      location.replace(location.pathname + SSO);
      location.reload();
    });
  }
  setInterval(check, 400);
})();

/* 4. The "choose a master password" screen (a new person, after Kikaron has vouched
 *    for them) is shown by Kikaron as a panel of its own - a notice with one line of
 *    explanation over just the form - not as the stock product page. Recognise the
 *    screen by what is on it (a form asking for a NEW password inside the landing
 *    card), flag the document (html.mp-setpw: kikaron-theme.css strips the stock
 *    header, the log-out button and the page chrome) and tell the parent, with the
 *    height of the card, so it can seat the frame in its panel.
 */
(function () {
  "use strict";
  var framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }
  if (!framed || !window.parent) { return; }

  var root = document.documentElement;
  var lastHeight = 0, lastFlag = false;

  function card() {
    return document.querySelector("bit-landing-card");
  }
  // what marks the screen where a NEW master password is chosen: inputs that ask for a
  // new password, the confirmation, or the hint. Upstream names change between
  // releases, so several are tried; any one inside the landing card is enough.
  var SETPW = 'input[formcontrolname="newPasswordConfirm"], input[formcontrolname="newPasswordHint"], '
    + 'input[autocomplete="new-password"], input[formcontrolname="confirmedPassword"], '
    + 'input[formcontrolname="hint"], input[formcontrolname="masterPasswordHint"], '
    + 'input[formcontrolname="newMasterPassword"], input[formcontrolname="confirmNewMasterPassword"]';
  function isSetPassword() {
    return !!document.querySelector("bit-landing-card form " + SETPW.split(", ").join(", bit-landing-card form "));
  }
  function tick() {
    var on = isSetPassword();
    if (on !== lastFlag) {
      lastFlag = on;
      root.classList.toggle("mp-setpw", on);
      lastHeight = 0;
      if (!on) { try { window.parent.postMessage({ multipass: "panel", modal: false }, "*"); } catch (e) { /* ignore */ } }
    }
    if (!on) { return; }
    // the card sits fixed at the top of the frame (kikaron-theme.css): its own
    // height - scrollHeight, so a card capped at the frame's height still reports
    // all of itself and the frame grows to it instead of scrolling
    var c = card();
    var h = c ? Math.ceil(Math.max(c.scrollHeight, c.getBoundingClientRect().height)) : 0;
    if (h && Math.abs(h - lastHeight) > 2) {
      lastHeight = h;
      try { window.parent.postMessage({ multipass: "panel", modal: true, height: h, busy: busy() }, "*"); }
      catch (e) { /* nobody to tell */ }
    } else {
      var b = busy();
      if (b !== lastBusy) {
        lastBusy = b;
        try { window.parent.postMessage({ multipass: "panel", modal: true, height: lastHeight, busy: b }, "*"); }
        catch (e) { /* nobody to tell */ }
      }
    }
  }
  // the form's own submit button is hidden on this screen (kikaron-theme.css): the
  // panel's button is Kikaron's, and asks for the submit with {multipass: "submit"}
  function submitButton() {
    return document.querySelector('bit-landing-card form button[type="submit"]');
  }
  var lastBusy = false;
  function busy() {
    var b = submitButton();
    return !!b && (b.disabled || b.getAttribute("aria-disabled") === "true");
  }
  window.addEventListener("message", function (event) {
    var data = event.data;
    if (event.source !== window.parent || !data) { return; }
    // only a Kikaron page may press it (the frame-ancestors list says the same)
    if (!/^https:\/\/([a-z0-9-]+\.)*kikaron\.com$/.test(event.origin)) { return; }
    // a Kikaron page that draws the button itself says so; an older one does not,
    // and keeps the vault's own button (html.mp-kbutton gates the hiding)
    if (data.multipass === "has-button") { root.classList.add("mp-kbutton"); return; }
    if (data.multipass !== "submit") { return; }
    var b = submitButton();
    if (lastFlag && b && !busy()) { b.click(); }
  });
  setInterval(tick, 200);
})();

/* 5. The "get the browser extension" page a new vault opens on is the stock
 *    product's onboarding, a store pitch in the middle of Kikaron. A framed vault
 *    goes straight on to the vault itself (the page is listed as transient above,
 *    so Kikaron's loading state covers the hop).
 */
(function () {
  "use strict";
  var framed = false;
  try { framed = window.top !== window.self; } catch (e) { framed = true; }
  if (!framed) { return; }
  setInterval(function () {
    if ((location.hash || "").split("?")[0] === "#/setup-extension") {
      location.replace(location.pathname + "#/vault");
    }
  }, 200);
})();
