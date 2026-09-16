# Personal Album Management Studio — Technical Design

## 1. Design goals

- Run as a local, single-user web application.
- Keep original image files immutable.
- Treat edits and machine-generated understanding as rebuildable metadata.
- Make expensive work explicit, asynchronous, observable, and resumable.
- Keep the frontend and backend independently evolvable.
- Make destructive actions deliberate and recoverable.

## 2. High-level architecture

```text
Browser
  │ HTTP/JSON API + job-status stream or polling
  ▼
Local backend service
  ├── API and mode authorization
  ├── Asset and variant service
  ├── Rendering service
  ├── Job manager
  │     ├── Image analysis pipeline
  │     ├── ML clustering pipeline
  │     └── Search indexing pipeline
  ├── Search service
  ├── External-app adapters
  └── Persistence layer
        ├── metadata database
        ├── derived feature/model data
        ├── search index
        └── preview cache
```

The browser is responsible for presentation and interaction. The backend owns all filesystem access, image processing, persistence, job execution, and authorization decisions.

The application should be started as one local backend process that serves the frontend assets and exposes the API. The internal modules should still be separated so the frontend and backend can later be developed or deployed independently without changing the domain model.

## 3. Frontend design

### 3.1 Main areas

- Library browser: thumbnails, filters, sorting, and pagination/virtualized scrolling.
- Asset detail: large preview, source metadata, variants, analysis results, and related assets.
- Variant editor: crop, color adjustment, and filter controls.
- Cleanup workspace: low-quality candidates, duplicate groups, selection, trash, restore, and clear trash.
- Search and discovery: metadata search, visual similarity, clusters, and hidden gems.
- Job center: start jobs, show progress, failures, stale data, and retry/cancel controls.
- Handoff/export panel: send selected assets or variants to supported applications.

### 3.2 Operating modes

The active mode is part of frontend application state and is also sent with every API request through the local session.

**牛马模式** is the full operator interface. It exposes all supported mutation and administration workflows.

**游客模式** is a browse-only interface. It may show thumbnails, previews, search, permitted metadata, clusters, and recommendations, but must not show mutation controls.

The backend remains the authority. A request made while in 游客模式 must be rejected if it would change assets, variants, metadata, collections, jobs, indexes, exports, or trash.

## 4. Backend module boundaries

### 4.1 API layer

Provides versioned HTTP endpoints for:

- assets, metadata, thumbnails, and previews;
- variants and edit recipes;
- search and similarity queries;
- clusters and recommendations;
- trash and cleanup operations;
- job creation, status, cancellation, and retry;
- export and external-app handoff.

The API should return stable IDs, explicit status values, timestamps, and model/index versions where derived data is involved.

### 4.2 Authorization layer

Authorization should classify API operations as `read`, `operator_mutation`, or `destructive`. 游客模式 may call only permitted read operations. 牛马模式 may call all operations, with destructive actions requiring an additional explicit confirmation at the API/UI workflow level.

### 4.3 Asset service

Owns asset discovery, fingerprinting, source-file status, metadata extraction, and relationships between source assets, variants, exports, and derived results.

### 4.4 Variant and rendering service

Stores ordered edit operations as an edit recipe. A renderer applies the recipe to the immutable source at preview or export time. Rendered previews are cached using a key derived from source fingerprint, variant recipe, renderer version, and requested size/format.

### 4.5 Search service

Translates user queries into metadata filters, feature comparisons, and index lookups. It should not depend directly on a particular indexing technology; the index adapter should be replaceable.

### 4.6 Integration adapter layer

External applications are accessed through adapters with a common handoff interface. The first adapter targets Home Companion. Adapters receive stable asset/variant IDs and can request rendered files and metadata from the backend.

### 4.7 Visitor telemetry service

Visitor-mode interaction logging is a first-class backend capability, not incidental frontend analytics. It provides the source data for view statistics, hidden-gem ranking, and recommendations.

The frontend should emit semantic events rather than incrementing counters directly. The backend validates, timestamps, persists, deduplicates, and aggregates those events.

## 5. Persistence model

The initial implementation should use a local metadata database plus filesystem/object storage for images and derived files.

Suggested entities:

- `Asset`: stable ID, source path, content fingerprint, dimensions, format, timestamps, and source status.
- `Variant`: stable ID, asset ID, name, edit recipe, and renderer version.
- `EditOperation`: variant ID, order, operation type, and parameters.
- `AnalysisRun`: run ID, scope, analyzer/model versions, status, and timestamps.
- `AssetFeatures`: asset ID, analysis run ID, quality signals, labels, colors, embeddings, and structure features.
- `ClusterRun`: run ID, input analysis run, model/configuration, status, and timestamps.
- `ClusterMembership`: cluster run ID, cluster ID, asset ID, and confidence/distance.
- `IndexRun`: run ID, source data versions, status, and timestamps.
- `Collection`: user-created grouping and membership.
- `TrashEntry`: asset/variant/export reference, original location, deletion state, and timestamps.
- `ViewEvent` or aggregated `ViewStats`: asset/variant ID, event type, count, and last-seen time.
- `VisitorSession`: session ID, start/end timestamps, mode, client metadata, and schema version.
- `ViewEvent`: event ID, session ID, asset/variant ID, event type, client timestamp, server timestamp, duration where applicable, source context, and deduplication key.
- `Job`: common job ID, type, state, progress, configuration, error, and retry information.

Derived records must reference the versions used to produce them. Source assets and user-created edit metadata should survive rebuilds of analysis, clustering, and search indexes.

## 6. Visitor-mode telemetry design

### 6.1 Event semantics

At minimum, the frontend should produce these events:

- `impression`: an item was rendered in a visible browsing context;
- `open`: the user opened a larger/detail view;
- `view_qualified`: the item remained meaningfully visible for a configured threshold;
- `variant_open`: a specific variant was viewed;
- `search_click`: the user opened an item from search results;
- `favorite` and `unfavorite`, if favorites are enabled;
- `export`, if exporting is enabled in the current mode.

An impression alone should not carry the same weight as a qualified view. Thumbnail prefetches, hidden elements, background tabs, and off-screen virtualized rows should not count as meaningful views.

### 6.2 Event delivery and durability

1. The frontend should batch low-value events and send them through a dedicated telemetry endpoint.
2. Important events should be acknowledged by the backend and retried with an idempotency/deduplication key when delivery fails.
3. The backend should persist raw events before updating aggregates, allowing statistics to be rebuilt.
4. A local client queue should buffer events during short network/service interruptions; browsing must continue if telemetry is unavailable.
5. Events should use server receive time for canonical ordering while retaining the client time for diagnostics.
6. The backend should expose ingestion failures, dropped-event counts, and queue health in operator diagnostics.

### 6.3 Deduplication and attribution

Deduplication should use a key derived from session, event type, asset/variant, view context, and a short time window. The exact window should be configurable.

The system should record both the source asset and the viewed variant when a variant is displayed. Aggregation should support:

- per-asset totals;
- per-variant totals;
- qualified-view totals;
- unique visitor sessions;
- first/last viewed timestamps;
- views by source, such as library, search, cluster, or recommendation.

### 6.4 Ranking inputs

The ranker should consume aggregated statistics rather than raw event counts alone. Candidate inputs include qualified views, recency, unique sessions, repeat-view frequency, search-origin views, and variant engagement. Ranking must account for exposure so that frequently shown images are not mistaken for genuinely engaging images.

Every ranking result should retain the statistics snapshot, weighting configuration, and ranker version used to produce it.

## 7. Processing jobs

### 7.1 Common job lifecycle

```text
queued → running → completed
             ├── failed → retrying → running
             └── cancelled
```

Each job should have a scope, configuration, dependency list, progress counters, logs/error details, and an idempotency key. Work should be split into asset-level units where possible so interrupted jobs can resume without repeating completed work.

### 7.2 Image analysis pipeline

Input: selected assets or a library scope.

Steps:

1. Resolve assets and verify source fingerprints.
2. Decode or safely inspect the image.
3. Compute quality signals.
4. Extract colors, detected objects/subjects, visual embeddings, and structural features.
5. Persist results with analyzer/model version and source fingerprint.
6. Mark dependent search and clustering data as stale when necessary.

Analysis should be on demand, with optional future support for automatic scheduling after import. Failures for one asset should not fail the entire run.

### 7.3 ML clustering pipeline

Input: a completed analysis run or selected feature set.

Steps:

1. Select the input assets and feature dimensions.
2. Normalize or transform features as required by the model.
3. Run the selected clustering strategy.
4. Persist a versioned cluster run and memberships.
5. Calculate confidence, distance, or representative-item information where available.
6. Present the result as a reviewable recommendation.

Cluster runs should be immutable results. User renaming, dismissal, or accepted organization changes should be stored separately from the raw model output.

### 7.4 Search indexing pipeline

Input: selected assets or a full/incremental scope.

Steps:

1. Identify new, changed, removed, and stale records.
2. Combine source metadata, analysis features, variants, collections, and view statistics.
3. Build or update index records.
4. Validate the new index or index segment.
5. Atomically publish the new index version.

The last known-good index must remain available until the replacement is successfully published.

## 8. Rendering and file safety

- Source files are read-only from the application’s perspective.
- Variant edits are serialized as structured recipes, not destructive file operations.
- Preview rendering may be lazy and cached.
- Export creates a new file and records its provenance.
- Moving an asset to trash changes application state first; permanent filesystem deletion happens only during explicit Clear Trash processing.
- Clear Trash should report failures individually and must not silently remove items it cannot verify.

## 9. Search, recommendations, and ranking

Search should combine exact filters and approximate feature matching. Similarity explanations should identify the relevant basis, such as shared objects, colors, structure, or embedding distance.

The hidden-gem ranker can initially combine:

- quality score;
- uniqueness or cluster distance;
- recency and timestamp context;
- low prior view count;
- user interaction signals.

Weights should be configurable and persisted with each recommendation/ranking run. Recommendations should include the ranking version and contributing signals.

## 10. API and job interaction example

```text
牛马模式 user
  └─ POST /jobs/analysis
       └─ backend returns job ID
            ├─ GET /jobs/{id}
            ├─ GET /jobs/{id}/events
            └─ POST /jobs/{id}/cancel

analysis completed
  ├─ POST /jobs/clustering
  └─ POST /jobs/indexing

游客模式 user
  └─ GET /search?q=...
       └─ mutation requests return a permission error
```

The exact endpoint naming and transport for job events may change, but the separation between read APIs, mutation APIs, and job APIs should remain stable.

## 11. Iterative implementation strategy

Each iteration should deliver a runnable vertical slice:

1. Local app shell, API boundary, mode switching, and read-only library browsing.
2. Asset ingestion, fingerprints, metadata persistence, and thumbnail/preview serving.
3. Variant recipes and non-destructive rendering/export.
4. Common job manager and the image-analysis pipeline.
5. Search index and metadata/color/visual similarity search.
6. Duplicate/quality cleanup workflow with trash safety.
7. ML clustering, reviewable recommendations, and hidden-gem ranking.
8. Home Companion handoff and broader integration/testing hardening.

The exact order can change, but migrations, API versioning, and persisted-data compatibility must be considered at every iteration.

## 12. Open technical decisions

- Frontend framework and state-management approach.
- Backend language/framework.
- Metadata database and search-index technology.
- Local job execution model: in-process worker, subprocesses, or a local queue.
- Image-analysis and ML runtime/model choices.
- Preview and derived-file storage layout.
- Job event transport: polling, server-sent events, or WebSocket.
- Home Companion integration protocol.
- Qualified-view threshold and weighting of impressions versus meaningful views.
- Telemetry retention period and whether raw visitor events can be compacted after aggregation.
- Exact deduplication window and treatment of repeated visits in one session.
