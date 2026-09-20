# Implementation Milestones

The original immediate objective was to establish a trustworthy local application foundation, a fast library catalog, and a usable non-destructive editing layer. Those foundations now exist and the project has moved into advanced-job hardening. The feature table below distinguishes implemented slices from future work.

## Current checkpoint status

- Milestone 0: substantially implemented — local server, config, SQLite catalog, mode enforcement, logging, jobs, and automated tests.
- Milestone 1: substantially implemented — recursive cataloging, `raw/` exclusion, folder explorer, pagination, lazy thumbnails, trash, hidden state, and explicit rescans.
- Milestone 2: substantially implemented — browser-side non-destructive editing, crop, adjustments, white balance, filters, rotation, variants, current-version persistence, and backend rendering/export.
- Remaining foundation gaps: browser-level regression tests, complete API documentation, and a clean separation between implemented jobs and future ML/search services.

## Completed foundation milestones

### Milestone 0 — Production foundation

Build the modular local monolith and its development boundaries:

- local backend and dedicated frontend;
- documented API boundary;
- configuration and local runtime setup;
- SQLite schema and migrations;
- `牛马模式` / `游客模式` enforcement;
- structured application logging;
- common job abstraction;
- basic automated test setup.

Exit condition: the app starts cleanly, serves the frontend, and has stable API and domain boundaries.

### Milestone 1 — Library catalog

Build a fast, reliable inventory of the local photo library:

- recursive folder discovery;
- content-based asset identity;
- cached catalog;
- incremental rescanning;
- foldable parent-child folder explorer;
- paginated browsing;
- thumbnails and previews;
- missing, moved, and changed-file detection.

Exit condition: browsing remains fast with a genuinely large photo library and does not send the entire library to the browser.

### Milestone 2 — Editing and rendering

Prove the core product interaction with a canonical, non-destructive editing model:

- versioned edit-recipe schema;
- crop;
- color adjustments;
- white balance and Auto WB;
- filters;
- browser-side responsive preview renderer;
- backend authoritative full-resolution renderer;
- multiple UUID-backed variants;
- preview caching;
- export with provenance;
- undo/redo.

Exit condition: browser preview and exported image are acceptably consistent, variants can be saved and loaded, and the original image remains untouched.

## Checkpoint after Milestone 2

Before starting advanced functionality, review:

- whether the local architecture is stable;
- whether catalog browsing is fast enough at realistic library size;
- whether the editing experience feels useful;
- whether browser and backend rendering are sufficiently consistent;
- whether the recipe and asset models are ready to support future pipelines;
- which technical choices need to change before production implementation continues.

The checkpoint is a deliberate decision point, not merely a progress review.

## Implemented advanced-job slices

- Technical quality detection using explainable heuristics for blur, resolution, exposure, and low information.
- Thumbnail generation with resumable work, cached thumbnails, clean-start mode, and catalog updates.
- 图片找朋友 stacking using cached thumbnail pHash, adjacent-image time limits, configurable Hamming distance, and stack-result review.
- Auto Develop pipeline that creates named `auto` versions and supports result review/deletion.
- Dedicated job pages, queued thumbnail/stack jobs, progress details, stale-running-job reconciliation, and full job history.

These are useful pipeline slices, not the complete semantic ML architecture described in `DESIGN.md`.

## Deferred advanced functionality

| Area | Planned capability | Depends on | Priority after checkpoint |
|---|---|---|---|
| Visitor telemetry | Sessions, semantic events, qualified views, deduplication, durable raw event log, derived view statistics | Foundation, catalog | Highest |
| Image analysis | Quality scoring, colors, objects, embeddings, structural features, versioned analysis runs | Catalog, job system | Highest |
| Search | Metadata, color, object, visual-similarity, and structural search; incremental semantic index | Image analysis | High |
| ML clustering | Feature generation, vector models, versioned clustering runs, reviewable cluster suggestions | Image analysis, job system | High |
| Recommendations | Hidden-gem ranking, view-stat weighting, explainable recommendation results | Telemetry, search, clustering | High |
| Duplicate detection | Exact fingerprints, timestamp-assisted near-duplicates, visual comparison | Catalog, image analysis | Medium |
| Quality cleanup | Low-quality review, bulk selection, explainable scores | Image analysis, file management | Medium |
| File management | Trash, restore, explicit Clear Trash, audited permanent deletion | Catalog, domain service | Medium |
| Collections | Manual collections, accepted cluster organization, collection search | Catalog, domain service | Medium |
| External integrations | Generic shuttle/adapter layer, Kindle Gen 7 integration | Stable asset/variant model | Medium |
| Advanced editing | RAW development, layered editing, masks, brushes, batch editing, stronger color management | Editing foundation | Later |
| Automation | Filesystem watchers, scheduled analysis, automatic stale-data refresh | Job system, catalog | Later |
| Portability | Metadata backup, portable edit recipes, derived-data rebuild tooling | Stable persistence model | Later |

## Delivery principles

- Every milestone should leave the application runnable.
- Prefer vertical slices over long infrastructure-only phases.
- Keep the backend as a modular monolith; use worker processes only for expensive jobs.
- Preserve original files and user-created metadata across all future iterations.
- Version all derived data, models, indexes, and renderers.
