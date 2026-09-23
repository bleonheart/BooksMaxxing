from __future__ import annotations

import argparse
import gzip
import html.parser
import json
import os
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
HARVEST_BASE = "https://www.gutenberg.org/robot/harvest"
DEFAULT_MAX_SITE_BYTES = 850_000_000
DEFAULT_MAX_BOOK_BYTES = 25 * 1024 * 1024
DEFAULT_DELAY = 2.0
CATALOG_RESERVE_BYTES = 20 * 1024 * 1024


class HarvestParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        self._href = dict(attrs).get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append((self._href, "".join(self._text).strip()))
        self._href = None
        self._text = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="site")
    parser.add_argument("--cache", default=".book-cache")
    parser.add_argument("--max-site-bytes", type=int, default=DEFAULT_MAX_SITE_BYTES)
    parser.add_argument("--max-book-bytes", type=int, default=DEFAULT_MAX_BOOK_BYTES)
    parser.add_argument("--max-books", type=int, default=0)
    parser.add_argument("--languages", default="en")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    return parser.parse_args()


def user_agent() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "BooksMaxxing")
    return f"BooksMaxxing static-library builder ({repository})"


def request_bytes(
    url: str,
    accept: str = "*/*",
    timeout: int = 60,
    max_bytes: int | None = None,
    retries: int = 2,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": user_agent(),
        },
    )

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
            delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 8)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError):
            if attempt >= retries:
                raise
            time.sleep(min(2 ** attempt, 8))

    raise RuntimeError("request failed")


def request_json(url: str) -> dict:
    return json.loads(request_bytes(url, "application/json", 45, 8 * 1024 * 1024).decode("utf-8"))


def harvest_url(languages: list[str]) -> str:
    params: list[tuple[str, str]] = [("filetypes[]", "txt")]
    params.extend(("langs[]", language) for language in languages)
    return f"{HARVEST_BASE}?{urllib.parse.urlencode(params)}"


def parse_harvest_page(url: str) -> tuple[dict[int, list[str]], str | None]:
    document = request_bytes(url, "text/html", 45, 2 * 1024 * 1024).decode("utf-8", errors="replace")
    parser = HarvestParser()
    parser.feed(document)
    archives: dict[int, list[str]] = {}
    next_url: str | None = None

    for href, text in parser.links:
        absolute = urllib.parse.urljoin(url, href)
        filename = Path(urllib.parse.urlparse(absolute).path).name
        stem = filename[:-4] if filename.lower().endswith(".zip") else filename
        prefix = stem.split("-", 1)[0]

        if prefix.isdigit() and absolute.lower().endswith(".zip"):
            archives.setdefault(int(prefix), []).append(absolute)

        if text.lower() == "next page":
            next_url = absolute

    return archives, next_url


def archive_rank(url: str, book_id: int) -> tuple[int, str]:
    name = Path(urllib.parse.urlparse(url).path).name.lower()
    if name == f"{book_id}-0.zip":
        return 0, name
    if name == f"{book_id}.zip":
        return 1, name
    if name == f"{book_id}-8.zip":
        return 2, name
    return 3, name


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


def metadata_path(cache_metadata: Path, book_id: int) -> Path:
    return cache_metadata / f"{book_id}.json"


def fetch_metadata(ids: list[int], cache_metadata: Path) -> dict[int, dict]:
    result: dict[int, dict] = {}
    missing: list[int] = []

    for book_id in ids:
        path = metadata_path(cache_metadata, book_id)
        if path.exists():
            try:
                result[book_id] = json.loads(path.read_text(encoding="utf-8"))
                continue
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
        missing.append(book_id)

    for start in range(0, len(missing), 32):
        batch = missing[start:start + 32]
        if not batch:
            continue
        query = urllib.parse.urlencode({"ids": ",".join(str(book_id) for book_id in batch)})
        url: str | None = f"{GUTENDEX_BASE}?{query}"
        while url:
            payload = request_json(url)
            for book in payload.get("results", []):
                try:
                    book_id = int(book["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                result[book_id] = book
                metadata_path(cache_metadata, book_id).write_text(
                    json.dumps(book, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )
            url = payload.get("next")

    return result


def compact_metadata(book_id: int, metadata: dict | None, file_name: str, compressed_bytes: int) -> dict:
    metadata = metadata or {}
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
    urls: list[str],
    cache_books: Path,
    max_book_bytes: int,
    delay: float,
) -> Path | None:
    cached = cache_books / f"{book_id}.txt.gz"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    for url in sorted(urls, key=lambda value: archive_rank(value, book_id)):
        try:
            data = request_bytes(url, "application/zip,application/octet-stream", 90, max_book_bytes + 8 * 1024 * 1024, 0)
            text = extract_archive(data, max_book_bytes)
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


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    cache = (root / args.cache).resolve()
    cache_books = cache / "books"
    cache_metadata = cache / "metadata"
    cache_books.mkdir(parents=True, exist_ok=True)
    cache_metadata.mkdir(parents=True, exist_ok=True)
    prepare_output(root, output)

    max_payload_bytes = max(0, args.max_site_bytes - CATALOG_RESERVE_BYTES)
    languages = [value.strip() for value in args.languages.split(",") if value.strip()]
    next_harvest = harvest_url(languages)
    catalog: list[dict] = []
    used_bytes = 0
    seen_ids: set[int] = set()
    harvest_pages = 0
    failures = 0

    while next_harvest and used_bytes < max_payload_bytes:
        if args.max_books and len(catalog) >= args.max_books:
            break

        print(f"harvest page {harvest_pages + 1}: {next_harvest}")
        try:
            archives, next_harvest = parse_harvest_page(next_harvest)
        except Exception as error:
            print(f"harvest failed: {error}", file=sys.stderr)
            break

        harvest_pages += 1
        ids = [book_id for book_id in archives if book_id not in seen_ids]
        try:
            metadata = fetch_metadata(ids, cache_metadata)
        except Exception as error:
            print(f"metadata batch failed: {error}", file=sys.stderr)
            metadata = {}

        ids.sort(key=lambda book_id: int(metadata.get(book_id, {}).get("download_count") or 0), reverse=True)

        for book_id in ids:
            seen_ids.add(book_id)
            if args.max_books and len(catalog) >= args.max_books:
                break

            cached = cache_books / f"{book_id}.txt.gz"
            if cached.exists() and cached.stat().st_size > 0:
                book_path = cached
            else:
                book_path = download_book(
                    book_id,
                    archives[book_id],
                    cache_books,
                    args.max_book_bytes,
                    args.delay,
                )

            if book_path is None:
                failures += 1
                continue

            size = book_path.stat().st_size
            if used_bytes + size > max_payload_bytes:
                next_harvest = None
                break

            relative_file = f"books/{book_id}.txt.gz"
            shutil.copy2(book_path, output / relative_file)
            used_bytes += size
            catalog.append(compact_metadata(book_id, metadata.get(book_id), relative_file, size))

            if len(catalog) % 25 == 0:
                print(f"included {len(catalog)} books, {used_bytes / 1024 / 1024:.1f} MiB compressed")

        if args.delay > 0 and next_harvest:
            time.sleep(args.delay)

    catalog.sort(key=lambda book: (book["download_count"], -book["id"]), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(catalog),
        "compressed_bytes": used_bytes,
        "languages": languages,
        "books": catalog,
    }
    catalog_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    (output / "data" / "catalog.json").write_bytes(catalog_bytes)
    total_bytes = used_bytes + len(catalog_bytes) + (output / "index.html").stat().st_size

    stats = {
        "books": len(catalog),
        "book_bytes": used_bytes,
        "catalog_bytes": len(catalog_bytes),
        "estimated_site_bytes": total_bytes,
        "harvest_pages": harvest_pages,
        "failures": failures,
    }
    (output / "data" / "build.json").write_text(
        json.dumps(stats, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(stats, indent=2))

    if not catalog:
        print("No books were built.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
