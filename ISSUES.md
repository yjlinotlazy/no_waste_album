# Known Issues

## Mobile delete/hide loses scroll position

- **Status:** unresolved
- **Symptom:** After deleting or hiding an image from the mobile card action buttons, the library returns to the top instead of staying anchored on the next image.
- **Expected behavior:** Keep the user at the deleted/hidden image's position and show the next available image. If the page becomes empty, move to the previous page and show its last image.
- **Affected area:** Mobile library image cards, delete/hide quick actions, pagination.
- **Notes:** Several client-side approaches were attempted, including `scrollIntoView()` and restoring the target card relative to the viewport before reload. The behavior remains unreliable and needs browser-level debugging with the running app.
