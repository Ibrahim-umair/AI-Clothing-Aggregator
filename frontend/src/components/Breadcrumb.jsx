export default function Breadcrumb({ selection, onChange }) {
  const crumbs = [];
  if (selection.gender) crumbs.push({ label: selection.gender, key: "gender" });
  if (selection.branch) crumbs.push({ label: selection.branch, key: "branch" });
  if (selection.sub) crumbs.push({ label: selection.sub, key: "sub" });
  if (selection.category) crumbs.push({ label: selection.category, key: "category" });

  if (crumbs.length === 0) return null;

  const goTo = (index) => {
    // Reset everything after this crumb's key
    const keysInOrder = ["gender", "branch", "sub", "category"];
    const cutoff = keysInOrder.indexOf(crumbs[index].key);
    const next = { ...selection };
    keysInOrder.forEach((k, i) => {
      if (i > cutoff) next[k] = null;
    });
    onChange(next);
  };

  return (
    <div className="breadcrumb">
      <button onClick={() => onChange({ gender: null, branch: null, sub: null, category: null, store: selection.store })}>
        All
      </button>
      {crumbs.map((c, i) => (
        <span key={c.key} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span className="breadcrumb__sep">/</span>
          {i === crumbs.length - 1 ? (
            <span className="breadcrumb__current">{c.label}</span>
          ) : (
            <button onClick={() => goTo(i)}>{c.label}</button>
          )}
        </span>
      ))}
    </div>
  );
}
