<p align="center">
  <strong>BooksMaxxing — Static Project Gutenberg Reader</strong><br/>
  A deploy-time digital library built for GitHub Pages.<br/>
  Search, browse, and read thousands of public-domain books without running a backend server.<br/><br/>
  <img src="./assets/logo.png" alt="BooksMaxxing Logo" width="180" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/GitHub%20Pages-Ready-222222?logo=github" alt="GitHub Pages Ready" />
  <img src="https://img.shields.io/badge/Project%20Gutenberg-Library-d69a47" alt="Project Gutenberg Library" />
  <img src="https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white" alt="Python 3.13" />
  <img src="https://img.shields.io/badge/Backend-None-92b95a" alt="No Runtime Backend" />
</p>

<h1 align="center">BooksMaxxing</h1>

---

## Quick Start

<p align="center">
  Push the repository to GitHub, enable <strong>GitHub Actions</strong> as the Pages source, and let the workflow build the library for you.
</p>

```bash
git clone https://github.com/<username>/<repository>.git
cd <repository>
git push origin main
```

Then open:

**Settings → Pages → Build and deployment → Source → GitHub Actions**

Run **Build and deploy Gutenberg library** from the Actions tab, or push a commit to `main`.

The workflow will:

1. Collect book metadata from Gutendex
2. Retrieve readable Project Gutenberg texts
3. Reuse previously cached book downloads
4. Compress book content for static hosting
5. Generate the searchable catalog
6. Package the reader into `site/`
7. Deploy the generated site directly to GitHub Pages

## Features

### Library

- **Deploy-time Gutenberg ingestion**  
  Books are gathered during GitHub Actions builds instead of being requested from Gutenberg every time a visitor opens the site.

- **Searchable local catalog**  
  Search generated books by title or author directly in the browser.

- **Static compressed book storage**  
  Readable text is stored as `.txt.gz` files so more books can fit inside the Pages artifact.

- **Automatic catalog pagination**  
  Browse large generated libraries without loading every result into the visible list at once.

- **Direct book URLs**  
  Open a generated Gutenberg title with a URL such as `?book=84`.

### Reader

- Single-page and two-page reading layouts
- Adjustable font size
- Keyboard navigation
- Per-book reading progress using `localStorage`
- Responsive browser-based reading interface
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
Project Gutenberg + Gutendex
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
  DOWNLOAD_DELAY: "2"
```

| Setting | Description |
| --- | --- |
| `BOOK_LANGUAGES` | Comma-separated Gutenberg language codes. Empty includes every language exposed by the build source. |
| `MAX_SITE_BYTES` | Approximate generated book-data budget before the builder stops adding titles. |
| `MAX_BOOK_BYTES` | Maximum uncompressed size allowed for a single book. |
| `MAX_BOOKS` | Maximum number of books to include. `0` disables the explicit count limit. |
| `DOWNLOAD_DELAY` | Delay in seconds between uncached Gutenberg downloads. |

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
  --delay 2
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

## Build Output

```text
site/
├── .nojekyll
├── index.html
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
├── .gitattributes
├── .gitignore
├── README.md
└── index.html
```

## Updating the Library

Open:

**Actions → Build and deploy Gutenberg library → Run workflow**

A scheduled rebuild also runs every Monday. The Actions cache keeps previously downloaded book text available between builds when possible, reducing unnecessary repeat downloads.

## Data Sources

BooksMaxxing uses:

- **Project Gutenberg** for public-domain ebook text
- **Gutendex** for searchable Gutenberg metadata

The build process uses Gutenberg-oriented automated download sources rather than scraping normal book pages. Copyright status may differ between jurisdictions, so anyone publicly redistributing generated content should consider the laws that apply to their deployment.

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
