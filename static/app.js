/* Post It — vanilla JS enhancements. Everything works with zero JS; these are progressive upgrades. */
(function () {
  "use strict";

  // Composer: show/hide custom-privacy fields
  function initComposer() {
    var select = document.querySelector('select[name="privacy"]');
    var box = document.getElementById("customFields");
    if (!select || !box) return;
    function sync() {
      box.hidden = select.value !== "custom";
    }
    select.addEventListener("change", sync);
    sync();
  }

  // Reactions: intercept reaction forms, update counts in place via JSON.
  // Falls back to plain form POST if fetch fails.
  function initReactions() {
    var forms = document.querySelectorAll("form.react-form");
    forms.forEach(function (form) {
      form.addEventListener("submit", function (ev) {
        ev.preventDefault();
        var fd = new FormData(form);
        fetch(form.action, {
          method: "POST",
          body: fd,
          headers: { Accept: "application/json" },
        })
          .then(function (res) {
            if (!res.ok) throw new Error("bad status");
            return res.json();
          })
          .then(function (data) {
            if (!data || !data.ok) throw new Error("not ok");
            var note = form.closest(".note");
            if (!note) return;
            var kinds = ["like", "love", "laugh", "fire", "skull"];
            kinds.forEach(function (k) {
              var btn = note.querySelector('.react-btn[data-kind="' + k + '"]');
              if (!btn) return;
              var count = data.counts && data.counts[k] != null ? data.counts[k] : 0;
              var cnt = btn.querySelector(".cnt");
              if (cnt) cnt.textContent = count > 0 ? count : "";
              btn.classList.toggle("mine", data.my_reaction === k);
            });
          })
          .catch(function () {
            // Graceful fallback: let the plain form POST happen
            form.submit();
          });
      });
    });
  }

  // Inline edit toggle: show the edit form on demand
  function initInlineEdit() {
    document.querySelectorAll("[data-edit-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-edit-toggle");
        var box = document.getElementById(id);
        if (box) box.hidden = !box.hidden;
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initComposer();
    initReactions();
    initInlineEdit();
  });
})();
