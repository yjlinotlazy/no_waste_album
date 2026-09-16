# Personal Album Management Studio — Requirements

## 1. Product goal

Build a personal, local-first studio for organizing a large image library, creating multiple visual versions of the same image, finding redundant or related images, and surfacing valuable images that are otherwise overlooked.

The original image remains the source of truth. Editing and organization metadata must not destroy the source unless the user explicitly clears the trash.

## 2. Core concepts

- **Asset:** An imported image file and its stable identity.
- **Variant:** A non-destructive rendering of an asset produced by a combination of edit operations.
- **Edit operations:** Initially cropping, color adjustment, and filters. Operations are stored as metadata, not baked into the original.
- **Collection/cluster:** A user-created or automatically generated grouping of assets or variants.
- **Trash:** A reversible staging area for deletion.
- **View statistics:** Usage signals such as opens, views, favorites, exports, and recency of interaction.

## 3. Application model and access modes

1. The application shall be a single-user web application served locally on the user's machine.
2. The application shall not require a hosted backend or multi-user account system for core functionality.
3. The frontend shall provide two explicit modes:
   - **牛马模式 (operator mode):** full editing, indexing, analysis, clustering, organization, export, trash, and library-management capabilities;
   - **游客模式 (visitor mode):** browse-only access to approved library content.
4. 牛马模式 shall be able to switch into 游客模式 from the frontend.
5. 游客模式 shall not expose controls or APIs that can mutate assets, variants, metadata, collections, jobs, indexes, or trash.
6. 游客模式 shall allow browsing, previewing, searching, and viewing permitted metadata and related-image recommendations.
7. The application shall make the active mode clearly visible at all times.
8. Since the application is local and single-user, mode switching may use a local session or explicit mode control rather than a full account/login system.
9. The backend shall enforce mode permissions in addition to hiding or disabling frontend controls.

## 4. System architecture

1. The project shall be implemented as two dedicated components:
   - **Frontend:** the local web UI for browsing, editing, management workflows, job controls, and mode switching;
   - **Backend:** the local service responsible for asset storage, metadata, rendering, analysis, ML pipelines, indexing, search, permissions, and external-app handoff.
2. Frontend/backend communication shall use an explicit, documented API boundary rather than direct access to backend internals or storage.
3. The API shall expose read and mutation operations separately so the backend can enforce 牛马模式 and 游客模式 permissions consistently.
4. Long-running analysis, clustering, and indexing operations shall be represented as backend jobs with status APIs that the frontend can monitor.
5. The architecture shall support incremental delivery over multiple iterations. Each iteration should leave the application runnable and preserve compatibility with existing assets and persisted metadata.
6. The system shall keep UI concerns, domain logic, persistence, image processing, ML, and integration adapters modular enough to evolve independently.

## 5. Functional requirements

### 5.1 Library ingestion and asset identity

1. The system shall import images from one or more user-selected folders.
2. The system shall preserve the original file and record its path, file metadata, dimensions, format, and timestamps where available.
3. The system shall assign each asset a stable internal identifier.
4. Re-indexing shall be idempotent: the same file must not create duplicate library records.
5. The system shall detect missing, moved, or changed source files and expose their status to the user.

### 5.2 Non-destructive variants

1. A single asset shall support multiple variants.
2. Each variant shall represent a combination of edit operations, including:
   - crop;
   - color adjustments, including white balance;
   - filters.
3. The edit history/order and parameters shall be persisted as structured metadata.
4. Users shall be able to create, name, duplicate, edit, compare, and delete variants without modifying the source asset.
5. The system shall render the selected variant at view/export time.
6. The system should cache rendered previews and invalidate them when the source or edit metadata changes.
7. The system shall support exporting a rendered variant as a new image file while retaining its relationship to the source asset.

### 5.3 Viewing and browsing

1. The system shall provide thumbnail and larger preview views.
2. Selecting an image shall show its variants, metadata, related images, and current organization state.
3. View-time rendering may tolerate moderate latency, but the interface shall show progress and remain responsive.
4. Every meaningful view/open interaction shall be eligible for view-stat recording.

### 5.4 Quality assessment and cleanup

1. The system shall assess likely low-quality images using signals such as blur, exposure, poor focus, corruption, and very small dimensions.
2. Quality assessment shall produce an explainable score or reason, not an unexplained deletion decision.
3. Users shall be able to filter and review likely low-quality images in a dedicated cleanup workflow.
4. The system shall support bulk selection for cleanup.
5. Deleting an image shall first move it to the application trash or equivalent reversible state.
6. Permanent deletion shall require an explicit **Clear Trash** action.
7. The system shall clearly distinguish source assets, variants, and generated exports before deletion.
8. The system must never permanently delete solely because an automated quality score is low.

### 5.5 Duplicate and similarity detection

1. The system shall find exact duplicates using file/content fingerprints.
2. The system shall find probable duplicates and near-duplicates using timestamp proximity and image analysis.
3. The system shall group or rank similar images without silently merging or deleting them.
4. Similarity results shall provide enough context for comparison: thumbnails, timestamps, similarity reason, and file locations.
5. The detection pipeline should be extensible so additional signals can be added later.

### 5.6 Indexing, search, and clustering

1. The system shall maintain an index of image features and searchable metadata.
2. Users shall be able to find images by:
   - similar visual elements;
   - detected objects or subjects;
   - dominant or representative colors;
   - visual structure/composition;
   - timestamp and file metadata.
3. The system shall support multiple clustering strategies rather than one fixed organization scheme.
4. Clusters shall be inspectable, editable, and dismissible by the user.
5. Automatic recommendations shall be presented as suggestions and must not alter user organization without confirmation.

### 5.7 View statistics and discovery

1. The system shall record configurable view/interaction statistics per asset and, where useful, per variant.
2. The system shall calculate a weighted ranking using view statistics and other configurable signals.
3. The system shall provide a discovery view for “hidden gems”: images with high quality, relevance, or uniqueness that are under-viewed.
4. Users shall be able to understand the main factors behind a recommendation or ranking.
5. Users shall be able to reset or exclude view statistics from ranking.
6. The system shall prioritize accurate, durable logging of visitor-mode interactions because these statistics drive ranking and recommendations.
7. Visitor-mode telemetry shall distinguish at minimum: image impression, opened image, meaningful view duration, variant view, navigation, search result click, favorite, and export where enabled.
8. Each recorded event shall include the asset or variant ID, event type, timestamp, visitor-mode session ID, and relevant context such as source view or search query.
9. The system shall prevent accidental inflation of statistics through rapid repeated renders, thumbnail prefetching, background tabs, or duplicate event delivery.
10. Logging failures shall be visible to the backend and recoverable without blocking visitor-mode browsing.

### 5.8 Interoperability

1. The system shall support sending selected assets, variants, clusters, or search results to external applications.
2. The first integration target is Home Companion, but the integration boundary shall not hard-code that application.
3. Handoff shall include stable asset identifiers and, when needed, rendered files plus relevant metadata.
4. Failed handoffs shall be visible and retryable.

## 6. Non-functional requirements

- **Safety:** No irreversible operation without explicit user action and confirmation.
- **Data integrity:** Source files must remain untouched by indexing, editing, analysis, and preview rendering.
- **Privacy:** Image analysis and indexing should run locally by default; any external processing must be opt-in and disclosed.
- **Responsiveness:** Browsing, search, and existing cached previews should remain usable while indexing or analysis runs in the background.
- **Recoverability:** Index rebuilds and interrupted analysis must be safe to resume.
- **Explainability:** Automated scores, clusters, and recommendations must expose their basis at a user-appropriate level.
- **Extensibility:** Feature extraction, clustering, edit operations, ranking, and app integrations should be replaceable modules.
- **Portability:** Library metadata should be exportable/backed up independently of application binaries.

## 7. Technical components and processing jobs

The system should use explicit, on-demand background jobs for computationally expensive image processing. Jobs must be observable, resumable, and safe to rerun.

### 7.1 Image analysis pipeline

An on-demand image-analysis job shall process selected assets or the entire library to extract reusable image features, including:

- quality signals such as blur, exposure, focus, corruption, and dimensions;
- detected objects or subjects;
- dominant and representative colors;
- visual embeddings for similarity search;
- structural/composition features;
- timestamps and other source metadata needed for duplicate analysis.

Requirements:

1. Analysis results shall be stored separately from source image files.
2. Each result shall record the analyzer/model version and processing timestamp.
3. Users shall be able to run analysis for new, changed, failed, or selected assets.
4. Re-running analysis shall update or version derived results without modifying the source asset or edit variants.
5. The job shall expose queued, running, completed, failed, and cancelled states.

### 7.2 ML clustering pipeline

An on-demand ML modeling job shall use extracted image features to generate one or more clustering results.

Requirements:

1. Users shall be able to choose the input scope, feature set, clustering strategy, and relevant parameters where practical.
2. Each clustering run shall be versioned and reproducible from its inputs, model version, and parameters.
3. A run shall produce inspectable clusters and confidence or similarity information where available.
4. Users shall be able to compare, accept, rename, edit, dismiss, or delete clustering results.
5. Clustering results shall remain recommendations until the user confirms any organization changes.
6. The pipeline shall support adding new models or clustering strategies without changing the asset model.

### 7.3 Search indexing pipeline

An on-demand indexing job shall build and maintain the search index from source metadata, analysis results, variants, and user organization data.

Requirements:

1. Users shall be able to index the full library or selected assets.
2. The index shall support metadata, timestamp, color, object, visual similarity, and structural search inputs.
3. The job shall support incremental indexing for new or changed assets.
4. Index records shall identify the source asset and the versions of the analysis data used to create them.
5. A failed or interrupted indexing run shall be resumable and shall not invalidate the last known-good index.
6. Users shall be able to rebuild or replace the index explicitly.

### 7.4 Job orchestration and status

1. Analysis, clustering, and indexing shall be independently triggerable; one job may declare dependencies on another when required.
2. Jobs shall support cancellation, retry, progress reporting, and error details.
3. The UI shall show which assets are pending, processing, complete, stale, or failed.
4. Jobs shall avoid unnecessary duplicate work by using asset fingerprints and processing configuration/model versions.
5. The system shall prioritize interactive browsing and preview rendering over background work.
6. Derived data shall be rebuildable from source assets and persisted configuration.

## 8. MVP scope

The MVP should include:

1. Folder import and idempotent indexing.
2. Asset/source identity and thumbnail browsing.
3. Non-destructive crop, color adjustment, and filter variants.
4. View-time rendering with preview caching.
5. Exact and timestamp-assisted near-duplicate detection.
6. Basic low-quality review workflow with trash and **Clear Trash**.
7. Search by metadata, color, and basic visual similarity.
8. Manual collections plus one automatic clustering strategy.
9. Basic view statistics and hidden-gem ranking.
10. A generic export/handoff mechanism, with Home Companion as the first adapter.
11. A locally served single-user web interface with 牛马模式 and 游客模式.
12. Backend-enforced browse-only restrictions for 游客模式.

## 9. Deferred scope

- Automatic permanent deletion.
- Advanced semantic understanding beyond the initial object/visual feature set.
- Cloud synchronization or multi-user collaboration.
- Full-featured RAW development and video management.
- Automatic organization changes without user confirmation.

## 10. Acceptance criteria

- Editing an image creates a variant and leaves the original byte-for-byte unchanged.
- Multiple variants of one source can coexist and be rendered independently.
- A user can identify likely duplicates and low-quality images, select items, move them to trash, restore them, and permanently clear trash deliberately.
- Search returns useful results for at least metadata, colors, and visual similarity.
- Background indexing does not block browsing and can resume after interruption.
- A user can export a selected rendered variant and hand it to an external app through an adapter.
- Ranking and recommendations show their contributing signals and can be reset or disabled.
- Visitor-mode interactions are logged durably and can be audited from the resulting view statistics.
- Repeated renders, prefetches, and accidental duplicate events do not materially inflate view counts.
- Image analysis, clustering, and indexing can each be started on demand, report progress, resume after interruption, and be rerun safely.
- Search and clustering results identify the analysis/model/index versions from which they were produced.
- The application runs locally as a single-user web app without requiring a hosted service.
- 牛马模式 can perform all supported editing and management actions.
- 游客模式 can browse and search permitted content but cannot mutate library state, start or cancel jobs, edit variants, export, or alter trash.
- Mode restrictions are enforced by the backend, not only by the frontend UI.
- Frontend and backend can be developed, tested, and evolved as separate components behind a documented API.

## 11. Open product decisions

- Supported image formats and whether RAW files are in scope for the first release.
- Whether metadata lives in a sidecar database, sidecar files, or both.
- Exact definition and weighting of “hidden gem.”
- Which Home Companion handoff protocol/API is available.
- Whether variants can be shared as portable edit recipes across installations.
- Retention policy for view statistics and derived image-analysis data.
