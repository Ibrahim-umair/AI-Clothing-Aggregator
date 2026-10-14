import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { LEGAL_LAST_UPDATED } from "../lib/site.js";
import { useDocumentMeta } from "../hooks/useDocumentMeta.js";

// Shared reading layout for /privacy and /terms: one narrow text column,
// a table of contents, and in-page #anchors that actually scroll (react-
// router doesn't do hash scrolling on its own — the cookie banner links
// straight to /privacy#cookies).
export default function LegalPage({ title, intro, sections }) {
  const { hash } = useLocation();
  useDocumentMeta({ title, description: intro });

  useEffect(() => {
    if (!hash) {
      window.scrollTo(0, 0);
      return;
    }
    document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <article className="legal">
      <header className="legal__header">
        <h1>{title}</h1>
        <p className="legal__updated">Last updated {LEGAL_LAST_UPDATED}</p>
        <p className="legal__intro">{intro}</p>
      </header>

      <nav className="legal__toc" aria-label="On this page">
        <ol>
          {sections.map((s) => (
            <li key={s.id}>
              <a href={`#${s.id}`}>{s.heading}</a>
            </li>
          ))}
        </ol>
      </nav>

      {sections.map((s) => (
        <section key={s.id} id={s.id} className="legal__section">
          <h2>{s.heading}</h2>
          {s.body}
        </section>
      ))}
    </article>
  );
}
