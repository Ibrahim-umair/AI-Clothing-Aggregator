// Real /api/search results for "Vintage wash brown hoodie" (gender: Men),
// first result per distinct brand — same set as video v1.
export type Product = { brand: string; title: string; price: number; compare: number | null; img: string };

export const HOODIE_QUERY = "Vintage wash brown hoodie";
export const HOODIE_ANSWER = "Here are brown hoodies with a vintage wash.";
export const HOODIE_CHIPS = ["Zip-up", "Pullover", "Oversized", "Cropped"];

export const HOODIES: Product[] = [
  { brand: "Cambridge", title: "Drop Shoulder Acid Wash Hoodie", price: 5316, compare: 7595, img: "products/s0-0.jpg" },
  { brand: "Engine", title: "Men Basic Hoodie", price: 3250, compare: 6499, img: "products/s0-1.jpg" },
  { brand: "Outfitters", title: "Slogan Print Hoodie", price: 5990, compare: null, img: "products/s0-2.jpg" },
  { brand: "Uniworth", title: "Brown Texture Pullover Hoodie", price: 4871, compare: 6495, img: "products/s0-3.jpg" },
  { brand: "Breakout", title: "Graphic Hoodie", price: 2999, compare: 5999, img: "products/s0-4.jpg" },
  { brand: "ONE (Be-One)", title: "Graphic Pullover Hoodie", price: 4193, compare: 5990, img: "products/s0-5.jpg" },
];

export const rs = (v: number) => `Rs ${Math.round(v).toLocaleString("en-US")}`;

export type Search = { query: string; answer: string; chips: string[]; cards: Product[] };

export const SEARCHES: Search[] = [
  { query: HOODIE_QUERY, answer: HOODIE_ANSWER, chips: HOODIE_CHIPS, cards: HOODIES },
  {
    query: "Relaxed-fit drop-shoulder waffle-knit sweater",
    answer: "Here are relaxed-fit, drop-shoulder waffle-knit sweaters.",
    chips: ["Crew neck", "Turtleneck", "Cable knit"],
    cards: [
      { brand: "Outfitters", title: "Basic Knitted Sweater", price: 3490, compare: 6990, img: "products/s3-0.jpg" },
      { brand: "Charcoal", title: "Textured Crew Neck Sweater", price: 4348, compare: 8695, img: "products/s3-1.jpg" },
      { brand: "Breakout", title: "Relaxed Fit Mock Neck Sweater", price: 2999, compare: 5999, img: "products/s3-2.jpg" },
      { brand: "Furor", title: "Crew Neck Knitted Sweater", price: 3995, compare: 7990, img: "products/s3-3.jpg" },
      { brand: "Cambridge", title: "Designer Sweater", price: 7206, compare: 10295, img: "products/s3-4.jpg" },
      { brand: "Edenrobe", title: "Drop Needle Zipper Sweater", price: 7000, compare: 8990, img: "products/s3-5.jpg" },
    ],
  },
  {
    query: "Light-wash wide-leg jeans",
    answer: "Here are light-wash, wide-leg jeans in blue.",
    chips: ["High-waist", "Ripped", "Straight fit"],
    cards: [
      { brand: "Breakout", title: "Wide Leg Fit Denim", price: 2499, compare: 4999, img: "products/s1-0.jpg" },
      { brand: "Engine", title: "Men Wide Leg Denim", price: 3000, compare: 5999, img: "products/s1-1.jpg" },
      { brand: "Cougar", title: "Wide Leg Jeans", price: 3249, compare: null, img: "products/s1-2.jpg" },
      { brand: "Cambridge", title: "Denim Jeans", price: 5895, compare: null, img: "products/s1-3.jpg" },
      { brand: "Furor", title: "Relaxed Fit Cut & Sew Jeans", price: 1700, compare: 7489, img: "products/s1-4.jpg" },
      { brand: "Royal Tag", title: "Blue Jeans", price: 2625, compare: 5250, img: "products/s1-5.jpg" },
    ],
  },
  {
    query: "Oversized black tshirts",
    answer: "Here are oversized black T-shirts.",
    chips: ["Graphic print", "Plain", "Drop shoulder"],
    cards: [
      { brand: "Charcoal", title: "Oversized Graphic T-Shirt", price: 1948, compare: 3895, img: "products/s2-0.jpg" },
      { brand: "Cougar", title: "Basic Oversized T-Shirt", price: 1649, compare: null, img: "products/s2-1.jpg" },
      { brand: "Zellbury", title: "Oversized Graphic T-Shirt", price: 1390, compare: null, img: "products/s2-2.jpg" },
      { brand: "Outfitters", title: "Cropped Graphic T-Shirt", price: 1790, compare: 3690, img: "products/s2-3.jpg" },
      { brand: "Cambridge", title: "Acid Wash Black T-Shirt", price: 2376, compare: 3395, img: "products/s2-4.jpg" },
      { brand: "ONE (Be-One)", title: "Boxy Graphic Tee", price: 1300, compare: 2599, img: "products/s2-5.jpg" },
    ],
  },
];

export const TAB_BRANDS = ["Outfitters", "Breakout", "Cougar", "Engine", "Cambridge", "Charcoal", "Zellbury"];
export const BRAND_ROWS = [
  ["Outfitters", "Breakout", "Cougar", "Engine", "Cambridge", "Charcoal", "Zellbury", "Uniworth"],
  ["Edenrobe", "Furor", "Diners", "Royal Tag", "Equator", "Meme", "Monark", "ONE"],
  ["Bandana", "Lama", "Outfitters", "Charcoal", "Engine", "Cougar", "Breakout", "Edenrobe"],
];
