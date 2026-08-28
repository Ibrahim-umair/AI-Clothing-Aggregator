import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "libas-wishlist"; // array of product id strings

function readStored() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

// Client-only saved-items list — there's no account system behind
// "Favourites" yet, so this persists to localStorage rather than faking a
// server-backed wishlist. Every component using this hook re-reads
// localStorage on the "libas-wishlist-change" event so the header's saved
// count and any open product grids stay in sync with each other.
export function useWishlist() {
  const [ids, setIds] = useState(readStored);

  useEffect(() => {
    function onChange() {
      setIds(readStored());
    }
    window.addEventListener("libas-wishlist-change", onChange);
    return () => window.removeEventListener("libas-wishlist-change", onChange);
  }, []);

  const toggle = useCallback((id) => {
    const key = String(id);
    const current = readStored();
    current.has(key) ? current.delete(key) : current.add(key);
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify([...current]));
    window.dispatchEvent(new Event("libas-wishlist-change"));
  }, []);

  return { ids, has: (id) => ids.has(String(id)), toggle };
}
