import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useWishlist } from "../hooks/useWishlist.js";
import { fetchProduct } from "../lib/api.js";
import ProductCard from "../components/ProductCard.jsx";
import ProductCardSkeleton from "../components/ProductCardSkeleton.jsx";

// Saved items are client-only (see useWishlist) — there's no account system
// behind this yet, so "Favourites" just resolves whatever product ids are
// in localStorage against the real API rather than faking a server list.
export default function Favourites() {
  const { ids } = useWishlist();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([...ids].map((id) => fetchProduct(id).catch(() => null)))
      .then((results) => !cancelled && setProducts(results.filter(Boolean)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [ids, retryToken]);

  if (loading) {
    return (
      <div className="product-grid product-grid--4" style={{ padding: "20px clamp(16px, 3.5vw, 40px) 60px" }}>
        {Array.from({ length: Math.min(4, ids.size) || 4 }, (_, i) => (
          <ProductCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  // ids.size > 0 but nothing resolved means every fetch for a saved item
  // failed (network drop, API down) — genuinely different from the user
  // simply not having saved anything, and "Nothing saved yet" would be a
  // misleading thing to tell someone whose favourites just failed to load.
  if (products.length === 0 && ids.size > 0) {
    return (
      <div className="empty-state">
        <h3>Couldn't load your favourites</h3>
        <p>Something went wrong reaching the server. Check your connection and try again.</p>
        <button type="button" className="btn btn--primary" onClick={() => setRetryToken((t) => t + 1)}>
          Try again
        </button>
      </div>
    );
  }

  if (products.length === 0) {
    return (
      <div className="empty-state">
        <h3>Nothing saved yet</h3>
        <p>Tap the heart on any product to save it here — it stays on this device.</p>
        <Link className="btn btn--primary" to="/shop">
          Start browsing
        </Link>
      </div>
    );
  }

  return (
    <>
      <div className="shop-heading">
        <div className="shop-heading__copy">
          <h1>Favourites</h1>
          <p>Saved on this device — clear your browser data and this list resets.</p>
        </div>
      </div>
      <div className="product-grid product-grid--4" style={{ padding: "20px clamp(16px, 3.5vw, 40px) 60px" }}>
        {products.map((p) => (
          <ProductCard
            key={p.id}
            product={{
              id: p.id,
              title: p.title,
              store_display: p.store_display,
              image_url: p.image_url,
              price: p.price,
              compare_at_price: p.compare_at_price,
              currency: p.currency,
              available: p.available,
            }}
          />
        ))}
      </div>
    </>
  );
}
