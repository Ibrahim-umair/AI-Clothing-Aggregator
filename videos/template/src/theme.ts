import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

// Local fonts only: renders must not depend on the network.
export const fontsReady = Promise.all([
  loadFont({ family: "Geist", url: staticFile("fonts/Geist.woff2"), weight: "300 700" }),
  loadFont({ family: "Geist Mono", url: staticFile("fonts/GeistMono.woff2"), weight: "400 600" }),
  loadFont({ family: "Instrument Serif", url: staticFile("fonts/InstrumentSerif-Italic.woff2"), style: "italic", weight: "400" }),
]);

// Libas "Ink on Paper" identity (frontend/src/styles/index.css :root):
// near-white ground, ink text, muted olive accent, gold secondary, deep-red
// sale. Borders do the separating; shadows stay soft and low.
export const C = {
  bg: "#f7f7f5",
  panel: "#ffffff",
  panelSolid: "#f1f1ef",
  field: "#f4f4f2",
  hair: "rgba(20, 22, 26, 0.08)",
  hairStrong: "rgba(20, 22, 26, 0.11)",
  text: "#14161a",
  soft: "#63665f",
  faint: "#8a8d84",
  accent: "#6b7649",
  accentStrong: "#4e5836",
  accentSoft: "#eef0ea",
  gold: "#b9822a",
};

export const SANS = '"Geist", -apple-system, "Segoe UI", sans-serif';
export const MONO = '"Geist Mono", ui-monospace, monospace';
export const SERIF = '"Instrument Serif", Georgia, serif';
