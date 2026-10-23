// Turn every <div class="cast" data-cast="…"> into an asciinema player. The player library is
// vendored beside this file, so the documentation works where the platform is served, offline.
(function () {
  function mount() {
    if (!window.AsciinemaPlayer) return;
    document.querySelectorAll("div.cast[data-cast]").forEach(function (el) {
      if (el.dataset.mounted) return;
      el.dataset.mounted = "1";
      AsciinemaPlayer.create(el.dataset.cast, el, {
        cols: 100, rows: 28, idleTimeLimit: 2, speed: 1.5, theme: "monokai", fit: "width",
        poster: "npt:" + (el.dataset.poster || "0:03"), terminalFontSize: "12px"
      });
    });
  }
  if (typeof document$ !== "undefined") document$.subscribe(mount); else document.addEventListener("DOMContentLoaded", mount);
})();
