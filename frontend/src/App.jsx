import { Routes, Route, useLocation } from "react-router-dom";
import Header from "./components/Header.jsx";
import Home from "./pages/Home.jsx";
import Shop from "./pages/Shop.jsx";
import AiSearch from "./pages/AiSearch.jsx";
import ProductDetail from "./pages/ProductDetail.jsx";
import Favourites from "./pages/Favourites.jsx";
import Placeholder from "./pages/Placeholder.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";

export default function App() {
  const location = useLocation();
  return (
    <div className="app-shell">
      <Header />
      <main>
        <div className="container">
          {/* Keyed on the route so navigating away from a page that just
              crashed resets the boundary instead of staying stuck on the
              "Something broke" screen forever. */}
          <ErrorBoundary key={location.pathname + location.search}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/shop" element={<Shop />} />
              <Route path="/ai-search" element={<AiSearch />} />
              <Route path="/product/:id" element={<ProductDetail />} />
              <Route path="/favourites" element={<Favourites />} />
              <Route
                path="/signup"
                element={
                  <Placeholder
                    title="Accounts are coming soon"
                    body="Sign-up isn't wired up yet, but the whole catalog below is already real and browsable."
                  />
                }
              />
            </Routes>
          </ErrorBoundary>
        </div>
      </main>
      <footer className="site-footer">
        <span>Libas — a browsing frontend over the real, live product database.</span>
        <span>Prices and stock shown as last scraped; always confirm on the brand's site.</span>
      </footer>
    </div>
  );
}
