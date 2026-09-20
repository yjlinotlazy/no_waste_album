# No Waste Album

No Waste Album is a local, single-user web app for browsing a large photo library, editing non-destructive versions, organizing metadata, and running resumable image jobs.

## Current implementation

Implemented:

- Python local backend with a browser frontend, served on port `7008` by default.
- Configuration from `~/.config/no_waste_album/config.yaml`.
- SQLite catalog with incremental/full scans, stable asset IDs, hidden/trash state, tags, and current-version state.
- Recursive folder explorer with `raw/` trees excluded, pagination, lazy thumbnails, and configurable page size.
- Non-destructive crop, adjustments, white balance, filters, rotation, variant save/overwrite/rename/delete, and current-version persistence.
- Technical quality detection, thumbnail generation, image stacking, and Auto Develop jobs with progress/history pages.
- Trash/restore/clear-trash workflows and bulk hide/delete actions.
- Kindle Gen 7 export through the configured output directory.
- Operator (`牛马模式`) and visitor (`游客模式`) API enforcement.

Not implemented yet:

- Visitor-mode album-display telemetry and view-stat ranking.
- Semantic image search, embeddings, general clustering, and recommendation engines.
- The personalized album-quality ML model and its training/evaluation feedback loop.
- Filesystem watchers and automatic background rescans.

## Run

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Create `~/.config/no_waste_album/config.yaml` from `config.example.yaml`, then run:

```bash
python3 server.py
```

Open <http://127.0.0.1:7008>.

The server has development reload enabled by default. Persisted catalog and job data live under the configured `data_dir`; the example configuration places this inside the photo library so it can be backed up with the library.

## Configuration

Important settings include:

- `library`: photo-library root;
- `data_dir`: catalog, jobs, previews, thumbnails, and other application data;
- `ml_data_dir` and `ml_negative_samples_dir`: reserved ML data paths;
- `kindle_gen7_output`: Kindle Gen 7 export directory;
- `stack_max_gap_minutes` and `stack_phash_max_distance`: stacking parameters;
- `page_size`, `thumbnail_size`, and `thumbnail_quality`.

The application does not hard-code user photo, ML, or device-output paths.

## Tests

```bash
python3 -m pip install -r requirements-dev.txt
PYTHONPATH=. pytest -q
```

The test suite covers catalog behavior, jobs, stacking, thumbnails, recipes, rendering, quality detection, and server behavior. Browser interaction still needs browser-level tests.

## Documentation

- [`REQUIREMENTS.md`](REQUIREMENTS.md): product requirements and target scope;
- [`DESIGN.md`](DESIGN.md): target technical design and current implementation boundary;
- [`ARCHITECTURE.md`](ARCHITECTURE.md): architecture diagrams;
- [`MILESTONES.md`](MILESTONES.md): delivery status and next work;
- [`ML.md`](ML.md): planned personalized album-quality model;
- [`ISSUES.md`](ISSUES.md): known defects and deferred fixes.
