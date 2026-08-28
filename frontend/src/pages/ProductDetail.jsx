import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { formatPrice, discountPercent, decodeHtmlEntities } from "../lib/format.js";
import { colorHex } from "../lib/colors.js";
import { ArrowUpRightIcon, ExpandIcon, HeartIcon } from "../components/icons.jsx";
import { fetchProduct, fetchProducts } from "../lib/api.js";
import { useWishlist } from "../hooks/useWishlist.js";
import ProductCard from "../components/ProductCard.jsx";

export default function ProductDetail() {
  const { id } = useParams();
  const [product, setProduct] = useState(null);
  const [status, setStatus] = useState("loading"); // "loading" | "ready" | "not_found" | "error"
  const [activeImage, setActiveImage] = useState(0);
  const [pickedSize, setPickedSize] = useState(null);
  const [pickedColor, setPickedColor] = useState(null);
  const [related, setRelated] = useState([]);
  const [retryToken, setRetryToken] = useState(0);
  const { has, toggle } = useWishlist();

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    setActiveImage(0);
    setRelated([]);
    fetchProduct(id)
      .then((data) => {
        if (cancelled) return;
        setProduct(data);
        setPickedSize(data.sizes?.find((s) => s.available)?.label ?? data.sizes?.[0]?.label ?? null);
        setPickedColor(data.colors?.[0] ?? null);
        setStatus("ready");

        const [gender, branch, sub, category] = data.category_path || [];
        if (gender) {
          fetchProducts(
            { gender, branch, sub, category },
            { pageSize: 6, sort: "newest" }
          )
            .then((r) => !cancelled && setRelated(r.products.filter((p) => String(p.id) !== String(id)).slice(0, 5)))
            .catch(() => {});
        }
      })
      // A 404 means the product genuinely doesn't exist (deleted, bad
      // link) — different from every other failure (network drop, API
      // down), which is likely transient and worth a retry rather than
      // "this doesn't exist" copy.
      .catch((err) => !cancelled && setStatus(err?.status === 404 ? "not_found" : "error"));
    return () => {
      cancelled = true;
    };
  }, [id, retryToken]);

  if (status === "loading") {
    return (
      <div className="detail" aria-hidden="true">
        <div className="gallery__thumbs">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="gallery__thumb skeleton-block" />
          ))}
        </div>
        <div className="gallery__main skeleton-block" />
        <div className="detail__info">
          <span className="skeleton-line" style={{ width: "30%", height: 12 }} />
          <span className="skeleton-line" style={{ width: "70%", height: 26, marginTop: 10 }} />
          <span className="skeleton-line" style={{ width: "25%", height: 22, marginTop: 18 }} />
          <span className="skeleton-line" style={{ width: "95%", marginTop: 22 }} />
          <span className="skeleton-line" style={{ width: "88%", marginTop: 8 }} />
          <span className="skeleton-line" style={{ width: "60%", marginTop: 8 }} />
        </div>
      </div>
    );
  }

  if (status === "not_found") {
    return (
      <div className="empty-state">
        <h3>We couldn't find that piece</h3>
        <p>It may have sold out or been removed from the catalog.</p>
        <Link className="btn btn--primary" to="/shop">
          Keep browsing
        </Link>
      </div>
    );
  }

  if (status === "error" || !product) {
    return (
      <div className="empty-state">
        <h3>Couldn't load this product</h3>
        <p>Something went wrong reaching the server. Check your connection and try again.</p>
        <button type="button" className="btn btn--primary" onClick={() => setRetryToken((t) => t + 1)}>
          Try again
        </button>
      </div>
    );
  }

  const discount = discountPercent(product.price, product.compare_at_price);
  const images = product.images && product.images.length > 0 ? product.images : [product.image_url];
  const saved = has(product.id);

  return (
    <>
      <Breadcrumb product={product} />

      <div className="detail">
        {images.length > 1 && (
          <div className="gallery__thumbs">
            {images.map((src, i) => (
              <button
                key={src + i}
                className="gallery__thumb"
                data-active={i === activeImage}
                onClick={() => setActiveImage(i)}
                aria-label={`View image ${i + 1}`}
              >
                <img src={src} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        )}

        <div className="gallery__main">
          <img src={images[activeImage]} alt={product.title} />
          <a
            className="gallery__expand"
            href={images[activeImage]}
            target="_blank"
            rel="noreferrer"
            aria-label="View full-size image"
          >
            <ExpandIcon size={16} />
          </a>
        </div>

        <div className="detail__info">
          <div>
            <span className="detail__store">{product.store_display}</span>
            <h1 className="detail__title">{product.title}</h1>
          </div>

          <div className="detail__price-row">
            <span className="detail__price">{formatPrice(product.price, product.currency)}</span>
            {product.compare_at_price && (
              <span className="price-compare">{formatPrice(product.compare_at_price, product.currency)}</span>
            )}
            {discount && <span className="discount-tag">Save {discount}%</span>}
            <span className="detail__price-note">Price incl. of all taxes, as last scraped</span>
          </div>

          {!product.available && <span className="oos-note">Currently out of stock at {product.store_display}</span>}

          {product.description && (
            <p className="detail__description">{decodeHtmlEntities(product.description)}</p>
          )}

          {product.sizes?.length > 0 && (
            <div>
              <div className="option-head">
                <b>Size</b>
              </div>
              <div className="size-row">
                {product.sizes.map((s) => (
                  <button
                    type="button"
                    key={s.label}
                    className={`size-pill size-pill--selectable${pickedSize === s.label ? " size-pill--active" : ""}${!s.available ? " size-pill--unavailable" : ""}`}
                    onClick={() => s.available && setPickedSize(s.label)}
                    title={s.available ? undefined : "Out of stock"}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {product.colors?.length > 0 && (
            <div>
              <div className="option-head">
                <b>Color{pickedColor ? `: ${pickedColor}` : ""}</b>
              </div>
              <div className="swatch-row">
                {product.colors.map((c) => (
                  <button
                    type="button"
                    key={c}
                    className="swatch"
                    data-active={pickedColor === c}
                    style={{ background: colorHex(c) }}
                    title={c}
                    aria-label={c}
                    onClick={() => setPickedColor(c)}
                  />
                ))}
              </div>
            </div>
          )}

          <div className="cta-row">
            <a className="btn btn--primary" href={product.product_url} target="_blank" rel="noreferrer">
              View on {product.store_display} <ArrowUpRightIcon size={15} />
            </a>
            <button
              type="button"
              className="btn btn--ghost"
              data-active={saved}
              onClick={() => toggle(product.id)}
              aria-label={saved ? "Remove from favourites" : "Save to favourites"}
            >
              <HeartIcon size={16} fill={saved ? "currentColor" : "none"} /> {saved ? "Saved" : "Save"}
            </button>
          </div>
        </div>
      </div>

      {related.length > 0 && (
        <section className="related-section">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Keep exploring</span>
              <h2>You Might Also Like</h2>
            </div>
          </div>
          <div className="product-grid product-grid--5">
            {related.map((p) => (
              <ProductCard key={p.id} product={p} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}

function Breadcrumb({ product }) {
  const path = product.category_path || [];
  return (
    <div className="breadcrumb">
      <Link to="/shop">Home</Link>
      {path.slice(0, -1).map((label, i) => (
        <span key={label} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="breadcrumb__sep">/</span>
          <Link
            to={`/shop?${new URLSearchParams(
              Object.fromEntries(
                [["gender", 0], ["branch", 1], ["sub", 2], ["category", 3]]
                  .filter(([, idx]) => idx <= i)
                  .map(([key, idx]) => [key, path[idx]])
              )
            ).toString()}`}
          >
            {label}
          </Link>
        </span>
      ))}
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <span className="breadcrumb__sep">/</span>
        <span className="breadcrumb__current">{product.title}</span>
      </span>
    </div>
  );
}
