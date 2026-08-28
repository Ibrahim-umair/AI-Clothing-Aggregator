import { Link } from "react-router-dom";

// Shared "not built yet" page for nav items that need to exist and route
// somewhere (Favourite, Sign Up) without real functionality behind them yet.
export default function Placeholder({ title, body }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{body}</p>
      <Link className="btn btn--primary" to="/">
        Back home
      </Link>
    </div>
  );
}
