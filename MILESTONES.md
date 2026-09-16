# Implementation Milestones

The immediate priority is to validate the local web-app architecture and the non-destructive editing layer before building analysis, clustering, ranking, or advanced library management.

## Milestone 0 — Browse a local image library

### Goal

Build the basic local backend and dedicated web frontend needed to browse images from a configured folder, including nested subfolders.

### Scope

#### Backend

- Start a local web server and serve the frontend.
- Accept a configured library root folder.
- Recursively discover supported image files in subfolders.
- Return folder and image data through a documented API.
- Expose stable image identifiers or stable source references.
- Serve thumbnails and full-image previews safely.
- Return basic metadata: filename, relative path, dimensions, format, and timestamps where available.
- Detect and report unsupported, unreadable, or missing files without stopping the whole scan.

#### Frontend

- Show the folder hierarchy.
- Show images for the selected folder.
- Provide thumbnail and larger-preview views.
- Support basic navigation between images.
- Display the image path and basic metadata.
- Clearly display the active `牛马模式` or `游客模式`.
- Implement 游客模式 as browse-only, even if most management functionality is not yet available.

### Acceptance criteria

- The app can be started locally and opened in a browser.
- A configured folder with multiple levels of subfolders is browsable.
- Images remain in their original locations and are not modified.
- Selecting a folder loads its images without requiring a full page reload.
- A user can open a full-size preview and return to the folder view.
- Unreadable files are reported clearly and do not crash the server or UI.
- Frontend and backend communicate through an explicit API boundary.

### Out of scope

- Image editing.
- Image analysis, ML clustering, and search indexing.
- Duplicate and low-quality detection.
- Trash and permanent deletion.
- External-app handoff.
- Cloud sync, authentication, and multi-user support.

## Milestone 1 — Non-destructive photo editing

### Goal

Enable a user to edit a viewed photo in the browser while storing all edits as metadata and rendering the result responsively.

### Scope

#### Editing model

- Define a versioned edit-recipe schema.
- Support crop, color adjustments including white balance, and at least one filter.
- Store edit recipes separately from the original image file.
- Allow multiple variants for one source image.
- Provide variant creation, naming, saving, editing, and deletion.
- Support undo/redo during an editing session.

#### Preview rendering

- Render edits in the browser using a reduced-resolution working preview.
- Update the preview interactively as controls change.
- Keep the UI responsive while rendering.
- Cache previews where useful.
- Show a clear loading state when a preview is not immediately available.

#### Full-resolution output

- Provide an explicit export action that renders the selected recipe at full resolution.
- Export to a new file without changing the original.
- Preserve provenance linking the export to its source asset and variant.
- Ensure the backend can reproduce the saved recipe independently of the browser session.

### Acceptance criteria

- A user can crop an image, adjust color, apply a filter, and see the result in the browser.
- Slider and control changes update the preview without a full page reload.
- Saving a variant changes metadata only; the original file remains byte-for-byte unchanged.
- Multiple variants of the same photo can be saved and viewed independently.
- Reloading the page restores saved variants and their edits.
- Export produces a new rendered image and leaves the source untouched.
- The saved recipe contains sufficient information to reproduce the variant.
- 游客模式 can view saved variants but cannot edit, save, export, or delete them.
- 牛马模式 can perform the supported editing actions.

### Suggested technical validation

Before expanding the editor, prove these risks with a small vertical slice:

1. Load one large JPEG from the backend.
2. Generate a browser preview.
3. Apply crop, color adjustment, and one filter from a JSON recipe.
4. Save and reload the recipe.
5. Export a full-resolution result through the backend.
6. Compare the browser preview and backend export for acceptable visual consistency.

### Out of scope

- RAW development.
- Layered editing, masks, brushes, or selections.
- AI retouching or generative editing.
- Batch editing.
- Complex color-management guarantees.
- Image analysis and ML pipelines, except where needed to support the editor.

## After Milestone 1

Once browsing and editing are proven, the next milestones can add the on-demand image-analysis, clustering, indexing, cleanup, recommendation, and Home Companion integration pipelines described in `REQUIREMENTS.md` and `DESIGN.md`.
