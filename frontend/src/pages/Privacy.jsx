import { Link } from "react-router-dom";
import LegalPage from "../components/LegalPage.jsx";
import { CONTACT_EMAIL, SITE_NAME } from "../lib/site.js";

// Every claim here is meant to describe what the code actually does —
// server/db_conversations.py (search_logs), server/rate_limit.py (in-memory
// IPs), server/rag.py (what goes to OpenAI), lib/consent.js + lib/
// analytics.js (cookies). Change those, change this page.
const SECTIONS = [
  {
    id: "who-we-are",
    heading: "Who we are",
    body: (
      <p>
        {SITE_NAME} is an independent search tool, run from Pakistan, that helps you find clothing across Pakistani
        brands&rsquo; online stores. We don&rsquo;t sell anything ourselves. Questions about this policy go to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    ),
  },
  {
    id: "what-we-collect",
    heading: "What we collect",
    body: (
      <>
        <p>There are no accounts, sign-ups, payments or contact forms, so we never ask for your name, email or phone number.</p>
        <ul>
          <li>
            <strong>Your AI searches.</strong> When you use AI search we store the text you typed, the filters our system
            worked out from it (for example &ldquo;men&rdquo;, &ldquo;kurta&rdquo;, &ldquo;under Rs 5,000&rdquo;), how many
            results came back, how long it took and what it cost us to run. This record is not linked to your IP
            address, device or any account.
          </li>
          <li>
            <strong>Your IP address, briefly.</strong> To stop automated abuse we count how many searches each IP address
            makes. These counts are held only in our server&rsquo;s memory, never written to the database, and are
            discarded within 24 hours.
          </li>
          <li>
            <strong>Standard hosting logs.</strong> Our hosting providers (Cloudflare for the website, Amazon Web Services
            for the search server) may record routine technical data such as IP address, browser type and the page
            requested, under their own policies, to keep the service running and secure.
          </li>
          <li>
            <strong>Analytics, only if you accept.</strong> See <a href="#cookies">Cookies and analytics</a> below.
          </li>
        </ul>
        <p>
          Please don&rsquo;t put personal details (names, phone numbers, addresses) into a search. The search
          doesn&rsquo;t need them, and they would be stored with the search text.
        </p>
      </>
    ),
  },
  {
    id: "ai-providers",
    heading: "AI search and third-party AI providers",
    body: (
      <>
        <p>
          AI search is powered by OpenAI. When you search, the text of your query (and nothing that identifies you)
          is sent to OpenAI&rsquo;s API to work out what you&rsquo;re looking for and to match it against products. The
          short summary shown above your results is written by the AI.
        </p>
        <p>
          Under OpenAI&rsquo;s API data-use policy at the time of writing, data sent through the API is not used to
          train OpenAI&rsquo;s models, and may be kept by OpenAI for up to 30 days for abuse monitoring before being
          deleted. OpenAI&rsquo;s own privacy policy governs that processing.
        </p>
        <p>Browsing the catalog (the Browse page, filters and product pages) does not use AI and sends nothing to OpenAI.</p>
      </>
    ),
  },
  {
    id: "how-we-use",
    heading: "How we use it",
    body: (
      <ul>
        <li>To run the search you asked for.</li>
        <li>To improve search quality, for example by finding searches that returned nothing or the wrong kind of item.</li>
        <li>To keep the service fast, affordable and protected from abuse.</li>
        <li>If you accepted analytics, to understand which pages and features are useful.</li>
      </ul>
    ),
  },
  {
    id: "cookies",
    heading: "Cookies and analytics",
    body: (
      <>
        <p>
          {SITE_NAME} itself sets no cookies. A few settings are saved in your browser&rsquo;s own storage and are
          never sent to us:
        </p>
        <ul>
          <li>your light/dark theme choice;</li>
          <li>the products you&rsquo;ve saved to Favourites;</li>
          <li>recent AI search results, so going back doesn&rsquo;t re-run them (cleared when you close the tab);</li>
          <li>your cookie choice.</li>
        </ul>
        <p>
          With your permission we use Google Analytics 4 to see aggregate usage: pages viewed, the device and
          browser type, approximate location (country/city) and interactions such as running a search. Google
          Analytics sets its own cookies (named <code>_ga</code> and <code>_ga_*</code>). None of it loads until you
          click &ldquo;Accept&rdquo;. If you decline, or never choose, it stays off. You can change your mind at any time
          through &ldquo;Cookie settings&rdquo; at the bottom of every page.
        </p>
      </>
    ),
  },
  {
    id: "sharing",
    heading: "Who we share it with",
    body: (
      <>
        <p>We do not sell your data or share it for advertising. It reaches only:</p>
        <ul>
          <li>the service providers named above (Cloudflare, Amazon Web Services, OpenAI, and Google if you accept analytics), solely to provide this service;</li>
          <li>authorities, if the law requires it.</li>
        </ul>
      </>
    ),
  },
  {
    id: "brand-sites",
    heading: "Links to brand stores",
    body: (
      <p>
        Product links take you to the brand&rsquo;s own website. Anything you do there, including buying, is covered
        by that brand&rsquo;s privacy policy, not this one. See our <Link to="/terms">Terms</Link> for more.
      </p>
    ),
  },
  {
    id: "retention",
    heading: "How long we keep it",
    body: (
      <ul>
        <li>Search records: up to 12 months, then deleted.</li>
        <li>Rate-limit IP counts: under 24 hours, in memory only.</li>
        <li>Analytics data (if you accepted): 2 months in Google Analytics.</li>
        <li>Browser storage: until you clear it.</li>
      </ul>
    ),
  },
  {
    id: "your-choices",
    heading: "Your choices",
    body: (
      <>
        <ul>
          <li>Decline or withdraw analytics consent through &ldquo;Cookie settings&rdquo;.</li>
          <li>Clear this site&rsquo;s data in your browser to remove your favourites, theme and cached results.</li>
          <li>Browse without using AI search, so nothing goes to OpenAI.</li>
        </ul>
        <p>
          Because search records aren&rsquo;t tied to you, we usually can&rsquo;t tell which ones are yours. If you
          searched for something you&rsquo;d like removed, email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>{" "}
          with the exact wording and roughly when you searched, and we&rsquo;ll delete matching records.
        </p>
      </>
    ),
  },
  {
    id: "children",
    heading: "Children",
    body: <p>{SITE_NAME} is not aimed at children under 13, and we don&rsquo;t knowingly collect their information.</p>,
  },
  {
    id: "changes",
    heading: "Changes to this policy",
    body: (
      <p>
        If we change what we collect or who we share it with, we&rsquo;ll update this page and its date. If the
        analytics change, we&rsquo;ll ask for your consent again.
      </p>
    ),
  },
];

export default function Privacy() {
  return (
    <LegalPage
      title="Privacy policy"
      intro={`What ${SITE_NAME} collects when you search, what goes to the AI provider behind it, and what stays in your own browser.`}
      sections={SECTIONS}
    />
  );
}
