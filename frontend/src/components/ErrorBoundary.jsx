import { Component } from "react";

// Catches JS exceptions thrown during render anywhere below it (a
// malformed API response reaching a component that assumes a shape it
// doesn't have, a null-reference bug, etc.) — a different failure mode
// from a failed fetch (see PageError in lib/errors.jsx), which never
// throws, just resolves with an error state. Without this, a render
// exception takes down the whole React tree and the user sees a blank
// white page with no indication anything went wrong.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error("Unhandled render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="empty-state">
          <h3>Something broke</h3>
          <p>This page hit an unexpected error. Reloading usually fixes it.</p>
          <button type="button" className="btn btn--primary" onClick={() => window.location.reload()}>
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
