import { Link } from "react-router-dom";
import LegalPage from "../components/LegalPage.jsx";
import { CONTACT_EMAIL, SITE_NAME } from "../lib/site.js";

const SECTIONS = [
  {
    id: "about",
    heading: "What this service is",
    body: (
      <>
        <p>
          {SITE_NAME} (&ldquo;we&rdquo;, &ldquo;us&rdquo;) is a free search tool that finds clothing across the online
          stores of Pakistani clothing brands and links you to them. By using the site you agree to these terms.
        </p>
        <p>
          We are not a shop. We don&rsquo;t sell, ship or take payment for anything, and we aren&rsquo;t affiliated with
          or endorsed by the brands we list. Brand names, logos, product photos and descriptions belong to their
          owners and are shown only to help you find their products.
        </p>
      </>
    ),
  },
  {
    id: "acceptable-use",
    heading: "Acceptable use",
    body: (
      <>
        <p>Use {SITE_NAME} for your own shopping. Please don&rsquo;t:</p>
        <ul>
          <li>scrape, bulk-download or automatically query the site or its API;</li>
          <li>try to get around rate limits or other usage limits, for example by rotating IP addresses;</li>
          <li>probe, attack or disrupt the service, or try to reach systems or data you weren&rsquo;t given access to;</li>
          <li>submit searches that are unlawful, abusive, or designed to manipulate the AI (prompt injection);</li>
          <li>use the service or its results to build a competing product or dataset;</li>
          <li>present our results as your own, or suggest we endorse you.</li>
        </ul>
        <p>We may block access for anyone who breaks these rules.</p>
      </>
    ),
  },
  {
    id: "ai-results",
    heading: "AI-generated results",
    body: (
      <>
        <p>
          Search results, product matches and the summary text above them are produced automatically by AI and by
          software that sorts each brand&rsquo;s products into categories. They can be wrong: an item can be filed
          under the wrong category, gender, colour or size, or a match can miss what you meant.
        </p>
        <p>
          Treat results as suggestions, not advice. Before you buy, check the product&rsquo;s details, size guide and
          photos on the brand&rsquo;s own website.
        </p>
      </>
    ),
  },
  {
    id: "prices-and-links",
    heading: "Prices, stock and brand websites",
    body: (
      <>
        <p>
          Prices, discounts and availability are collected from brands&rsquo; websites at intervals, so they can be out
          of date by the time you see them. The price and stock on the brand&rsquo;s own site is the one that counts.
        </p>
        <p>
          When you follow a link to a brand&rsquo;s store you leave {SITE_NAME}. Any purchase is a contract between you
          and that brand, under their terms, delivery and returns policies. We aren&rsquo;t responsible for their
          products, websites, pricing, orders, deliveries, refunds or content.
        </p>
      </>
    ),
  },
  {
    id: "content",
    heading: "Our content and takedown requests",
    body: (
      <p>
        The {SITE_NAME} site, its design and its software are ours. Product content belongs to the brands. If you
        represent a brand and want your products changed or removed, write to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a> and we&rsquo;ll act promptly.
      </p>
    ),
  },
  {
    id: "disclaimer",
    heading: "No warranty",
    body: (
      <p>
        The service is provided free and &ldquo;as is&rdquo;. We don&rsquo;t promise it will always be available, error-free
        or that results will be accurate, complete or current.
      </p>
    ),
  },
  {
    id: "liability",
    heading: "Limitation of liability",
    body: (
      <>
        <p>To the fullest extent the law allows, we are not liable for any loss or damage arising from:</p>
        <ul>
          <li>relying on an AI-generated match, summary, category, price or stock status;</li>
          <li>anything you buy, or any dealings you have, with a brand or other website we link to;</li>
          <li>the service being unavailable, slow or interrupted;</li>
          <li>any indirect or consequential loss, such as lost time or a missed sale.</li>
        </ul>
        <p>
          Where liability can&rsquo;t be excluded, our total liability to you is limited to PKR 5,000. Nothing in these
          terms limits liability that cannot legally be limited.
        </p>
      </>
    ),
  },
  {
    id: "privacy",
    heading: "Privacy",
    body: (
      <p>
        How we handle searches and analytics is explained in our <Link to="/privacy">Privacy policy</Link>.
      </p>
    ),
  },
  {
    id: "changes",
    heading: "Changes and ending the service",
    body: (
      <p>
        We may change or stop the service, or update these terms, at any time. The date at the top shows the latest
        version. Continuing to use the site after a change means you accept the new terms.
      </p>
    ),
  },
  {
    id: "law",
    heading: "Governing law",
    body: <p>These terms are governed by the laws of Pakistan, and its courts have jurisdiction over any dispute.</p>,
  },
  {
    id: "contact",
    heading: "Contact",
    body: (
      <p>
        Questions about these terms: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    ),
  },
];

export default function Terms() {
  return (
    <LegalPage
      title="Terms of use"
      intro={`The ground rules for using ${SITE_NAME}, and what we can and can't promise about AI-matched results and the brand stores we link to.`}
      sections={SECTIONS}
    />
  );
}
