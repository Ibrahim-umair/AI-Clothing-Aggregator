import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import Header from "./components/Header.jsx";
import Home from "./pages/Home.jsx";
import Shop from "./pages/Shop.jsx";
import AiSearch from "./pages/AiSearch.jsx";
import ProductDetail from "./pages/ProductDetail.jsx";
import Favourites from "./pages/Favourites.jsx";
import Placeholder from "./pages/Placeholder.jsx";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { lazy, Suspense } from "react";
// Loaded only on /admin, so shoppers never download it.
const Admin = lazy(() => import("./pages/Admin.jsx"));

export default function App() {
  const location = useLocation();
  // The scrape admin has its own layout, without the shopper header.
  if (location.pathname.startsWith("/admin")) return <Suspense fallback={null}><Admin /></Suspense>;
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
              {/* AI search is the landing page; the old home (occasions etc.) lives on /home. */}
              <Route path="/" element={<Navigate to="/ai-search" replace />} />
              <Route path="/home" element={<Home />} />
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
    </div>
  );
}
