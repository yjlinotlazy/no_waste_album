# No Waste Album

## POC

This dependency-free POC serves a local image library with nested folders and demonstrates non-destructive photo editing in the browser.

Configure the app in `~/.config/no_waste_album/config.yaml`, then run:

```bash
python3 server.py
```

Open <http://127.0.0.1:7008>. Use `牛马模式` to edit/save/export and switch to `游客模式` to verify browse-only behavior.

Saved recipes and exports are written to the configured `data_dir`. The original images are never modified.
