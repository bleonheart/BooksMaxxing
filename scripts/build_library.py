from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

GUTENDEX_BASE = "https://gutendex.com/books"
DEFAULT_MIRRORS = "https://gutenberg.pglaf.org,https://mirror.cs.odu.edu/gutenberg"
DEFAULT_MAX_SITE_BYTES = 850_000_000
DEFAULT_MAX_BOOK_BYTES = 25 * 1024 * 1024
DEFAULT_DELAY = 0.25
CATALOG_RESERVE_BYTES = 20 * 1024 * 1024
PAGE_SIZE = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="site")
    parser.add_argument("--cache", default=".book-cache")
    parser.add_argument("--max-site-bytes", type=int, default=DEFAULT_MAX_SITE_BYTES)
    parser.add_argument("--max-book-bytes", type=int, default=DEFAULT_MAX_BOOK_BYTES)
    parser.add_argument("--max-books", type=int, default=0)
    parser.add_argument("--languages", default="en")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--mirrors", default=os.environ.get("GUTENBERG_MIRRORS", DEFAULT_MIRRORS))
    return parser.parse_args()


def user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "bleonheart/Codex")
    repository_url = f"https://github.com/{repository}" if "/" in repository else repository
    return f"Codex static-library builder/1.0 (+{repository_url})"


def request_bytes(
    url: str,
    accept: str = "*/*",
    timeout: int = 60,
    max_bytes: int | None = None,
    retries: int = 2,
) -> bytes:
    headers = {
        "Accept": accept,
        "Accept-Encoding": "identity",
        "User-Agent": user_agent(),
    }
    contact = os.environ.get("GUTENBERG_CONTACT", "").strip()
    if contact:
        headers["From"] = contact

    request = urllib.request.Request(url, headers=headers)

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                length = response.headers.get("Content-Length")
                if max_bytes is not None and length and int(length) > max_bytes:
                    raise ValueError("response is too large")
                if max_bytes is None:
                    return response.read()
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise ValueError("response is too large")
                return data
        except urllib.error.HTTPError as error:
            if error.code < 500 and error.code != 429:
                raise
            if attempt >= retries:
                raise
            retry_after = error.headers.get("Retry-After") if error.headers else None
            wait = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 8)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError):
            if attempt >= retries:
                raise
            time.sleep(min(2 ** attempt, 8))

    raise RuntimeError("request failed")


def request_json(url: str) -> dict:
    return json.loads(request_bytes(url, "application/json", 60, 16 * 1024 * 1024).decode("utf-8"))


def catalog_url(page: int, languages: list[str]) -> str:
    params: list[tuple[str, str]] = [
        ("page", str(page)),
        ("sort", "popular"),
        ("mime_type", "text/plain"),
    ]
    if languages:
        params.append(("languages", ",".join(languages)))
    return f"{GUTENDEX_BASE}?{urllib.parse.urlencode(params)}"


def catalog_cache_path(cache_catalog: Path, page: int, languages: list[str]) -> Path:
    key = ",".join(languages) if languages else "all"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return cache_catalog / f"{digest}-page-{page}.json"


def fetch_catalog_page(page: int, languages: list[str], cache_catalog: Path) -> tuple[dict, bool]:
    path = catalog_cache_path(cache_catalog, page, languages)
    url = catalog_url(page, languages)

    try:
        payload = request_json(url)
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return payload, False
    except Exception as error:
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                print(f"catalog page {page}: network failed ({error}); using cached page", file=sys.stderr)
                return payload, True
            except (OSError, json.JSONDecodeError):
                pass
        raise


def mirror_directory(book_id: int) -> str:
    value = str(book_id)
    prefix = "/".join(value[:-1])
    return f"{prefix}/{value}" if prefix else value


def text_stems_from_metadata(book_id: int, metadata: dict) -> list[str]:
    stems: list[str] = []
    formats = metadata.get("formats") if isinstance(metadata.get("formats"), dict) else {}

    for mime, url in formats.items():
        if not isinstance(mime, str) or not mime.startswith("text/plain") or not isinstance(url, str):
            continue
        filename = Path(urllib.parse.urlparse(url).path).name
        match = re.match(r"^(\d+(?:-[A-Za-z0-9]+)?)\.txt(?:\..*)?$", filename, re.IGNORECASE)
        if match:
            stems.append(match.group(1))

    for stem in (f"{book_id}-0", str(book_id), f"{book_id}-8"):
        if stem not in stems:
            stems.append(stem)

    return stems


def book_candidates(book_id: int, metadata: dict, mirrors: list[str]) -> list[str]:
    directory = mirror_directory(book_id)
    candidates: list[str] = []

    for mirror in mirrors:
        base = mirror.rstrip("/")
        for stem in text_stems_from_metadata(book_id, metadata):
            candidates.append(f"{base}/{directory}/{stem}.zip")
        candidates.extend(
            [
                f"{base}/cache/epub/{book_id}/pg{book_id}.txt",
                f"{base}/cache/epub/{book_id}/pg{book_id}-images.txt",
            ]
        )

    unique: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_archive(data: bytes, max_book_bytes: int) -> str:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        candidates = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir() and entry.filename.lower().endswith(".txt")
        ]
        if not candidates:
            raise ValueError("archive has no text file")
        entry = max(candidates, key=lambda item: item.file_size)
        if entry.file_size > max_book_bytes:
            raise ValueError("book is too large")
        with archive.open(entry) as handle:
            raw = handle.read(max_book_bytes + 1)
        if len(raw) > max_book_bytes:
            raise ValueError("book is too large")
    return decode_text(raw)


def gzip_text(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)


def compact_metadata(book_id: int, metadata: dict, file_name: str, compressed_bytes: int) -> dict:
    authors = []
    for author in metadata.get("authors", []):
        name = author.get("name") if isinstance(author, dict) else None
        if name:
            authors.append({"name": name})

    summaries = metadata.get("summaries") if isinstance(metadata.get("summaries"), list) else []
    summary = str(summaries[0])[:700] if summaries else ""

    return {
        "id": book_id,
        "title": metadata.get("title") or f"Project Gutenberg #{book_id}",
        "authors": authors,
        "languages": metadata.get("languages") or [],
        "download_count": int(metadata.get("download_count") or 0),
        "summary": summary,
        "file": file_name,
        "compressed_bytes": compressed_bytes,
    }


def prepare_output(root: Path, output: Path) -> None:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copy2(root / "index.html", output / "index.html")
    for static_file in ("sw.js", "manifest.webmanifest"):
        source = root / static_file
        if source.exists():
            shutil.copy2(source, output / static_file)
    assets = root / "assets"
    if assets.exists():
        shutil.copytree(assets, output / "assets")
    (output / ".nojekyll").write_text("", encoding="utf-8")
    (output / "books").mkdir()
    (output / "data").mkdir()


def download_book(
    book_id: int,
    metadata: dict,
    cache_books: Path,
    max_book_bytes: int,
    delay: float,
    mirrors: list[str],
) -> Path | None:
    cached = cache_books / f"{book_id}.txt.gz"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    for url in book_candidates(book_id, metadata, mirrors):
        try:
            if url.lower().endswith(".zip"):
                data = request_bytes(
                    url,
                    "application/zip,application/octet-stream,*/*;q=0.5",
                    90,
                    max_book_bytes + 8 * 1024 * 1024,
                    1,
                )
                text = extract_archive(data, max_book_bytes)
            else:
                data = request_bytes(url, "text/plain,*/*;q=0.5", 90, max_book_bytes, 1)
                text = decode_text(data)

            if not text.strip():
                raise ValueError("book text is empty")

            compressed = gzip_text(text)
            cached.write_bytes(compressed)
            if delay > 0:
                time.sleep(delay)
            return cached
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, zipfile.BadZipFile, OSError) as error:
            print(f"skip candidate {url}: {error}", file=sys.stderr)

    if delay > 0:
        time.sleep(delay)
    return None


def site_shell_bytes(output: Path) -> int:
    total = 0
    for path in output.rglob("*"):
        if path.is_file() and "books" not in path.parts and "data" not in path.parts:
            total += path.stat().st_size
    return total


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    cache = (root / args.cache).resolve()
    cache_books = cache / "books"
    cache_catalog = cache / "catalog"
    cache_books.mkdir(parents=True, exist_ok=True)
    cache_catalog.mkdir(parents=True, exist_ok=True)
    prepare_output(root, output)

    max_payload_bytes = max(0, args.max_site_bytes - CATALOG_RESERVE_BYTES)
    languages = [value.strip() for value in args.languages.split(",") if value.strip()]
    mirrors = [value.strip().rstrip("/") for value in args.mirrors.split(",") if value.strip()]
    if not mirrors:
        mirrors = [value.strip().rstrip("/") for value in DEFAULT_MIRRORS.split(",") if value.strip()]
    catalog: list[dict] = []
    used_bytes = 0
    catalog_pages = 0
    cached_catalog_pages = 0
    failures = 0
    page = 1
    exhausted = False

    while used_bytes < max_payload_bytes and not exhausted:
        if args.max_books and len(catalog) >= args.max_books:
            break

        print(f"catalog page {page}: {catalog_url(page, languages)}")
        try:
            payload, used_cached_page = fetch_catalog_page(page, languages, cache_catalog)
        except Exception as error:
            print(f"catalog failed on page {page}: {error}", file=sys.stderr)
            break

        catalog_pages += 1
        cached_catalog_pages += int(used_cached_page)
        books = payload.get("results", [])
        if not isinstance(books, list) or not books:
            break

        for metadata in books:
            if args.max_books and len(catalog) >= args.max_books:
                exhausted = True
                break
            if not isinstance(metadata, dict):
                continue

            try:
                book_id = int(metadata["id"])
            except (KeyError, TypeError, ValueError):
                continue

            cached = cache_books / f"{book_id}.txt.gz"
            if cached.exists() and cached.stat().st_size > 0:
                book_path = cached
            else:
                book_path = download_book(
                    book_id,
                    metadata,
                    cache_books,
                    args.max_book_bytes,
                    args.delay,
                    mirrors,
                )

            if book_path is None:
                failures += 1
                continue

            size = book_path.stat().st_size
            if used_bytes + size > max_payload_bytes:
                exhausted = True
                break

            relative_file = f"books/{book_id}.txt.gz"
            shutil.copy2(book_path, output / relative_file)
            used_bytes += size
            catalog.append(compact_metadata(book_id, metadata, relative_file, size))

            if len(catalog) % 25 == 0:
                print(f"included {len(catalog)} books, {used_bytes / 1024 / 1024:.1f} MiB compressed")

        if exhausted or not payload.get("next"):
            break
        page += 1

    catalog.sort(key=lambda book: (book["download_count"], -book["id"]), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(catalog),
        "compressed_bytes": used_bytes,
        "languages": languages,
        "source": "Gutendex metadata + Project Gutenberg mirror text",
        "books": catalog,
    }
    catalog_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (output / "data" / "catalog.json").write_bytes(catalog_bytes)
    total_bytes = used_bytes + len(catalog_bytes) + site_shell_bytes(output)

    stats = {
        "books": len(catalog),
        "book_bytes": used_bytes,
        "catalog_bytes": len(catalog_bytes),
        "estimated_site_bytes": total_bytes,
        "catalog_pages": catalog_pages,
        "cached_catalog_pages": cached_catalog_pages,
        "failures": failures,
        "mirrors": mirrors,
    }
    (output / "data" / "build.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))

    if not catalog:
        print("No books were built.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
