# TRACKROOM v5.7 — HD album artwork in the bubble canvas

Update based on TRACKROOM v5.6. This patch changes only `public/app.js`.

## Changes
- Apple/iTunes artwork supplied as `artworkUrl100` (typically 100x100 pixels) is requested from Apple's CDN at 600x600 for the large music bubbles and their detail panel.
- For an unsupported image URL or non-Apple provider, keep the original URL untouched.
- If a high-resolution image fails to load, automatically try the original image; if that fails, use the existing fallback artwork.
- Covers previously added and saved in rooms get upgraded when the bubble UI renders. No SQLite migration, API key change, or re-registration is needed.
- Small search-result thumbnails remain unchanged to avoid unnecessary data use.

## Installation
1. Open the GitHub repository at `trackroom/public`.
2. Replace `public/app.js` with the file in this ZIP at the same path.
3. Commit changes and wait for Render to report Live.
4. Hard-refresh the site (Ctrl+Shift+R, or refresh in a private tab on mobile).

No change to `server.py`, `public/style.css`, `public/index.html`, or Render environment variables is needed.

## Notes
- Image clarity improves only when a matching higher-resolution image exists on Apple's CDN; upscaling a low-resolution source by CSS does not create image detail.
- An absent/mismatched cover remains absent; the patch does not change song matching or catalog search.
- Apple artwork use must comply with the content owner's copyright and Apple's promotional-content terms, even for an unlisted site.

## Validation
- Node.js syntax check passed.
- 7 Apple/non-Apple image URL rewrite cases passed.
- Bubble markup fallback checks passed.
- Existing TRACKROOM v5.6 server suite: 30 tests passed.
- Real Apple image CDN requests and deployed Render environment were not tested here.
