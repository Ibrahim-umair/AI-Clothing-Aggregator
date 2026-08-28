// Matches .card's exact structure/dimensions (see ProductCard.jsx) so
// swapping a skeleton grid for the real one causes zero layout shift.
export default function ProductCardSkeleton() {
  return (
    <div className="card card--skeleton" aria-hidden="true">
      <div className="card__media skeleton-block" />
      <div className="card__body">
        <span className="skeleton-line skeleton-line--store" />
        <span className="skeleton-line skeleton-line--title" />
        <span className="skeleton-line skeleton-line--price" />
      </div>
    </div>
  );
}
