import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "libas-theme"; // "light" | "dark"

function getInitialTheme() {
  // Light is the default regardless of the OS's own prefers-color-scheme
  // — a real user request, not a system-preference fallback. Once someone
  // explicitly toggles, that choice is what's remembered from then on.
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return "light";
}

export function useTheme() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "light" ? "dark" : "light"));
  }, []);

  return { theme, toggle };
}
