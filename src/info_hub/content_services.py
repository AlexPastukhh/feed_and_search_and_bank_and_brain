"""Content version indexing, lazy backfill and on-demand page extraction."""
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from info_hub.content import split_text
from info_hub.db import open_session
from info_hub.models import ContentChunk, Resource, ResourceVersion
from info_hub.web_content import fetch_public_article


def index_version(session: Session, version: ResourceVersion) -> None:
    # Always flush: even metadata-only versions need an ID for current_version_id.
    session.flush()
    if not version.content_text:
        return
    for chunk in split_text(version.content_text):
        session.add(ContentChunk(
            resource_version_id=version.id,
            ordinal=chunk.ordinal,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            text=chunk.text,
        ))


def backfill_missing_chunks(*, batch_size: int = 20) -> int:
    """Index versions created before chunks existed; safe to rerun."""
    with open_session() as session:
        no_chunk = ~exists(select(ContentChunk.id).where(
            ContentChunk.resource_version_id == ResourceVersion.id,
        ))
        versions = session.scalars(
            select(ResourceVersion)
            .where(
                ResourceVersion.content_text.is_not(None),
                func.length(ResourceVersion.content_text) > 0,
                no_chunk,
            )
            .order_by(ResourceVersion.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        ).all()
        for version in versions:
            index_version(session, version)
        session.commit()
        return len(versions)


def extract_resource(resource_id: int) -> tuple[bool, ResourceVersion]:
    """Fetch a public article, preserve RSS originals and index a new web version."""
    with open_session() as session:
        resource = session.get(Resource, resource_id)
        if resource is None:
            raise LookupError("Resource not found")
        if not resource.canonical_url:
            raise ValueError("Resource has no article URL")
        url = resource.canonical_url

    page = fetch_public_article(url)
    with open_session() as session:
        resource = session.scalar(
            select(Resource).where(Resource.id == resource_id).with_for_update()
        )
        if resource is None:
            raise LookupError("Resource not found")
        latest_web = session.scalar(
            select(ResourceVersion)
            .where(
                ResourceVersion.resource_id == resource_id,
                ResourceVersion.content_origin == "web",
            )
            .order_by(ResourceVersion.version_number.desc())
            .limit(1)
        )
        if latest_web is not None and latest_web.content_hash == page.content_hash:
            return False, latest_web
        last_version = session.scalar(
            select(ResourceVersion.version_number)
            .where(ResourceVersion.resource_id == resource_id)
            .order_by(ResourceVersion.version_number.desc())
            .limit(1)
        )
        version = ResourceVersion(
            resource_id=resource_id,
            version_number=(last_version or 0) + 1,
            content_text=page.text,
            content_status="full",
            content_origin="web",
            content_hash=page.content_hash,
            raw_payload={"origin": "web", "url": page.source_url,
                         "extractor": "trafilatura", "note": "accessible HTML only"},
        )
        session.add(version)
        index_version(session, version)
        resource.current_version_id = version.id
        session.commit()
        return True, version
