# No Waste Album

This local app serves a local image library with nested folders and browser-based photo management and editing.

Install runtime dependencies once with:

```bash
python3 -m pip install -r requirements.txt
```

Configure the app in `~/.config/no_waste_album/config.yaml`, then run:

```bash
python3 server.py
```

Open <http://127.0.0.1:7008>. Use `牛马模式` to edit/save/export and switch to `游客模式` to verify browse-only behavior.

The production catalog/job modules can be exercised with:

```bash
python3 -m backend.worker --once
```

The worker currently executes `catalog_scan` and basic `analysis` jobs. Clustering and semantic indexing workers are intentionally not implemented yet.

For test coverage, install the development dependency and run:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m coverage run -m unittest discover -s backend/tests
python3 -m coverage report
```

Saved recipes and exports are written to the configured `data_dir`. The original images are never modified.
