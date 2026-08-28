import React, { useMemo, useState } from 'react';
import {
  ArrowLeft, ArrowRight, BadgeCheck, ChevronDown, ChevronRight, CircleUserRound,
  Filter, Heart, Menu, PackageCheck, Search, ShoppingBag, SlidersHorizontal, Sparkles,
  Store, Truck, X, ShieldCheck, RefreshCcw, Star, Grid2X2, List, Shirt, Footprints,
  Watch, Droplets, Lamp, Glasses, ShoppingBasket, Check, Plus, Minus
} from 'lucide-react';
import { brandNames, categories, products } from './data.js';

const money = (n) => `PKR ${n.toLocaleString('en-PK')}`;

function Logo({ onClick }) {
  return (
    <button className="logo" onClick={onClick} aria-label="Go home">
      <span className="logo-mark"><i /><i /><i /><i /></span>
      <span>SHOPALL<small>PAKISTAN</small></span>
    </button>
  );
}

function Header({ view, setView, wishlistCount, cartCount }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <>
      <header className="site-header">
        <div className="header-main shell">
          <button className="icon-btn mobile-only" onClick={() => setMobileOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
          <Logo onClick={() => setView('home')} />
          <nav className="desktop-nav" aria-label="Main navigation">
            <button onClick={() => setView('catalog')}>WOMEN</button>
            <button onClick={() => setView('catalog')}>MEN</button>
            <button onClick={() => setView('catalog')}>NEW IN</button>
            <button onClick={() => setView('home')}>BRANDS</button>
            <button onClick={() => setView('home')}>PAKISTANI STORES</button>
            <button className="sale" onClick={() => setView('catalog')}>SALE</button>
          </nav>
          <div className="header-actions">
            <button className="search-pill" onClick={() => setView('catalog')}><Search size={17}/><span>Search products, brands & more</span></button>
            <button className="icon-btn desktop-action" aria-label="Saved"><Heart size={19}/>{wishlistCount > 0 && <b>{wishlistCount}</b>}</button>
            <button className="icon-btn desktop-action" aria-label="Cart"><ShoppingBag size={19}/>{cartCount > 0 && <b>{cartCount}</b>}</button>
            <button className="icon-btn account" aria-label="Account"><CircleUserRound size={19}/></button>
          </div>
        </div>
      </header>

      {mobileOpen && (
        <div className="drawer-backdrop" onClick={() => setMobileOpen(false)}>
          <aside className="mobile-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="drawer-top"><Logo onClick={() => { setView('home'); setMobileOpen(false); }}/><button className="icon-btn" onClick={() => setMobileOpen(false)}><X size={20}/></button></div>
            <button onClick={() => {setView('catalog');setMobileOpen(false)}}>Women <ChevronRight size={17}/></button>
            <button onClick={() => {setView('catalog');setMobileOpen(false)}}>Men <ChevronRight size={17}/></button>
            <button onClick={() => {setView('catalog');setMobileOpen(false)}}>New In <ChevronRight size={17}/></button>
            <button onClick={() => {setView('home');setMobileOpen(false)}}>Brands <ChevronRight size={17}/></button>
            <button onClick={() => {setView('catalog');setMobileOpen(false)}}>Sale <ChevronRight size={17}/></button>
          </aside>
        </div>
      )}
    </>
  );
}

function BrandStrip() {
  return (
    <section className="band brand-band shell section-tight">
      <div className="section-heading compact"><div><span>DISCOVER BY STORE</span><h2>Popular brands</h2></div><button>VIEW ALL <ChevronRight size={15}/></button></div>
      <div className="brand-row">
        {brandNames.map((brand) => <button key={brand}>{brand}</button>)}
      </div>
    </section>
  );
}

const iconMap = { shirt: Shirt, sparkles: Sparkles, footprints: Footprints, 'shopping-bag': ShoppingBag, watch: Watch, droplets: Droplets, lamp: Lamp, glasses: Glasses };
function CategoryStrip({ onBrowse }) {
  return (
    <section className="shell section-tight category-section">
      <div className="section-heading compact"><div><span>BROWSE QUICKLY</span><h2>Shop by category</h2></div><button onClick={onBrowse}>VIEW ALL <ChevronRight size={15}/></button></div>
      <div className="category-row">
        {categories.map(({name, icon}) => { const Icon = iconMap[icon] || Sparkles; return <button key={name} onClick={onBrowse}><Icon size={21} strokeWidth={1.4}/><span>{name}</span><ChevronRight size={15}/></button>; })}
      </div>
    </section>
  );
}

function ProductCard({ product, onOpen, wishlisted, onWishlist }) {
  return (
    <article className="product-card">
      <div className="product-image" onClick={() => onOpen(product)} role="button" tabIndex={0}>
        <img src={product.image} alt={product.name}/>
        <button className={`heart ${wishlisted ? 'active' : ''}`} onClick={(e) => { e.stopPropagation(); onWishlist(product.id); }} aria-label="Save product"><Heart size={18} fill={wishlisted ? 'currentColor' : 'none'}/></button>
        {product.oldPrice && <span className="deal-tag">PRICE DROP</span>}
      </div>
      <div className="product-copy" onClick={() => onOpen(product)}>
        <span className="product-brand">{product.brand}</span>
        <h3>{product.name}</h3>
        <div className="price-line"><strong>{money(product.price)}</strong>{product.oldPrice && <del>{money(product.oldPrice)}</del>}</div>
      </div>
    </article>
  );
}

function Benefits() {
  return <div className="benefit-row">
    <div><BadgeCheck/><span><b>Verified stores</b><small>Authentic brand sources</small></span></div>
    <div><Truck/><span><b>Nationwide delivery</b><small>Across Pakistan</small></span></div>
    <div><RefreshCcw/><span><b>Easy comparison</b><small>Prices in one place</small></span></div>
  </div>;
}

function HomePage({ setView, openProduct, wishlist, toggleWishlist }) {
  const featured = products.slice(0, 6);
  return (
    <main>
      <section className="hero shell">
        <div className="hero-copy">
          <span className="eyebrow">ONE DESTINATION. COUNTLESS BRANDS.</span>
          <h1>Pakistan's best fashion.<br/>All in one place.</h1>
          <p>Browse products from leading Pakistani stores without jumping between fifteen different websites.</p>
          <div className="hero-actions"><button className="btn primary" onClick={() => setView('catalog')}>SHOP MEN <ArrowRight size={16}/></button><button className="btn secondary" onClick={() => setView('catalog')}>SHOP WOMEN <ArrowRight size={16}/></button></div>
          <Benefits />
        </div>
        <div className="hero-image">
          <img src="/assets/hero-models.webp" alt="Fashion models wearing minimalist clothing"/>
          <div className="hero-note"><span><Sparkles size={14}/> New season</span><strong>Summer edit</strong><button onClick={() => setView('catalog')}>Explore now <ArrowRight size={14}/></button></div>
        </div>
      </section>

      <BrandStrip />
      <CategoryStrip onBrowse={() => setView('catalog')} />

      <section className="shell section-block">
        <div className="section-heading"><div><span>CURATED PICKS</span><h2>Featured for you</h2></div><button onClick={() => setView('catalog')}>VIEW ALL <ChevronRight size={15}/></button></div>
        <div className="product-grid featured-grid">{featured.map(p => <ProductCard key={p.id} product={p} onOpen={openProduct} wishlisted={wishlist.has(p.id)} onWishlist={toggleWishlist}/>)}</div>
      </section>

      <section className="editorial shell section-block">
        <div className="editorial-copy"><span>SMARTER SHOPPING</span><h2>Compare the same style across stores.</h2><p>See brand, price and availability in one clean view, then go straight to the store you trust.</p><button className="btn secondary" onClick={() => setView('catalog')}>BROWSE ALL PRODUCTS <ArrowRight size={16}/></button></div>
        <img src="/assets/hero-accessories.webp" alt="Minimal fashion accessories"/>
      </section>
    </main>
  );
}

function CatalogPage({ openProduct, wishlist, toggleWishlist }) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [sort, setSort] = useState('Featured');
  const [selectedBrand, setSelectedBrand] = useState('All');
  const filtered = useMemo(() => selectedBrand === 'All' ? products.slice(0,8) : products.filter(p => p.brand.toLowerCase().includes(selectedBrand.toLowerCase())), [selectedBrand]);
  const FilterContent = () => <>
    <div className="filter-title"><b>FILTERS</b><button onClick={() => setSelectedBrand('All')}>Clear all</button></div>
    <div className="filter-group"><div className="filter-label">SIZE <ChevronDown size={15}/></div><div className="size-grid">{['XS','S','M','L','XL','2X'].map(s => <button key={s}>{s}</button>)}</div></div>
    <div className="filter-group"><div className="filter-label">AVAILABILITY <ChevronDown size={15}/></div><label><input type="checkbox" defaultChecked/> In stock <span>450</span></label><label><input type="checkbox"/> On sale <span>128</span></label></div>
    <div className="filter-group"><div className="filter-label">BRAND <ChevronDown size={15}/></div>{['All','Sapphire','Outfitters','Khaadi','Alkaram'].map(b => <label key={b}><input type="radio" name="brand" checked={selectedBrand===b} onChange={()=>setSelectedBrand(b)}/> {b}</label>)}</div>
    <div className="filter-group"><div className="filter-label">COLOR <ChevronDown size={15}/></div><div className="swatches"><i className="black"/><i className="white"/><i className="sand"/><i className="blue"/><i className="olive"/></div></div>
    <div className="filter-group"><div className="filter-label">PRICE RANGE <ChevronDown size={15}/></div><div className="price-range"><span>PKR 1,000</span><span>PKR 10,000+</span></div><input type="range" min="1000" max="10000" defaultValue="6500"/></div>
    <div className="filter-group"><div className="filter-label">RATINGS <ChevronDown size={15}/></div>{[5,4,3].map(r => <label key={r}><input type="checkbox"/> <span className="stars">{'★'.repeat(r)}{'☆'.repeat(5-r)}</span> & up</label>)}</div>
  </>;
  return <main className="catalog shell">
    <div className="breadcrumbs">Home <ChevronRight size={13}/> Men <ChevronRight size={13}/> Tops</div>
    <div className="catalog-heading"><div><h1>Men's Tops</h1><p>Discover shirts, polos and everyday pieces across Pakistan's leading stores.</p></div><div className="sort-wrap"><span>Sort by</span><select value={sort} onChange={e=>setSort(e.target.value)}><option>Featured</option><option>Newest Arrivals</option><option>Price: Low to High</option></select></div></div>
    <div className="catalog-toolbar"><button className="mobile-filter" onClick={()=>setFilterOpen(true)}><SlidersHorizontal size={17}/> Filters</button><div className="catalog-search"><Search size={17}/><input placeholder="Search within Men's Tops"/></div><div className="result-count">{filtered.length * 28 + 11} products</div><div className="view-buttons"><button className="active"><Grid2X2 size={17}/></button><button><List size={17}/></button></div></div>
    <div className="catalog-layout"><aside className="filters"><FilterContent/></aside><div className="catalog-products"><div className="active-chips"><span>Men <X size={13}/></span><span>Tops <X size={13}/></span></div><div className="product-grid catalog-grid">{filtered.map(p => <ProductCard key={p.id} product={p} onOpen={openProduct} wishlisted={wishlist.has(p.id)} onWishlist={toggleWishlist}/>)}</div></div></div>
    {filterOpen && <div className="drawer-backdrop" onClick={()=>setFilterOpen(false)}><aside className="filter-drawer" onClick={e=>e.stopPropagation()}><div className="drawer-top"><h3>Filters</h3><button className="icon-btn" onClick={()=>setFilterOpen(false)}><X size={20}/></button></div><FilterContent/><button className="btn primary full" onClick={()=>setFilterOpen(false)}>SHOW PRODUCTS</button></aside></div>}
  </main>;
}

function ProductPage({ product, back, wishlist, toggleWishlist, cartCount, setCartCount }) {
  const [size, setSize] = useState('M');
  const [qty, setQty] = useState(1);
  const similar = products.filter(p => p.id !== product.id).slice(0,5);
  return <main className="product-page shell">
    <div className="breadcrumbs"><button onClick={back}><ArrowLeft size={14}/> Back</button><ChevronRight size={13}/> Men <ChevronRight size={13}/> Shirts <ChevronRight size={13}/> {product.name}</div>
    <div className="product-detail">
      <div className="gallery"><div className="thumbs"><button className="selected"><img src="/assets/detail-shirt.webp" alt="Front view"/></button><button><img src={product.image} alt="Alternate view"/></button><button><img src="/assets/product-8.webp" alt="Alternate view"/></button></div><div className="main-photo"><img src="/assets/detail-shirt.webp" alt={product.name}/><button className={`floating-heart ${wishlist.has(product.id) ? 'active' : ''}`} onClick={()=>toggleWishlist(product.id)}><Heart fill={wishlist.has(product.id) ? 'currentColor' : 'none'}/></button></div></div>
      <div className="detail-copy">
        <span className="detail-brand">{product.brand.toUpperCase()}</span><h1>{product.name}</h1>
        <div className="rating"><span className="stars">★★★★★</span><b>{product.rating}</b><span>({product.reviews})</span><i/> <span>250+ viewed this week</span></div>
        <div className="detail-price"><strong>{money(product.price)}</strong>{product.oldPrice && <del>{money(product.oldPrice)}</del>}<small>MRP incl. of all taxes</small></div>
        <p className="description">Relaxed, clean and easy to style. A versatile everyday piece surfaced from multiple Pakistani stores so you can compare before you buy.</p>
        <div className="option-head"><b>Size</b><button>Size guide</button></div><div className="size-picker">{['XS','S','M','L','XL','2XL'].map(s=><button key={s} className={size===s?'active':''} onClick={()=>setSize(s)}>{s}</button>)}</div>
        <div className="option-head"><b>Color: {product.color}</b></div><div className="swatches detail-swatches"><i className="black selected"/><i className="white"/><i className="sand"/></div>
        <Benefits />
        <div className="purchase-row"><div className="qty"><button onClick={()=>setQty(Math.max(1,qty-1))}><Minus size={15}/></button><span>{qty}</span><button onClick={()=>setQty(qty+1)}><Plus size={15}/></button></div><button className="btn primary add" onClick={()=>setCartCount(cartCount+qty)}><ShoppingBag size={17}/> ADD TO CART</button><button className={`btn icon-save ${wishlist.has(product.id)?'active':''}`} onClick={()=>toggleWishlist(product.id)}><Heart size={18} fill={wishlist.has(product.id)?'currentColor':'none'}/></button></div>
        <div className="store-offers"><div className="offer-head"><div><Store size={18}/><span><b>Available across multiple stores</b><small>Compare store options before leaving ShopAll.</small></span></div><button>View all stores</button></div><div className="offer-grid"><div><span>Sapphire</span><b>{money(product.price)}</b><small>In stock</small></div><div><span>Khaadi</span><b>{money(product.price+300)}</b><small>2 colors</small></div><div><span>Outfitters</span><b>{money(product.price+500)}</b><small>Limited stock</small></div></div></div>
        <details><summary>Product details <ChevronDown size={16}/></summary><p>Generated demo content for the frontend prototype. Connect this panel to your scraped normalized product data later.</p></details>
        <details><summary>Shipping & returns <ChevronDown size={16}/></summary><p>Policies vary by source store and can be surfaced here from your aggregator data.</p></details>
      </div>
    </div>
    <section className="section-block similar"><div className="section-heading"><div><span>KEEP EXPLORING</span><h2>You might also like</h2></div></div><div className="product-grid similar-grid">{similar.map(p=><ProductCard key={p.id} product={p} onOpen={()=>{}} wishlisted={wishlist.has(p.id)} onWishlist={toggleWishlist}/>)}</div></section>
  </main>;
}

function MobileBottomNav({ view, setView, cartCount }) {
  return <nav className="mobile-bottom"><button className={view==='home'?'active':''} onClick={()=>setView('home')}><Store size={18}/><span>Home</span></button><button className={view==='catalog'?'active':''} onClick={()=>setView('catalog')}><Search size={18}/><span>Browse</span></button><button><Heart size={18}/><span>Saved</span></button><button><ShoppingBag size={18}/>{cartCount>0&&<b>{cartCount}</b>}<span>Cart</span></button></nav>;
}

export default function App() {
  const [view, setView] = useState('home');
  const [selectedProduct, setSelectedProduct] = useState(products[0]);
  const [wishlist, setWishlist] = useState(new Set([3]));
  const [cartCount, setCartCount] = useState(0);
  const openProduct = (p) => { setSelectedProduct(p); setView('product'); window.scrollTo({top:0, behavior:'smooth'}); };
  const toggleWishlist = (id) => setWishlist(prev => { const next = new Set(prev); next.has(id) ? next.delete(id) : next.add(id); return next; });
  return <div className="app-shell">
    <Header view={view} setView={setView} wishlistCount={wishlist.size} cartCount={cartCount}/>
    {view==='home' && <HomePage setView={setView} openProduct={openProduct} wishlist={wishlist} toggleWishlist={toggleWishlist}/>} 
    {view==='catalog' && <CatalogPage openProduct={openProduct} wishlist={wishlist} toggleWishlist={toggleWishlist}/>} 
    {view==='product' && <ProductPage product={selectedProduct} back={()=>setView('catalog')} wishlist={wishlist} toggleWishlist={toggleWishlist} cartCount={cartCount} setCartCount={setCartCount}/>} 
    <footer><div className="shell"><Logo onClick={()=>setView('home')}/><p>A frontend concept for a Pakistan-focused multi-store fashion aggregator.</p><span>© 2026 ShopAll Concept</span></div></footer>
    <MobileBottomNav view={view} setView={setView} cartCount={cartCount}/>
  </div>;
}
