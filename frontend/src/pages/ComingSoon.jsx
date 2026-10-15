import { useState } from "react";
import { LogoMark } from "../components/icons.jsx";
import { submitSignupEmail } from "../lib/api.js";

// Pre-launch placeholder for the whole site. No one outside this project
// has heard of Libas AI yet, so the copy leads with what it does
// ("describe what you want, Libas AI finds it") rather than "we're back" -
// there's no "back" to reference, and it's natural-language search, not
// keyword search, so the copy says that rather than implying a plain
// search box. See App.jsx for why this fully replaces routing instead of
// living behind one.
export default function ComingSoon() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState("idle"); // idle | submitting | done | error

  async function handleSubmit(e) {
    e.preventDefault();
    if (status === "submitting") return;
    setStatus("submitting");
    try {
      await submitSignupEmail(email.trim());
      setStatus("done");
    } catch {
      setStatus("error");
    }
  }

  return (
    <div className="coming-soon">
      <div className="coming-soon__card">
        <LogoMark className="coming-soon__logo" size={56} />

        <p className="eyebrow coming-soon__eyebrow">AI-powered shopping</p>

        <h1 className="coming-soon__headline">
          Something's <em>coming</em> for how Pakistan shops online.
        </h1>

        <p className="coming-soon__subtext">
          Describe what you want. Libas AI finds it across every brand.
        </p>

        {status === "done" ? (
          <p className="coming-soon__confirm">You're on the list. We'll email you.</p>
        ) : (
          <form className="coming-soon__form" onSubmit={handleSubmit}>
            <input
              type="email"
              required
              placeholder="you@email.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="coming-soon__input"
              aria-label="Email address"
            />
            <button type="submit" className="coming-soon__submit" disabled={status === "submitting"}>
              {status === "submitting" ? "Sending..." : "Notify me"}
            </button>
          </form>
        )}
        {status === "error" && (
          <p className="coming-soon__error">That didn't go through, mind trying again?</p>
        )}

        <p className="coming-soon__footnote">Leave your email and you'll be the first to know.</p>

        <a className="coming-soon__contact" href="mailto:team@libasai.com">
          team@libasai.com
        </a>
      </div>
    </div>
  );
}
