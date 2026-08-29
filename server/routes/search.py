"""POST /api/search — port of the same route in server/index.js.

Logs the search asynchronously (FastAPI BackgroundTasks, run AFTER the
response is already sent) rather than blocking the request on a DB write —
both Alexey Grigorev's lesson 14 and the observability article we
researched flag synchronous logging as a real production gap, and it's a
cheap fix to make now even without full OpenTelemetry.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException

from db_conversations import log_search
from models import SearchRequest
from rag import run_search

router = APIRouter()


@router.post("/api/search")
async def search(body: SearchRequest, background_tasks: BackgroundTasks):
    try:
        result = await run_search(body.query, gender_override=body.gender)
    except RuntimeError as err:
        if str(err) == "OPENAI_API_KEY not configured":
            raise HTTPException(status_code=503, detail={"error": "search_unavailable", "message": str(err)})
        raise HTTPException(status_code=500, detail={"error": "internal_error"})
    except ValueError as err:
        if str(err) == "empty query":
            raise HTTPException(status_code=400, detail={"error": "missing_query"})
        raise HTTPException(status_code=500, detail={"error": "internal_error"})

    metrics = result.pop("_metrics", None)
    if metrics:
        background_tasks.add_task(log_search, query=body.query, gender_override=body.gender, result=result, metrics=metrics)
    return result
