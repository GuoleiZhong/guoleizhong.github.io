#!/usr/bin/env python3
"""Mirror published Google Sites content without changing the last good site on failure."""
from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path
import re
import runpy
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from google_sites import ParseError, parse_pages


BASE = "https://sites.google.com/view/guoleizhongshomepage/"
PAGES = ("home", "research", "talks", "teaching", "links")
MAX_PAGE = 4_000_000
MAX_PDF = 24_000_000
MAX_IMAGE = 20_000_000
FIXED_OUTPUTS = {
    "index.html", "research.html", "talks.html", "teaching.html", "links.html", "404.html",
    *(f"{page}/index.html" for page in PAGES),
    "source/content.json", "source/local-files.json", "source/sync-state.json",
    "assets/images/banner.webp", "assets/images/guolei-zhong-huangshan.webp",
}


class SyncError(RuntimeError):
    """A failed sync must leave the published version unchanged."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def allowed_google_url(url: str) -> bool:
    try:
        part = urlsplit(url)
        host = (part.hostname or "").lower()
        return (part.scheme == "https" and not part.username and not part.password
                and part.port in (None, 443)
                and (host in {"sites.google.com", "drive.google.com", "drive.usercontent.google.com"}
                     or host == "googleusercontent.com" or host.endswith(".googleusercontent.com")))
    except ValueError:
        return False


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_google_url(urljoin(req.full_url, newurl)):
            raise SyncError("Google resource redirected outside the supported public hosts")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, limit: int) -> bytes:
    """Fetch public resources only, with bounded size, redirects, retries and timeouts."""
    if not allowed_google_url(url):
        raise SyncError("Unsupported download host or URL")
    opener = build_opener(SafeRedirect())
    last: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "GuoleiHomepageSync/1.0", "Accept-Encoding": "identity"})
            with opener.open(request, timeout=45) as response:
                if response.status != 200:
                    raise SyncError(f"Unexpected HTTP status {response.status}")
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > limit:
                    raise SyncError("Remote resource exceeds the configured size limit")
                data = response.read(limit + 1)
                if len(data) > limit or not data:
                    raise SyncError("Empty or oversized remote resource")
                return data
        except HTTPError as exc:
            last = exc
            if exc.code not in {408, 429, 500, 502, 503, 504}:
                break
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise SyncError(f"Unable to fetch public resource ({type(last).__name__})") from last


def drive_id(url: str) -> str | None:
    part = urlsplit(url)
    if part.hostname != "drive.google.com" or part.scheme not in {"http", "https"}:
        return None
    match = re.match(r"^/file/d/([A-Za-z0-9_-]+)(?:/|$)", part.path)
    identifier = match[1] if match else parse_qs(part.query).get("id", [None])[0]
    return identifier if identifier and re.fullmatch(r"[A-Za-z0-9_-]{10,160}", identifier) else None


def drive_download_url(identifier: str) -> str:
    return "https://drive.usercontent.google.com/download?" + urlencode({"id": identifier, "export": "download", "authuser": "0", "confirm": "t"})


def item_links(value: object) -> set[str]:
    if isinstance(value, dict):
        found = {value["url"]} if isinstance(value.get("url"), str) else set()
        for child in value.values():
            found |= item_links(child)
        return found
    if isinstance(value, list):
        return set().union(*(item_links(child) for child in value)) if value else set()
    return set()


def public_pdf_path(relative: str) -> bool:
    return bool(re.fullmatch(r"files/[A-Za-z0-9][A-Za-z0-9_.-]*\.pdf", relative))


def read_json(path: Path, default: dict | None = None) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else (default or {})


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def guard_item_loss(previous: dict, current: dict, allow: bool) -> None:
    for key in ("publications", "talks", "teaching", "collaborators", "homeItems"):
        old, new = previous.get(key, []), current.get(key, [])
        if not isinstance(old, list) or not isinstance(new, list):
            raise SyncError(f"Invalid content collection: {key}")
        if not allow and len(old) >= 3 and len(new) < len(old) * 0.6:
            raise SyncError(f"Unexpected loss of {key} items; review source or use --allow-large-removal deliberately")


def sync_documents(stage: Path, content: dict, mapping: dict, downloader: Callable[[str, int], bytes]) -> dict:
    by_id = {drive_id(url): path for url, path in mapping.items() if drive_id(url)}
    for path in mapping.values():
        if not isinstance(path, str) or not public_pdf_path(path):
            raise SyncError("Unsafe path in local-files.json")
    urls = item_links(content)
    cv = content.get("profile", {}).get("cv", "")
    if cv:
        urls.add(cv)
    grouped: dict[str, list[str]] = {}
    for url in sorted(urls):
        identifier = drive_id(url)
        if identifier:
            grouped.setdefault(identifier, []).append(url)
    if len(grouped) > 150:
        raise SyncError("Too many linked Google Drive documents")
    used_targets: dict[str, str] = {}
    for identifier, aliases in grouped.items():
        target = "files/guolei-zhong-cv.pdf" if identifier == drive_id(cv) else by_id.get(identifier, f"files/google-drive-{identifier}.pdf")
        if (target == "files/guolei-zhong-cv.pdf" and identifier != drive_id(cv)) or (target in used_targets and used_targets[target] != identifier):
            target = f"files/google-drive-{identifier}.pdf"
        used_targets[target] = identifier
        try:
            data = downloader(drive_download_url(identifier), MAX_PDF)
        except SyncError as exc:
            raise SyncError(f"Could not update {target}: {exc}") from exc
        if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-8192:]:
            raise SyncError(f"{target}: linked Google Drive file is unavailable, private, non-PDF, or incomplete")
        (stage / target).write_bytes(data)
        for alias in aliases:
            mapping[alias] = target
    return mapping


def sync_image(stage: Path, source_url: str, destination: str, old_state: dict,
               downloader: Callable[[str, int], bytes]) -> tuple[dict, tuple[int, int]]:
    from PIL import Image, ImageOps, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = 30_000_000
    data = downloader(source_url, MAX_IMAGE)
    source_hash = digest(data)
    target = stage / destination
    # Signed Google image URLs change over time. Compare image bytes, not URLs.
    if old_state.get("source_sha256") == source_hash and target.exists():
        with Image.open(target) as previous:
            return old_state, previous.size
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise SyncError("Unsupported homepage image format")
            if source.width * source.height > 30_000_000:
                raise SyncError("Homepage image exceeds the pixel limit")
            picture = ImageOps.exif_transpose(source).convert("RGB")
            picture.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            size = picture.size
            picture.save(target, "WEBP", quality=85, method=6)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SyncError("Invalid or oversized homepage image") from exc
    return {"source_sha256": source_hash, "output_sha256": digest(target.read_bytes())}, size


class LocalLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            raise SyncError("Generated pages must not contain JavaScript")
        for key, value in attrs:
            if key.lower().startswith("on"):
                raise SyncError("Generated pages must not contain event handlers")
            if key in {"href", "src"} and value:
                self.urls.append(value)


def validate_site(stage: Path) -> None:
    for relative in sorted(FIXED_OUTPUTS):
        if not relative.endswith(".html"):
            continue
        path = stage / relative
        if not path.exists():
            raise SyncError(f"Missing generated page: {relative}")
        parser = LocalLinks()
        parser.feed(path.read_text(encoding="utf-8"))
        for url in parser.urls:
            parts = urlsplit(url)
            if parts.scheme:
                if parts.scheme not in {"http", "https", "mailto", "tel"}:
                    raise SyncError("Unsafe scheme in generated page")
                continue
            if parts.netloc:
                raise SyncError("Protocol-relative URL in generated page")
            if not parts.path:
                continue
            target = ((stage / parts.path.lstrip("/")) if parts.path.startswith("/") else (path.parent / parts.path)).resolve()
            if not target.is_relative_to(stage.resolve()) or not target.exists():
                raise SyncError(f"Broken local link in {relative}: {parts.path}")


def mirror(root: Path, downloader: Callable[[str, int], bytes] = fetch,
           allow_large_removal: bool = False, now: datetime | None = None) -> list[str]:
    """Prepare and validate everything in isolation before replacing any live files."""
    root = root.resolve()
    if any(path.is_symlink() for path in root.rglob("*") if '.git' not in path.parts):
        raise SyncError("Symlinks are not supported in the site")
    old = read_json(root / "source/content.json")
    state = read_json(root / "source/sync-state.json")
    pages = {page: downloader(BASE + page, MAX_PAGE).decode("utf-8") for page in PAGES}
    content = parse_pages(pages, previous=old)
    guard_item_loss(old, content, allow_large_removal)
    now = now or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="guolei-sync-") as temporary:
        stage = Path(temporary) / "site"
        shutil.copytree(root, stage, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv", ".DS_Store"))
        for path in stage.rglob("*"):
            if path.is_symlink():
                raise SyncError("Symlinks are not supported in the site")
        mapping = sync_documents(stage, content, read_json(stage / "source/local-files.json"), downloader)
        images = state.get("images", {})
        portrait_url = content["profile"].get("portrait", "")
        banner_url = content.get("bannerUrl", "")
        if not portrait_url or not banner_url:
            raise SyncError("Missing homepage image or banner")
        portrait_state, portrait_size = sync_image(stage, portrait_url, "assets/images/guolei-zhong-huangshan.webp", images.get("portrait", {}), downloader)
        banner_state, _ = sync_image(stage, banner_url, "assets/images/banner.webp", images.get("banner", {}), downloader)
        content["profile"]["portrait"] = "assets/images/guolei-zhong-huangshan.webp"
        content["profile"]["portraitWidth"], content["profile"]["portraitHeight"] = portrait_size
        content["bannerUrl"] = "assets/images/banner.webp"
        # Keep no-op checks clean: update retrieval date only when semantic content changes.
        content.pop("retrieved", None)
        old_comparable = {key: value for key, value in old.items() if key != "retrieved"}
        content["retrieved"] = old.get("retrieved", now.date().isoformat()) if content == old_comparable else now.date().isoformat()
        write_json(stage / "source/content.json", content)
        write_json(stage / "source/local-files.json", dict(sorted(mapping.items())))
        write_json(stage / "source/sync-state.json", {
            "version": 1,
            "last_successful_month": now.strftime("%Y-%m"),
            "images": {"portrait": portrait_state, "banner": banner_state},
        })
        runpy.run_path(str(stage / "source/build.py"), run_name="__main__")
        validate_site(stage)
        outputs = FIXED_OUTPUTS | {str(path.relative_to(stage)) for path in (stage / "files").glob("*.pdf")}
        changed = [name for name in sorted(outputs) if (stage / name).is_file()
                   and (not (root / name).exists() or (root / name).read_bytes() != (stage / name).read_bytes())]
        # Fetching, parsing, rebuilding and validation cannot mutate the last good version.
        # A runner killed during this final copy still cannot publish: the following git
        # commit/deploy steps run only after this process succeeds.
        for name in changed:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            replacement = target.with_name(target.name + ".sync-tmp")
            shutil.copyfile(stage / name, replacement)
            replacement.replace(target)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allow-large-removal", action="store_true", help="Permit deliberate removal of over 40%% of a content collection")
    args = parser.parse_args()
    try:
        changed = mirror(args.root, allow_large_removal=args.allow_large_removal)
    except (SyncError, ParseError, ValueError, OSError) as exc:
        print(f"Sync stopped; published site remains unchanged: {exc}")
        return 1
    print(f"Sync verified: {len(changed)} changed files.")
    for path in changed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
