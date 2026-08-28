/* Reading timer for the digest page.
 *
 * Accumulated seconds survive the page reloads that the action buttons cause
 * (sessionStorage, per-item), so flagging an item mid-read never loses the
 * reading time already earned.
 *
 * The timer normally pauses when the tab is hidden — otherwise every
 * background tab would bank reading time nobody did. But "Open source" opens
 * the article in a NEW tab, which hides this one, so reading the actual
 * article used to earn only the few seconds before the click. Once a source
 * link is opened, that item therefore keeps counting while this tab is
 * hidden.
 *
 * Two bounds keep those minutes honest, because RACP minutes must be measured
 * and never inflated:
 *   - only ONE item accrues while hidden: the last whose source was opened;
 *   - a hidden stretch is credited for at most HIDDEN_BUDGET_SECONDS, so a tab
 *     left open overnight banks half an hour, not eight. Returning to the page
 *     resets the budget for the next excursion.
 */
(function () {
  "use strict";

  var STORE = "cpd-read-timers";
  var EXTERNAL_STORE = "cpd-read-external";
  var HIDDEN_BUDGET_SECONDS = 1800;

  var counters = {};
  var activeExternal = null;
  try { counters = JSON.parse(sessionStorage.getItem(STORE) || "{}"); } catch (e) {}
  try { activeExternal = sessionStorage.getItem(EXTERNAL_STORE) || null; } catch (e) {}

  var hiddenElapsed = 0;

  function save() {
    try {
      sessionStorage.setItem(STORE, JSON.stringify(counters));
      if (activeExternal === null) sessionStorage.removeItem(EXTERNAL_STORE);
      else sessionStorage.setItem(EXTERNAL_STORE, activeExternal);
    } catch (e) {}
  }

  function paint(d, seconds) {
    var t = d.querySelector(".timer");
    if (t) {
      t.textContent = Math.floor(seconds / 60) + ":" +
        String(seconds % 60).padStart(2, "0");
    }
    var input = d.querySelector(".seconds-input");
    if (input) input.value = seconds;
  }

  document.querySelectorAll("details.news-item").forEach(function (d) {
    var id = d.dataset.item;
    if (counters[id]) paint(d, counters[id]);

    var link = d.querySelector("a.source-link");
    if (link) {
      link.addEventListener("click", function () {
        activeExternal = id;
        hiddenElapsed = 0;
        save();
      });
    }

    var readForm = d.querySelector("form[action$='/read']");
    if (readForm) {
      readForm.addEventListener("submit", function () {
        delete counters[id];
        if (activeExternal === id) activeExternal = null;
        save();
      });
    }
  });

  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) hiddenElapsed = 0;
  });

  window.setInterval(function () {
    var hidden = document.hidden;
    if (hidden) {
      hiddenElapsed += 1;
      if (!activeExternal || hiddenElapsed > HIDDEN_BUDGET_SECONDS) return;
    }
    var changed = false;
    document.querySelectorAll("details.news-item[open]").forEach(function (d) {
      var id = d.dataset.item;
      if (hidden && id !== activeExternal) return;
      counters[id] = (counters[id] || 0) + 1;
      changed = true;
      paint(d, counters[id]);
    });
    if (changed) save();
  }, 1000);
})();
