<p align="center">
 <strong>Codex — Static Project Gutenberg Reader</strong><br/>
 A deploy-time digital library built for GitHub Pages.<br/>
 Search, browse, and read thousands of public-domain books without running a backend server.
</p>

<p align="center">
 <img src="./logo.svg" alt="Codex Logo" width="220" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/GitHub%20Pages-Ready-222222?logo=github" alt="GitHub Pages Ready" />
  <img src="https://img.shields.io/badge/Project%20Gutenberg-Library-d69a47" alt="Project Gutenberg Library" />
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white" alt="Python 3.13" />
  <img src="https://img.shields.io/badge/Backend-None-92b95a" alt="No Runtime Backend" />
</p>

---

## Quick Start

<p align="center">
  Push the repository to GitHub, enable <strong>GitHub Actions</strong> as the Pages source, and let the workflow build the library for you.
</p>

```bash
git clone https://github.com/<username>/Codex.git
cd Codex
git push origin main
```

Then open:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

Run **Build and deploy Codex** from the Actions tab, or push a commit to `main`.

The workflow will:

1. Collect book metadata from Gutendex in popularity order
2. Retrieve readable texts from Gutenberg-compatible mirrors
3. Reuse previously cached book downloads
4. Compress book content for static hosting
5. Generate the searchable catalog
6. Package the reader into `site/`
7. Deploy the generated site directly to GitHub Pages

## Features

### Library

- **Library index**  
  Pick from every generated title, filter to books saved on the current device, or jump directly back into books already in progress.

- **Deploy-time Gutenberg ingestion**  
  Books are gathered during GitHub Actions builds instead of being requested from Gutenberg every time a visitor opens the site.

- **Searchable local catalog**  
  Search generated books by title, author, language, or Gutenberg ID directly in the browser.

- **Automatic local book saving**  
  After a book opens successfully, its cleaned text is stored in IndexedDB on that device. Reopening the title uses the local copy first.

- **Offline app shell**  
  A service worker caches the reader, catalog, manifest, and interface assets. Books that have already been saved locally can be reopened without downloading their text again.

- **Static compressed book storage**  
  Deploy-time book content is stored as `.txt.gz` files so more books can fit inside the Pages artifact.

- **Automatic catalog pagination**  
  Browse large generated libraries without loading every result into the visible list at once.

- **Direct book URLs**  
  Open a generated Gutenberg title with a URL such as `?book=84`.

### Reader

- **Desktop mode**  
  Dense archive layout with the persistent library sidebar, desktop window chrome, keyboard navigation, and optional one- or two-page reading.

- **Phone mode**  
  Touch-first catalog with sticky search, larger book targets, single-page reading, compact reader controls, fixed page navigation, and left/right swipe gestures.

- Adjustable font size
- Per-book reading position stored locally with a character-location anchor, so progress survives font-size and desktop/mobile pagination changes
- Automatic layout switching at the phone breakpoint
- **Share Page** links that reopen the same book near the same text location
- **Share Text** for selected passages, using the native share sheet when available and clipboard fallback otherwise
- Shared passage links can highlight the selected quote when the recipient opens the book
- **Choose Book** is always available from the reader so returning to the index does not require browser navigation
- No login or runtime API required

### Deployment

- Fully compatible with GitHub Pages
- Works on both user Pages and repository Pages paths
- Push-triggered deployments from `main`
- Manual workflow dispatches
- Weekly automatic library refreshes
- GitHub Actions cache reuse between builds
- No runtime Python server

## How It Works

```text
Gutendex + Gutenberg mirrors
             |
             v
  scripts/build_library.py
             |
             +--> site/data/catalog.json
             +--> site/data/build.json
             +--> site/books/<id>.txt.gz
             +--> site/index.html
             |
             v
      GitHub Pages artifact
             |
             v
       Static book reader
```

The browser only reads files generated during the build. Visitors do not need direct access to Gutendex or Project Gutenberg for normal reading.

## Configuration

The main build settings are defined in `.github/workflows/pages.yml`:

```yaml
env:
  BOOK_LANGUAGES: ""
  MAX_SITE_BYTES: "850000000"
  MAX_BOOK_BYTES: "26214400"
  MAX_BOOKS: "0"
  DOWNLOAD_DELAY: "0.25"
  GUTENBERG_MIRRORS: "https://aleph.gutenberg.org,https://mirrors.xmission.com/gutenberg"
```

| Setting | Description |
| --- | --- |
| `BOOK_LANGUAGES` | Comma-separated Gutenberg language codes. Empty includes every language exposed by the build source. |
| `MAX_SITE_BYTES` | Approximate generated book-data budget before the builder stops adding titles. |
| `MAX_BOOK_BYTES` | Maximum uncompressed size allowed for a single book. |
| `MAX_BOOKS` | Maximum number of books to include. `0` disables the explicit count limit. |
| `DOWNLOAD_DELAY` | Delay in seconds between uncached mirror downloads. |
| `GUTENBERG_MIRRORS` | Comma-separated Gutenberg-compatible HTTP mirrors. Codex tries them in order. |

### English-Only Library

```yaml
BOOK_LANGUAGES: "en"
```

### Smaller Library

```yaml
MAX_SITE_BYTES: "300000000"
MAX_BOOKS: "5000"
```

## Local Development

Python 3.11 or newer is recommended. The build script uses only the Python standard library.

Generate a small local library:

```bash
python scripts/build_library.py \
  --output site \
  --cache .book-cache \
  --languages en \
  --max-books 25 \
  --max-site-bytes 50000000 \
  --delay 0.25
```

Serve the generated site:

```bash
python -m http.server 8000 --directory site
```

Open:

```text
http://127.0.0.1:8000
```

The source `index.html` is a build input. The generated reader expects `site/data/catalog.json` and `site/books/`, so local testing should be done from the generated `site/` directory.


## Local Library and Sharing

Codex keeps two kinds of browser-local state:

- **Book text:** stored in IndexedDB after the first successful open
- **Reading position and reader preferences:** stored in `localStorage` per Gutenberg ID

Local copies belong to that browser profile and device. Clearing site data removes saved books and progress. The app requests persistent browser storage when supported, but final storage retention is controlled by the browser.

The saved reading position is based on a character location inside the book instead of relying only on a rendered page number. This lets the same progress map onto different page counts when moving between desktop and phone layouts or changing the font size.

Reader sharing supports two link types:

```text
?book=84&loc=12540&p=11
?book=84&loc=12540&p=11&quote=selected%20text
```

`loc` is the stable text location used to reopen the relevant passage. `p` is included as a human-readable page hint. A passage share also includes a short `quote` value so the relevant text can be highlighted after opening.

## Build Output

```text
site/
├── .nojekyll
├── index.html
├── manifest.webmanifest
├── sw.js
├── assets/
│   ├── favicon.png
│   └── logo.png
├── books/
│   ├── 11.txt.gz
│   ├── 84.txt.gz
│   └── ...
└── data/
    ├── catalog.json
    └── build.json
```

`site/` and `.book-cache/` are generated automatically and should not be committed.

## Repository Layout

```text
.
├── .github/
│   └── workflows/
│       └── pages.yml
├── assets/
│   ├── favicon.png
│   └── logo.png
├── scripts/
│   └── build_library.py
├── manifest.webmanifest
├── sw.js
├── .gitattributes
├── .gitignore
├── README.md
└── index.html
```

## Updating the Library

Open:

**Actions → Build and deploy Codex → Run workflow**

A scheduled rebuild also runs every Monday. The Actions cache keeps previously downloaded book text available between builds when possible, reducing unnecessary repeat downloads.


## Troubleshooting

### `HTTP Error 406: Not Acceptable`

Older builds used `https://www.gutenberg.org/robot/harvest`, which can reject requests from shared CI infrastructure such as GitHub Actions. The current Codex builder does not use that endpoint. Metadata is paged from Gutendex and book files are fetched from the mirrors configured in `GUTENBERG_MIRRORS`.

If a mirror is temporarily unavailable, Codex automatically tries the next configured mirror. The Actions cache also retains successful catalog pages and book downloads between builds.

## Data Sources

Codex uses:

- **Project Gutenberg** for public-domain ebook text
- **Gutendex** for searchable Gutenberg metadata

The build process enumerates readable titles through Gutendex and downloads the text from Gutenberg-compatible mirrors instead of scraping normal book pages or calling the `robot/harvest` endpoint. Copyright status may differ between jurisdictions, so anyone publicly redistributing generated content should consider the laws that apply to their deployment.

## Contributing

Improvements to the reader, build pipeline, catalog generation, and interface are welcome.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-change`)
3. Make and test your changes
4. Open a pull request describing what changed

---

<p align="center">
  <strong>Build once. Read anywhere.</strong><br/>
  Static hosting, automatic library generation, and no runtime backend.
</p>
