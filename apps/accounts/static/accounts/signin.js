/* The entrance's only script. A STATIC FILE, never inline.
 *
 * The production CSP is `script-src 'self'` (A5), so an inline `<script>` on
 * the sign-in page is a script the browser refuses to run — silently, on the
 * one screen a person meets before they trust anything here. Everything below
 * is therefore served from this origin and referenced by `{% static %}`.
 *
 * WHAT IT DOES, and nothing else:
 *   1. the Show toggle on the password field (design P-9's primitive);
 *   2. the passkey affordance — REVEALED only where the browser can do
 *      WebAuthn, and drawn at all only where the door says this deployment's
 *      host is a legal relying party;
 *   3. the ceremony itself, when the door has handed the page a challenge.
 *
 * WHAT IT NEVER DOES: fetch anything. There is no `fetch`, no `XMLHttpRequest`
 * and no URL in this file. Every exchange with the server is the page's own
 * form, posting to its own URL, which is what keeps the entrance's no-fetch
 * property true of the script as well as of the markup, and what keeps the
 * whole road working with the network panel closed.
 *
 * TWO THINGS ARE THE DOOR'S, NOT THIS FILE'S. Whether the passkey road exists
 * on this deployment (the host has to be a domain; an IP address is not a
 * relying-party id and no browser will run a ceremony against one) and what
 * the challenge is. Both arrive as markup the door rendered: an element that
 * is simply absent when the answer is no. A script that decided either one
 * would be a second opinion about a deployment it cannot see.
 */
(function () {
  "use strict";

  function reveal(root) {
    root.querySelectorAll("[data-reveal]").forEach(function (button) {
      button.addEventListener("click", function () {
        var field = document.getElementById(button.getAttribute("data-reveal"));
        if (!field) return;
        var hidden = field.type === "password";
        field.type = hidden ? "text" : "password";
        button.textContent = hidden ? "Hide" : "Show";
      });
    });
  }

  function supported() {
    return typeof window.PublicKeyCredential === "function";
  }

  /* Conditional mediation where the browser has it: a passkey the person can
   * pick from the address field itself. Asked for, never required — the
   * predicate is young and a browser that does not have it still gets the
   * button. */
  function conditionalAvailable() {
    var api = window.PublicKeyCredential;
    if (!api || typeof api.isConditionalMediationAvailable !== "function") {
      return Promise.resolve(false);
    }
    return api.isConditionalMediationAvailable().catch(function () {
      return false;
    });
  }

  function unhide(root) {
    if (!supported()) return;
    root.querySelectorAll("[data-needs='publickey-credential']").forEach(function (node) {
      node.hidden = false;
    });
    conditionalAvailable().then(function (ok) {
      if (!ok) return;
      root.querySelectorAll("[data-autocomplete-when-conditional]").forEach(function (field) {
        field.setAttribute("autocomplete", field.getAttribute("data-autocomplete-when-conditional"));
      });
    });
  }

  /* base64url, both ways. The options Zitadel answers carry base64url in the
   * places WebAuthn wants ArrayBuffers, and the assertion has to go back the
   * same way — the browser hands out ArrayBuffers and a form field is text. */
  function toBytes(text) {
    var padded = String(text).replace(/-/g, "+").replace(/_/g, "/");
    while (padded.length % 4) padded += "=";
    var raw = window.atob(padded);
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  function toText(buffer) {
    var bytes = new Uint8Array(buffer);
    var raw = "";
    for (var i = 0; i < bytes.length; i++) raw += String.fromCharCode(bytes[i]);
    return window.btoa(raw).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function ceremony(root) {
    var form = root.querySelector("[data-passkey-ceremony]");
    if (!form || !supported()) return;
    var carrier = form.querySelector("[name='options']");
    var answer = form.querySelector("[name='assertion']");
    if (!carrier || !answer) return;

    var options;
    try {
      options = JSON.parse(carrier.value);
    } catch (error) {
      return;
    }
    options.challenge = toBytes(options.challenge);
    (options.allowCredentials || []).forEach(function (credential) {
      credential.id = toBytes(credential.id);
    });

    navigator.credentials
      .get({ publicKey: options })
      .then(function (credential) {
        answer.value = JSON.stringify({
          id: credential.id,
          rawId: toText(credential.rawId),
          type: credential.type,
          response: {
            clientDataJSON: toText(credential.response.clientDataJSON),
            authenticatorData: toText(credential.response.authenticatorData),
            signature: toText(credential.response.signature),
            userHandle: credential.response.userHandle
              ? toText(credential.response.userHandle)
              : ""
          }
        });
        form.submit();
      })
      .catch(function () {
        /* The person dismissed the prompt, or the authenticator refused. The
         * page they are looking at is the page to try again from, so nothing
         * is navigated and nothing is announced: a sentence invented here
         * would be a sentence the server's own J7 table does not have. */
        var cancelled = form.querySelector("[data-passkey-cancelled]");
        if (cancelled) cancelled.hidden = false;
      });
  }

  function start() {
    reveal(document);
    unhide(document);
    ceremony(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
