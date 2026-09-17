# No Waste Album — Architecture Diagrams

These diagrams are the visual companion to [`DESIGN.md`](DESIGN.md).

## 1. System overview

```mermaid
flowchart LR
    Browser[Local browser]
    API[Local backend API\nmode authorization]

    Browser --> API

    subgraph Backend[Modular local backend]
        Catalog[Library catalog\nfolders, paths, fingerprints]
        Domain[Metadata/domain service\nexplicit commands]
        Render[Renderer\npreview and export]
        Query[Search/query service]
        Telemetry[Visitor telemetry]
        Files[File-management service\ntrash and delete]
        Jobs[Job manager]
        Adapters[External-app adapters]
    end

    API --> Catalog
    API --> Domain
    API --> Render
    API --> Query
    API --> Telemetry
    API --> Files
    API --> Jobs
    API --> Adapters

    subgraph Storage[Local storage]
        DB[(Metadata DB)]
        Sources[Original image files\nread-only]
        Derived[Derived data\nfeatures, vectors, clusters]
        Semantic[Semantic search index]
        Cache[Preview cache]
    end

    Catalog --> DB
    Domain --> DB
    Domain --> Sources
    Render --> Sources
    Render --> Cache
    Query --> DB
    Query --> Semantic
    Telemetry --> DB
    Files --> Sources
    Files --> DB
    Jobs --> Derived
    Jobs --> Semantic
```

## 2. Two indexing layers

```mermaid
flowchart TB
    Files[Photo folders and files]
    Scan[Catalog scan or filesystem watcher]
    Catalog[(Library catalog)]
    Browser[File browser]

    Files --> Scan --> Catalog --> Browser

    Catalog --> Analysis[On-demand image analysis]
    Analysis --> Features[(Versioned features\nquality, colors, objects, vectors)]
    Features --> Cluster[On-demand clustering]
    Features --> Index[On-demand semantic indexing]
    Cluster --> Clusters[(Versioned cluster results)]
    Index --> Semantic[(Semantic search index)]
    Semantic --> Search[Search and recommendations]
    Clusters --> Search
```

The catalog is the fast, basic inventory needed for browsing. The semantic index is derived data and may be absent or stale without breaking the file browser.

## 3. Non-destructive editing flow

```mermaid
sequenceDiagram
    actor User
    participant UI as Editor UI
    participant Preview as Browser preview renderer
    participant API as Backend API
    participant Domain as Metadata/domain service
    participant DB as Metadata DB
    participant Render as Backend renderer
    participant FS as Original files

    User->>UI: Adjust crop, color, white balance, filter
    UI->>Preview: Apply canonical edit recipe
    Preview-->>UI: Responsive preview
    User->>UI: Save variant
    UI->>API: create_variant(recipe)
    API->>Domain: Validate command
    Domain->>DB: Store variant + recipe + UUID
    DB-->>Domain: Saved variant
    Domain-->>UI: Variant ID
    User->>UI: Export
    UI->>API: export(variant_id)
    API->>Render: Render canonical recipe
    Render->>FS: Read immutable source
    FS-->>Render: Source pixels
    Render-->>API: Full-resolution output
    API-->>UI: New export path
```

The browser renderer is optimized for interaction. The backend renderer is authoritative for full-resolution output. Both consume the same versioned recipe format.

## 4. Background pipeline flow

```mermaid
flowchart LR
    Operator[牛马模式 operator]
    JobAPI[Job API]
    Queue[Local job manager]
    Analysis[Analysis worker]
    Cluster[Clustering worker]
    Index[Indexing worker]
    DB[(Metadata DB)]
    Features[(Feature store)]
    Clusters[(Cluster results)]
    Search[(Semantic index)]

    Operator -->|start| JobAPI --> Queue
    Queue -->|analysis| Analysis
    Analysis -->|status and results| DB
    Analysis --> Features
    Features -->|dependency| Cluster
    Cluster -->|versioned results| Clusters
    Features -->|dependency| Index
    DB --> Index
    Clusters --> Index
    Index -->|atomic publish| Search
    Queue -->|progress, retry, cancel| JobAPI
    JobAPI --> Operator
```

Workers do not directly mutate user-owned metadata. They write versioned derived results through defined job outputs.

## 5. Visitor telemetry and ranking

```mermaid
flowchart LR
    Visitor[游客模式 visitor]
    UI[Frontend interaction tracker]
    Events[(Raw visitor events)]
    Aggregate[Statistics aggregator]
    Stats[(ViewStats\nexposure, qualified views, sessions)]
    Rank[Ranking and recommendation engine]
    Results[Hidden gems and recommendations]

    Visitor --> UI
    UI -->|impression, open, qualified view, search click| Events
    Events --> Aggregate --> Stats --> Rank --> Results
    Results --> Visitor
```

Raw events are retained so statistics and rankings can be recalculated when weighting or recommendation logic changes.

## 6. Access modes

```mermaid
flowchart TB
    Request[Frontend request]
    Mode{Active mode}
    Visitor[游客模式]
    Operator[牛马模式]
    Read[Read APIs\nbrowse, preview, search]
    Mutate[Mutation APIs\nvariants, collections, jobs]
    Destructive[Destructive APIs\ntrash, clear trash]
    Reject[Permission error]

    Request --> Mode
    Mode -->|游客模式| Visitor
    Mode -->|牛马模式| Operator
    Visitor --> Read
    Visitor --> Mutate
    Visitor --> Destructive
    Mutate --> Reject
    Destructive --> Reject
    Operator --> Read
    Operator --> Mutate
    Operator --> Destructive
```

The backend enforces these permissions. Frontend control hiding is only a usability feature.

## 7. Ownership boundaries

| Component | Owns | Does not own |
|---|---|---|
| Library catalog | Folder inventory, paths, fingerprints, source status | Semantic labels or recommendations |
| Metadata/domain service | Validated user mutations and edit recipes | ML-derived results |
| Renderer | Preview/export pixels | Variant persistence decisions |
| Telemetry service | Raw visitor events and aggregates | Ranking policy |
| Analysis workers | Versioned image features | User metadata mutations |
| Clustering worker | Versioned cluster runs | Automatic organization changes |
| Indexing worker | Search-index versions | Source-file deletion |
| File-management service | Trash, restore, permanent delete | Quality judgments |
| Recommendation engine | Ranking and recommendation results | Unconfirmed user organization |
