"""
Live status of an enrichment Batch API run, straight from OpenAI. Read-only:
doesn't collect results or write anything (enrich_products.py does that).

    python batch_status.py                          # enrich_runs/test_stores
    python batch_status.py enrich_runs/other_run
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / "server" / ".env")

run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "enrich_runs" / "test_stores")
state = json.loads((run_dir / "state.json").read_text())
client = OpenAI()

done = failed = total = 0
print(f"{run_dir.name}: {state['selected']:,} products, {len(state['chunks'])} batches\n")
for ch in state["chunks"]:
    if not ch["batch_id"]:
        print(f"  {ch['file']}: not submitted")
        total += ch["n"]
        continue
    b = client.batches.retrieve(ch["batch_id"])
    rc = b.request_counts
    done += rc.completed
    failed += rc.failed
    total += rc.total or ch["n"]
    started = datetime.fromtimestamp(b.created_at).strftime("%H:%M")
    collected = "  (results saved to DB)" if ch["collected"] else ""
    print(f"  {ch['file']}: {b.status:<12} {rc.completed:>5}/{rc.total or ch['n']:<5} failed {rc.failed:<4} submitted {started}{collected}")

pct = done / total * 100 if total else 0
print(f"\nTotal: {done:,} / {total:,} done ({pct:.0f}%), {failed:,} failed")
if all(c["collected"] for c in state["chunks"]):
    print("Everything collected.")
elif done + failed >= total:
    print("OpenAI is finished. Run enrich_products.py with the same --batch-dir to save the results.")
