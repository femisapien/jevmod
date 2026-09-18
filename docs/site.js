/* jevmod.dev: live demo, chips, copy buttons, invite toggle. No dependencies. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };

  /* ---- hosted invite buttons: one function for #inviteBtn and #inviteBtn2 ---- */
  function inviteToggle() {
    var host = $("hosted");
    var inv = host ? (host.dataset.invite || "").trim() : "";
    ["inviteBtn", "inviteBtn2"].forEach(function (id) {
      var b = $(id);
      if (!b) return;
      if (inv) {
        b.href = inv;
        b.rel = "noopener";
        b.textContent = "Add to Discord";
        b.removeAttribute("aria-disabled");
        b.classList.add("primary");
      } else {
        b.textContent = "Add to Discord, coming soon";
        b.removeAttribute("href");
        b.setAttribute("aria-disabled", "true");
        b.classList.remove("primary");
      }
    });
  }
  inviteToggle();

  /* ---- copy buttons (.code > button.copy + pre) ---- */
  document.querySelectorAll(".code .copy").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var pre = btn.parentElement.querySelector("pre");
      var text = pre ? pre.textContent.replace(/\s+$/, "") : "";
      var label = btn.textContent;
      function done(ok) {
        btn.textContent = ok ? "copied" : "copy failed";
        setTimeout(function () { btn.textContent = label; }, 1400);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      } else { done(false); }
    });
  });

  /* ---- live demo ---- */
  var demo = $("demo");
  if (!demo) return;
  var qs = new URLSearchParams(location.search);
  var DEMO_URL = (qs.get("demo") || demo.dataset.demo || "").replace(/\/$/, "");
  var TH = { spam: 0.85, scam: 0.75, harassment: 0.75, nsfw: 0.80, selfharm: 0.80, doxxing: 0.80, minors: 0.70 };
  var CATS = Object.keys(TH);
  var LABEL = { spam: "spam", scam: "scam", harassment: "harassment", nsfw: "adult", selfharm: "self-harm", doxxing: "doxxing", minors: "minors" };
  var form = $("liveForm"), input = $("liveText"), btn = $("liveBtn"), chips = $("chips"),
      result = $("result"), cats = $("cats"), bars = $("bars"), msg = $("liveMsg"), closedEl = $("liveClosed");
  var closed = false, inflight = false;

  bars.innerHTML = CATS.map(function (c) {
    return '<span class="n">' + LABEL[c] + '</span><span class="b"><s style="left:' + (TH[c] * 100) + '%"></s><i data-c="' + c + '"></i></span><span class="v" data-v="' + c + '">0.00</span>';
  }).join("");

  function paint(scores) {
    CATS.forEach(function (c) {
      var v = scores && c in scores ? +scores[c] : 0, over = v >= TH[c];
      var bar = bars.querySelector('i[data-c="' + c + '"]'), val = bars.querySelector('[data-v="' + c + '"]');
      bar.style.width = (v * 100) + "%";
      bar.classList.toggle("hit", over);
      val.textContent = v.toFixed(2);
      val.classList.toggle("hit", over);
    });
  }

  function show(d) {
    var hit = d.action !== "none" && d.category ? d.category : null;
    result.classList.remove("hit", "ok");
    if (!d.judged) {
      result.textContent = "too short to judge, would pass";
      result.classList.add("ok");
    } else if (hit) {
      result.textContent = LABEL[hit] + " " + (+d.probability).toFixed(2) + ", would be flagged";
      result.classList.add("hit");
    } else {
      result.textContent = "nothing over its line, would pass";
      result.classList.add("ok");
    }
    paint(d.scores);
    cats.hidden = false;
  }

  function closeLive(reason) {
    closed = true;
    btn.disabled = true;
    closedEl.hidden = false;
    if (reason) closedEl.textContent = reason;
  }

  if (!DEMO_URL) closeLive();
  else fetch(DEMO_URL + "/demo/health", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
    .then(function (h) { if (!h.open) closeLive(); })
    .catch(function () { closeLive(); });

  function submit() {
    var text = input.value.trim();
    if (closed || inflight) return;
    if (!text) { msg.textContent = "Type something first."; input.focus(); return; }
    inflight = true; btn.disabled = true; msg.textContent = "asking Jev";
    fetch(DEMO_URL + "/demo/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: text }) })
      .then(function (r) {
        if (r.status === 429) { msg.textContent = "Slow down: 6 checks a minute, 40 a day per visitor."; return; }
        if (r.status === 503) { msg.textContent = ""; closeLive("The demo budget for this month is used up. Run jevmod check with your own key."); return; }
        if (!r.ok) { msg.textContent = "The demo server answered " + r.status + "."; return; }
        return r.json().then(function (d) {
          show(d);
          msg.textContent = d.reason === "cache" ? "cached, cost $0" : d.judged ? "live" : "not sent to the model";
        });
      })
      .catch(function () { msg.textContent = "Could not reach the demo server."; })
      .then(function () { inflight = false; if (!closed) btn.disabled = false; });
  }

  form.addEventListener("submit", function (e) { e.preventDefault(); submit(); });
  chips.addEventListener("click", function (e) {
    var c = e.target.closest(".chip"); if (!c) return;
    Array.prototype.forEach.call(chips.children, function (x) { x.classList.toggle("on", x === c); });
    input.value = c.dataset.text;
    if (closed) { input.focus(); return; }
    submit();
  });
  input.addEventListener("input", function () {
    Array.prototype.forEach.call(chips.children, function (x) { x.classList.toggle("on", x.dataset.text === input.value); });
  });
})();
