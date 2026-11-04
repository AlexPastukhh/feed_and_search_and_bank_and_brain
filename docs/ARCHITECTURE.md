# Architecture snapshot

## Product direction
Personal extensible information ingestion and research platform:
RSS, API, URL and files now; more source types and research tools later.

## First-version decisions
- Modular monolith with one codebase and separate API/worker processes.
- PostgreSQL for resources and metadata; future pgvector only if needed.
- **Connector**: implementation; **Source**: configured connection;
  **Subscription**: acquisition/monitoring rule.
- **Resource**: obtained item; **Entity**: domain object;
  **Observation**: timestamped measurement; **Artifact**: file;
  **ContentChunk**: citable content fragment.
- READ and RESEARCH are independent usage flags; BOTH is only a UI label.
- LLM optional, via provider adapter.
- Research runs are bounded and user-directed; no autonomous agents in V1.

## Milestones
| Slice | Goal |
|---|---|
| Phase 0 | Runtime foundation and CI |
| V1.0 | RSS/API/URL/files → storage → search |
| V1.1 | Archive Q&A with source/chunk citations |
| V1.2 | Evidence-backed research runs and CSV analysis |
| V2 | Domain connectors, history, hybrid search, monitoring |
| V3 | Bounded autonomous research tools |

## Package boundaries (planned)
`core`, `sources`, `ingestion`, `content`, `search`,
`ai`, `research`, `domain`, `api`.

Phase 0 creates only runtime components. Future packages should be added when
their first real feature is developed, not as empty scaffolding.

## Documentation ownership
This file is a brief architectural orientation, not a competing feature registry.
A complete Draft 0.2 architecture package exists separately; import it into
the repository and make one canonical feature backlog before Phase 1.

## Implemented first slice: RSS

`Source` holds a feed connection; `Subscription` holds polling settings and
READ/RESEARCH flags. `IngestionRun` is a durable queued job. The worker
fetches and parses RSS/Atom, upserts `Resource`, creates `ResourceVersion`
only for content changes, and records `SubscriptionResource` membership.
Each API resource shows provenance and whether feed content is partial.
A small connector interface separates RSS transport/parsing from the
source-independent ingestion and persistence services.

See [RSS-first-slice](RSS-FIRST-SLICE.md) for supported endpoints and limits.

## Content and search slice

ResourceVersion.content_origin distinguishes feed-derived and web-extracted
content. Resource.current_version_id points to the preferred readable text;
older versions are retained for provenance. ContentChunk links exact offsets to
its immutable ResourceVersion; PostgreSQL GIN FTS powers keyword retrieval.
The worker backfills older RSS texts. HTML extraction is on-demand only.
Details and PowerShell verification: [CONTENT-SEARCH.md](CONTENT-SEARCH.md).
