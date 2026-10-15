import ErrorBoundary from "./components/ErrorBoundary.jsx";
import ComingSoon from "./pages/ComingSoon.jsx";

// The whole app is parked on this one screen for every URL while a
// ground-up rebuild happens elsewhere — see coming-soon branch notes.
// Intentionally no Header/Routes: there is nothing else on the site to
// navigate to right now, and re-adding them later is a one-line revert
// (git log for the commit before this one has the real app back).
export default function App() {
  return (
    <div className="app-shell app-shell--coming-soon">
      <ErrorBoundary>
        <ComingSoon />
      </ErrorBoundary>
    </div>
  );
}
