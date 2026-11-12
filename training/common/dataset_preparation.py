"""Portable, non-training dataset acquisition with explicit annotation readiness."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import yaml

from safesight.config import within
from safesight.contracts import CLASSES


def file_hash(path: Path) -> str:
    """Hash an archive or installed file without reading it all into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward provider credentials to a download CDN."""

    def redirect_request(self, request, fp, code, message, headers, newurl):
        redirected = super().redirect_request(request, fp, code, message, headers, newurl)
        if redirected and urllib.parse.urlsplit(request.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def open_url(url: str, headers: dict | None = None):
    """Open HTTPS sources, permitting HTTP only for loopback test servers."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")):
        raise ValueError("Dataset URLs must use HTTPS")
    return urllib.request.build_opener(SafeRedirect()).open(
        urllib.request.Request(url, headers={"User-Agent": "SafeSight-dataset-preparation/1", **(headers or {})}),
        timeout=60,
    )


def source_url(source: dict) -> tuple[str, dict, bool]:
    """Resolve an authenticated provider export without persisting private links/keys."""
    override = os.getenv(source.get("url_env", ""))
    if override:
        return override, {}, True
    kind = source["kind"]
    if kind == "http":
        return source["url"], {}, False
    if kind == "kaggle":
        headers = {}
        username, key = os.getenv("KAGGLE_USERNAME"), os.getenv("KAGGLE_KEY")
        if username and key:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{key}".encode()).decode()
        return "https://www.kaggle.com/api/v1/datasets/download/" + source["dataset"], headers, False
    if kind == "roboflow":
        key = os.getenv("ROBOFLOW_API_KEY")
        if not key:
            raise ValueError(
                "Set ROBOFLOW_API_KEY in .env, supply a local archive, or set the source archive URL environment variable"
            )
        endpoint = "https://api.roboflow.com/{workspace}/{project}/{version}/{format}".format(**source)
        url = endpoint + "?" + urllib.parse.urlencode({"api_key": key})
        for _ in range(12):
            try:
                with open_url(url) as response:
                    data = json.load(response)
                    if data.get("export", {}).get("link"):
                        return data["export"]["link"], {}, False
            except urllib.error.HTTPError as error:
                raise ValueError(f"Roboflow export failed (HTTP {error.code}); check project access and key") from None
            time.sleep(5)
        raise ValueError("Roboflow export is still building; rerun this command later")
    raise ValueError(f"Unsupported source provider: {kind}")


def download(url: str, target: Path, headers: dict, expected: str | None, reserve: int, estimate: int) -> dict:
    """Resume only a validated partial transfer; never log signed/private URLs."""
    target.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = target.with_suffix(".receipt.json")
    if target.exists():
        actual = file_hash(target)
        receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
        if (expected and actual == expected) or (not expected and receipt.get("sha256") == actual):
            return {"sha256": actual, "bytes": target.stat().st_size, "cached": True}
        raise ValueError(
            "Existing cached archive checksum is invalid; preserve/inspect it or choose a new cache directory"
        )
    partial = target.with_suffix(".part")
    state_path = target.with_suffix(".http.json")
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    identity = hashlib.sha256(url.encode()).hexdigest()
    offset = (
        partial.stat().st_size
        if partial.exists() and state.get("url_hash") == identity and (expected or state.get("validator"))
        else 0
    )
    if shutil.disk_usage(target.parent).free < max(0, estimate - offset) + reserve:
        raise ValueError(
            "Insufficient free disk space for archive plus reserve; select a larger --datasets-root/--cache-root"
        )
    request_headers = dict(headers)
    if offset:
        request_headers["Range"] = f"bytes={offset}-"
        if state.get("validator"):
            request_headers["If-Range"] = state["validator"]
    try:
        response = open_url(url, request_headers)
    except urllib.error.HTTPError as error:
        if error.code == 416:
            response = open_url(url, headers)
            offset = 0
        else:
            raise ValueError(
                f"Download denied/unavailable (HTTP {error.code}); check credentials or use --archive"
            ) from None
    with response:
        if "text/html" in response.headers.get("Content-Type", "").lower():
            raise ValueError(
                "Provider returned a login/confirmation page, not an archive; use an authorized direct URL or --archive"
            )
        if response.status == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
            if not match or int(match[1]) != offset:
                raise ValueError("Invalid HTTP range response; refusing to concatenate unrelated content")
        else:
            offset = 0
        length = int(response.headers.get("Content-Length", 0))
        if length and shutil.disk_usage(target.parent).free < length + reserve:
            raise ValueError("Insufficient disk space for the remaining download")
        validator = response.headers.get("ETag") or response.headers.get("Last-Modified")
        write_json(state_path, {"url_hash": identity, "validator": validator})
        received = 0
        with partial.open("ab" if offset else "wb") as output:
            while chunk := response.read(1024 * 1024):
                if shutil.disk_usage(target.parent).free < len(chunk) + reserve:
                    raise ValueError("Disk reserve reached; partial download retained for resume")
                output.write(chunk)
                received += len(chunk)
        if length and received != length:
            raise ValueError("Download interrupted; partial data retained for resume")
    actual = file_hash(partial)
    if expected and actual != expected:
        partial.unlink()
        raise ValueError("Archive SHA-256 mismatch; incomplete/corrupt download discarded")
    partial.replace(target)
    receipt = {"sha256": actual, "bytes": target.stat().st_size, "cached": False}
    write_json(receipt_path, receipt)
    return receipt


def archive_path(name: str) -> str:
    """Reject traversal, Windows drives/ADS, links and platform-specific escapes."""
    name = name.replace("\\", "/")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or ":" in name or "\x00" in name:
        raise ValueError("Unsafe path inside archive")
    reserved = {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}
    if any(
        part.rstrip(". ") != part or part.split(".")[0].upper() in reserved or part.endswith(".safesight-part")
        for part in path.parts
    ):
        raise ValueError("Archive filename is not portable")
    if path.as_posix() in (".extracting.json", ".extracted.json"):
        raise ValueError("Archive conflicts with preparation metadata")
    return path.as_posix()


def extract(archive: Path, destination: Path, reserve: int, maximum: int) -> None:
    """Safely extract ZIP/TAR without executing dataset-supplied code."""
    digest = file_hash(archive)
    if destination.exists():
        if (destination / ".extracted.json").is_file() and json.loads(
            (destination / ".extracted.json").read_text()
        ).get("archive_sha256") == digest:
            return
        if (
            not (destination / ".extracting.json").is_file()
            or json.loads((destination / ".extracting.json").read_text()).get("archive_sha256") != digest
        ):
            raise ValueError("Existing extraction is preserved; inspect it or choose a new dataset root")
    if zipfile.is_zipfile(archive):
        handle = zipfile.ZipFile(archive)
        entries = [(i.filename, i.file_size, i.is_dir(), i) for i in handle.infolist()]
        for _, _, _, info in entries:
            if stat.S_ISLNK(info.external_attr >> 16):
                handle.close()
                raise ValueError("Archive symlinks are not allowed")
        reader = handle.open
    elif tarfile.is_tarfile(archive):
        handle = tarfile.open(archive)
        entries = [(i.name, i.size, i.isdir(), i) for i in handle.getmembers()]
        if any(not (i.isfile() or i.isdir()) for _, _, _, i in entries):
            handle.close()
            raise ValueError("Archive links/devices are not allowed")
        reader = handle.extractfile
    else:
        raise ValueError("Expected ZIP or TAR archive; HTML/login pages and RAR need an authorized ZIP/TAR export")
    try:
        total = sum(size for _, size, _, _ in entries)
        seen = set()
        for name, _, _, _ in entries:
            safe = archive_path(name).casefold()
            if safe in seen:
                raise ValueError("Duplicate/case-colliding archive paths are not portable")
            seen.add(safe)
        destination.parent.mkdir(parents=True, exist_ok=True)
        remaining = sum(
            size
            for name, size, is_directory, _ in entries
            if not is_directory and not within(destination, archive_path(name)).exists()
        )
        if total > maximum or shutil.disk_usage(destination.parent).free < remaining + reserve:
            raise ValueError("Extraction exceeds available disk space or configured size limit")
        destination.mkdir(exist_ok=True)
        write_json(destination / ".extracting.json", {"archive_sha256": digest})
        for name, _, is_directory, info in entries:
            output = within(destination, archive_path(name))
            if is_directory:
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                if output.exists():
                    hasher = hashlib.sha256()
                    with reader(info) as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            hasher.update(chunk)
                    if file_hash(output) != hasher.hexdigest():
                        raise ValueError("Extracted source file was modified; preserving it instead of overwriting")
                    continue
                temporary = output.with_name(output.name + ".safesight-part")
                with reader(info) as source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target, 1024 * 1024)
                temporary.replace(output)
        write_json(destination / ".extracted.json", {"archive_sha256": digest, "unpacked_bytes": total})
        (destination / ".extracting.json").unlink(missing_ok=True)
    finally:
        handle.close()


def install_native(extracted: Path, target: Path, slug: str) -> dict | None:
    """Validate complete SafeSight bundles before installing; preserve existing files."""
    candidates = [p.parent for p in extracted.rglob("manifest.jsonl") if p.parent.name == slug]
    if (extracted / "manifest.jsonl").is_file():
        candidates.append(extracted)
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("More than one native dataset found; select a single-use-case bundle")
    from training.common.datasets import validate

    source = candidates[0]
    from training.common.splitting import materialize_splits

    result = validate(materialize_splits(source, slug), slug, qualification=False)
    if not result.valid:
        return {"status": "NEEDS_ANNOTATIONS", "errors": result.errors, "warnings": result.warnings}
    files = [p for p in source.rglob("*") if p.is_file() and p.name not in ("README.md", ".extracted.json")]
    for path in files:
        output = within(target, path.relative_to(source))
        if output.exists() and file_hash(output) != file_hash(path):
            raise ValueError("Existing dataset content differs; refusing to overwrite it")
    required = sum(p.stat().st_size for p in files if not within(target, p.relative_to(source)).exists())
    if shutil.disk_usage(target).free < required + 1024**3:
        raise ValueError("Insufficient space to install the validated bundle")
    # Manifest is published last, so an interrupted copy cannot masquerade as ready.
    for path in sorted(files, key=lambda p: p.name == "manifest.jsonl"):
        output = within(target, path.relative_to(source))
        if not output.exists():
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
    installed = validate(materialize_splits(target, slug), slug, qualification=False)
    return {
        "status": "READY" if installed.valid else "NEEDS_ANNOTATIONS",
        "errors": installed.errors,
        "warnings": installed.warnings,
        "dataset_hash": installed.dataset_hash,
    }


def inventory(root: Path, slug: str) -> dict:
    """Inspect export metadata without guessing labels from image contents."""
    images, labels, xml = 0, 0, 0
    declared = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            images += 1
        if path.suffix.lower() == ".txt":
            labels += 1
        if path.suffix.lower() == ".xml":
            xml += 1
        if path.name in ("data.yaml", "data.yml"):
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(content, dict):
                names = content.get("names", [])
                declared.update(str(v) for v in (names.values() if isinstance(names, dict) else names))
    normalized = {name.casefold() for name in declared}
    return {
        "image_files": images,
        "text_annotation_candidates": labels,
        "xml_annotation_candidates": xml,
        "declared_yolo_classes": sorted(declared),
        "required_classes_not_declared": [name for name in CLASSES[slug] if name.casefold() not in normalized],
        "note": "Counts/metadata are an inventory, not proof of complete labels, correct scene splits or event ground truth.",
    }


def prepare(
    source: dict,
    slug: str,
    datasets_root: Path,
    cache_root: Path,
    reserve: int,
    maximum: int,
    local_archive: Path | None = None,
) -> dict:
    """Acquire source data into its task folder and report exact training readiness."""
    target = within(datasets_root, slug)
    target.mkdir(parents=True, exist_ok=True)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", source["id"]):
        raise ValueError("Source id must be a portable directory identifier")
    if local_archive is None and (target / "manifest.jsonl").is_file():
        from training.common.datasets import validate

        from training.common.splitting import materialize_splits

        existing = validate(materialize_splits(target, slug), slug, qualification=False)
        if existing.valid:
            return {
                "slug": slug,
                "status": "READY",
                "source_origin": "Existing validated dataset; no downloads or changes",
                "dataset_hash": existing.dataset_hash,
                "errors": [],
                "warnings": existing.warnings,
                "cached": True,
            }
    metadata = target / "preparation.json"
    if metadata.exists() and json.loads(metadata.read_text()).get("tool") != "SafeSight-dataset-preparation":
        raise ValueError("Existing preparation.json is not owned by this tool and has been preserved")
    cache = within(cache_root, slug)
    expected = source.get("sha256")
    if local_archive is not None:
        archive = local_archive.resolve()
        if not archive.is_file():
            raise ValueError("Local archive does not exist")
        receipt = {"sha256": file_hash(archive), "bytes": archive.stat().st_size, "local": True}
    else:
        private_override = os.getenv(source.get("url_env", ""))
        identity = hashlib.sha256(
            json.dumps(
                {
                    "source": source,
                    "override_sha256": hashlib.sha256(private_override.encode()).hexdigest()
                    if private_override
                    else None,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()[:12]
        archive = cache / f"{source['id']}-{identity}" / "source.archive"
        if archive.exists():
            # A verified cached export does not need fresh provider credentials.
            url, headers, override = source["publisher"], {}, bool(private_override)
        else:
            url, headers, override = source_url(source)
        receipt = download(
            url,
            archive,
            headers,
            None if override else expected,
            reserve,
            int(source["estimated_archive_gb"] * 1024**3),
        )
        if not zipfile.is_zipfile(archive) and not tarfile.is_tarfile(archive):
            if not receipt.get("cached"):
                archive.unlink()
                archive.with_suffix(".receipt.json").unlink(missing_ok=True)
            raise ValueError("Provider did not return ZIP/TAR data; check account access or supply --archive")
    extracted = target / "_sources" / f"{source['id']}-{receipt['sha256'][:12]}"
    extract(archive, extracted, reserve, maximum)
    result = {
        "tool": "SafeSight-dataset-preparation",
        "schema_version": 1,
        "slug": slug,
        "source_id": source["id"],
        "publisher": source["publisher"],
        "license": source["license"],
        "archive": receipt,
        "extracted": str(extracted),
        "inventory": inventory(extracted, slug),
        "status": "DOWNLOADED_NEEDS_ANNOTATIONS",
        "next_steps": source["annotation_gaps"],
    }
    if local_archive is not None:
        result["source_origin"] = "User-supplied archive; verify origin/license against its included source records"
    installed = install_native(extracted, target, slug)
    if installed:
        result.update(installed)
        if result["status"] == "READY":
            result["next_steps"] = []
    write_json(target / "preparation.json", result)
    return result
