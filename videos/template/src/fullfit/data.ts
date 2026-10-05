// Live /api/search results (gender: Men), re-run and photo-checked on render
// day (2026-10-05). Each grid is the app's real top 6, unedited; titles are
// only re-cased and stripped of SKU codes.
export type Card = { brand: string; title: string; price: number; compare: number | null; img: string };
export type Piece = {
  slot: string;
  query: string;
  answer: string;
  cards: Card[];
  pick: number; // index into cards
  cutout: string;
  cutoutAspect: number; // width / height of the trimmed cut-out
};

export const BUDGET = 10000;

export const PIECES: Piece[] = [
  {
    slot: "Top",
    query: "Black oversized t-shirts under 2500",
    answer: "Here are black oversized T-shirts under Rs. 2,500.",
    pick: 1,
    cutout: "flatlay/tee-trim.png",
    cutoutAspect: 1369 / 1275,
    cards: [
      { brand: "Charcoal", title: "Oversized Graphic T-Shirt", price: 1948, compare: 3895, img: "grid/q0-0.jpg" },
      { brand: "Cougar", title: "Basic Oversized T-Shirt", price: 1649, compare: null, img: "grid/q0-1.jpg" },
      { brand: "Zellbury", title: "Oversized Graphic T-Shirt", price: 1390, compare: null, img: "grid/q0-2.jpg" },
      { brand: "Outfitters", title: "Basic Crew Neck T-Shirt", price: 1390, compare: 2890, img: "grid/q0-3.jpg" },
      { brand: "Royal Tag", title: "Black Round Neck T-Shirt", price: 1425, compare: 2850, img: "grid/q0-4.jpg" },
      { brand: "Meme", title: "Printed T-Shirt for Men", price: 1495, compare: 2990, img: "grid/q0-5.jpg" },
    ],
  },
  {
    slot: "Bottom",
    query: "Dark blue slim fit jeans under 3500",
    answer: "Here are dark blue slim-fit jeans under Rs. 3,500.",
    pick: 4,
    cutout: "flatlay/jeans-trim.png",
    cutoutAspect: 830 / 1424,
    cards: [
      { brand: "Cambridge", title: "Denim Jeans, Dark Blue", price: 3297, compare: 5495, img: "grid/q1-0.jpg" },
      { brand: "Charcoal", title: "Slim Fit Jean Dark Blue", price: 2748, compare: 5495, img: "grid/q1-1.jpg" },
      { brand: "Zellbury", title: "Essential Denim", price: 2790, compare: null, img: "grid/q1-2.jpg" },
      { brand: "Outfitters", title: "Slim Fit Jeans", price: 2190, compare: 5490, img: "grid/q1-3.jpg" },
      { brand: "Engine", title: "Men Slim Fit Denim", price: 1650, compare: 5499, img: "grid/q1-4.jpg" },
      { brand: "Meme", title: "Skinny Fit Jeans for Men", price: 2495, compare: 4990, img: "grid/q1-5.jpg" },
    ],
  },
  {
    slot: "Shoes",
    query: "Chunky sneakers under 7000",
    answer: "Here are chunky sneakers under Rs. 7,000.",
    pick: 2,
    cutout: "flatlay/sneakers-trim.png",
    cutoutAspect: 698 / 881,
    cards: [
      { brand: "Cougar", title: "Chunky Sole Sneakers", price: 5999, compare: null, img: "grid/q2-0.jpg" },
      { brand: "Outfitters", title: "Chunky Mesh Sneakers", price: 5990, compare: 11990, img: "grid/q2-1.jpg" },
      { brand: "Breakout", title: "Trainers", price: 5499, compare: 10999, img: "grid/q2-2.jpg" },
      { brand: "ONE (Be-One)", title: "Textured Sole Sneakers", price: 6000, compare: 11999, img: "grid/q2-3.jpg" },
      { brand: "Furor", title: "Core Skate Sneakers", price: 5495, compare: 10990, img: "grid/q2-4.jpg" },
      { brand: "Engine", title: "Men Sneakers", price: 6000, compare: 11999, img: "grid/q2-5.jpg" },
    ],
  },
  {
    slot: "Cap",
    query: "Black cap under 1500",
    answer: "Here are black caps under Rs. 1,500.",
    pick: 0,
    cutout: "flatlay/cap-trim.png",
    cutoutAspect: 730 / 802,
    cards: [
      { brand: "Zellbury", title: "Baseball Cap 6048", price: 990, compare: null, img: "grid/q3-0.jpg" },
      { brand: "Furor", title: "Baseball Cap", price: 1392, compare: 1989, img: "grid/q3-1.jpg" },
      { brand: "Zellbury", title: "Baseball Cap 6047", price: 990, compare: null, img: "grid/q3-2.jpg" },
      { brand: "Furor", title: "Baseball Cap", price: 1392, compare: 1989, img: "grid/q3-3.jpg" },
      { brand: "Zellbury", title: "Baseball Cap 6039", price: 490, compare: null, img: "grid/q3-4.jpg" },
      { brand: "Furor", title: "Canvas Baseball Cap", price: 1392, compare: 1989, img: "grid/q3-5.jpg" },
    ],
  },
];

export const rs = (v: number) => `Rs ${Math.round(v).toLocaleString("en-US")}`;
