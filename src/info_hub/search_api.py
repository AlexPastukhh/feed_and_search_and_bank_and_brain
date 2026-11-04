"""Multilingual simple-token PostgreSQL full text search over indexed chunks."""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from info_hub.content_services import extract_resource
from info_hub.db import get_session
from info_hub.models import ContentChunk, Resource, ResourceVersion

router = APIRouter(tags=["content"])


@router.get("/search")
def search(
    q: str = Query(min_length=1, max_length=200),
    source_id: int | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    query_text = q.strip()
    if not query_text:
        raise HTTPException(status_code=422, detail="Query cannot be blank")
    tsquery = func.websearch_to_tsquery("simple", query_text)
    rank = func.coalesce(func.ts_rank(ContentChunk.search_vector, tsquery), 0.0)
    # OUTER JOIN also finds title-only and metadata-only resources.
    # SQLAlchemy autoescapes LIKE wildcards in user-provided title searches.
    statement = (
        select(Resource, ResourceVersion, ContentChunk, rank.label("rank"))
        .select_from(Resource)
        .outerjoin(ResourceVersion, Resource.current_version_id == ResourceVersion.id)
        .outerjoin(ContentChunk, ContentChunk.resource_version_id == ResourceVersion.id)
        .where(or_(
            ContentChunk.search_vector.op("@@")(tsquery),
            Resource.title.icontains(query_text, autoescape=True),
        ))
    )
    if source_id is not None:
        statement = statement.where(Resource.source_id == source_id)
    statement = statement.order_by(
        rank.desc(), Resource.published_at.desc().nullslast(), ContentChunk.ordinal,
    ).limit(limit)
    results = session.execute(statement).all()
    return [
        {
            "resource_id": resource.id,
            "chunk_id": chunk.id if chunk else None,
            "version_id": version.id if version else None,
            "title": resource.title,
            "canonical_url": resource.canonical_url,
            "source_id": resource.source_id,
            "published_at": resource.published_at,
            "content_status": version.content_status if version else "unavailable",
            "rank": float(score),
            "snippet": chunk.text[:400] if chunk else "",
            "char_start": chunk.char_start if chunk else None,
            "char_end": chunk.char_end if chunk else None,
        }
        for resource, version, chunk, score in results
    ]


@router.post("/resources/{resource_id}/extract")
def extract_article(resource_id: int) -> dict:
    try:
        created, version = extract_resource(resource_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # Existing RSS text remains intact on failed extraction.
        raise HTTPException(status_code=422, detail=str(exc)[:180]) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Article source returned HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Article request failed") from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail="Article hostname unavailable") from exc
    return {
        "resource_id": resource_id,
        "version": version.version_number,
        "content_status": version.content_status,
        "content_origin": version.content_origin,
        "content_chars": len(version.content_text or ""),
        "created": created,
    }
