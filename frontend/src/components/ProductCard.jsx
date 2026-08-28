import { Link } from "react-router-dom";
import { formatPrice, discountPercent } from "../lib/format.js";
import { useWishlist } from "../hooks/useWishlist.js";
import { HeartIcon } from "./icons.jsx";

export default function ProductCard({ product }) {
  const discount = discountPercent(product.price, product.compare_at_price);
  const { has, toggle } = useWishlist();
  const saved = has(product.id);

  return (
    <Link to={`/product/${product.id}`} className="card">
      <div className="card__media">
        <img src={product.image_url} alt={product.title} loading="lazy" />
        <button
          type="button"
          className="card__heart"
          data-active={saved}
          aria-label={saved ? "Remove from favourites" : "Save to favourites"}
          onClick={(e) => {
            e.preventDefault();
            toggle(product.id);
          }}
        >
          <HeartIcon size={15} fill={saved ? "currentColor" : "none"} />
        </button>
        {discount && <span className="badge badge--sale">-{discount}%</span>}
        {!product.available && <span className="badge badge--oos">Out of stock</span>}
      </div>
      <div className="card__body">
        <span className="card__store">{product.store_display}</span>
        <span className="card__title">{product.title}</span>
        <div className="price-row">
          <span className={`price${discount ? " price--sale" : ""}`}>
            {formatPrice(product.price, product.currency)}
          </span>
          {product.compare_at_price && (
            <span className="price-compare">{formatPrice(product.compare_at_price, product.currency)}</span>
          )}
        </div>
      </div>
    </Link>
  );
}
