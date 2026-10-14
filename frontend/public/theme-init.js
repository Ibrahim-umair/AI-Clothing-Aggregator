// Runs synchronously from <head>, before first paint, so the correct theme
// is already on <html> by the time CSS applies — otherwise the browser
// paints once using the OS's prefers-color-scheme (via the guarded @media
// rule in index.css) and only gets corrected to the actual saved/intended
// theme after React mounts and its useEffect runs (useTheme.js), which is
// the flash that was being reported.
//
// A separate file rather than an inline <script> so the Content-Security-
// Policy in public/_headers can stay at script-src 'self' with no
// 'unsafe-inline'. Deliberately a plain classic script (not type="module",
// not async/defer): it has to block, and it's a few hundred bytes.
(function () {
  try {
    var stored = window.localStorage.getItem("libas-theme");
    var theme =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: dark)").matches
          ? "dark"
          : "light";
    document.documentElement.setAttribute("data-theme", theme);
  } catch (e) {}
})();
