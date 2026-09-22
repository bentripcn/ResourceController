# ResourceController iOS-inspired design handoff

## Visual direction

Use a calm, light workspace with one blue action color. The visual hierarchy
comes from whitespace, soft separators and typography rather than heavy borders.
The shell is a white rounded rectangle on `#f5f5f7`, with a muted gray sidebar,
compact title bar and an optional inspector panel.

## Tokens

| Token | Value | Use |
|---|---|---|
| canvas | `#f5f5f7` | application background |
| surface | `#ffffff` | cards, tables, dialogs |
| surface-subtle | `#fafbfc` | filters, inspector, headers |
| ink | `#202633` | primary text |
| muted | `#89909f` | secondary text |
| line | `#e5e8ed` | separators |
| accent | `#3478f6` | primary actions and selection |
| accent-soft | `#eaf1ff` | selected rows and cards |

Typography uses Microsoft YaHei UI on Windows, falling back to Segoe UI. Page
titles use 27 px semibold, section labels 11 px semibold, body text 13 px, and
helper text 11 px. Controls use 9 px corners; metric cards use 12 px corners
and resource cards use 11 px corners. Borders stay one pixel at rest and use
the blue accent on focus or selection.

## Main screen anatomy

1. Frameless title bar: product name, current workspace, minimize, maximize and
   close controls.
2. Sidebar: library name, current folder, all resources / inbox / trash,
   hierarchical custom categories, tags, duplicate check, history and settings.
3. Content header: breadcrumb, live search, page title, sync and choose-folder
   actions.
4. Metric cards: image, video and folder totals. Each card is a toggle filter;
   selected cards use `accent-soft`, a two-pixel `accent` border, and stronger
   blue text. Multiple cards may be selected without clearing the current
   category scope.
5. Filter strip: grade, type, tag and sort controls, followed by grid/list
   switchers.
6. Resource area: responsive thumbnail cards or a compact table. Selection is
   shared between both views.
7. Inspector: selected preview, metadata, path, batch actions and cover actions. Opening a resource is handled by double-click/context menu so the inspector remains focused on information and organization.

## Interaction states

- Buttons use a restrained hover and pressed state and remain disabled while a
  scan or filesystem transaction is running.
- Destructive actions always show a review dialog and move resources to the
  trash area; they never delete immediately.
- Empty, loading, error and selected states have dedicated copy and iconography.
  The sync action uses two opposing arrowheads so it is distinct from history
  and undo. Selected resource cards also carry a short blue accent edge and a
  check badge for keyboard, mouse, and low-contrast thumbnail visibility.
- Folder double-click opens Explorer. Image double-click opens the image viewer;
  video double-click opens the media player.
- Video player exposes a timeline, ±3-second keyboard seeking, and 3× speed
  while holding the right arrow key.

The implementation lives in `rc_app/ui/`; reusable query state and theme tokens
are in `rc_app/models.py`, `rc_app/controller.py` and `rc_app/ui/theme.py`.
