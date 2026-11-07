"""Make sure the model file is present: use the local copy, or download it.

Why: model weights are not stored in Git or baked into the Docker image. In a
container/VM the file is fetched at startup from storage (e.g. Azure Blob) and
verified against a SHA256 checksum, so we always know exactly which model runs.

    MODEL_URL     where to download from (a SAS URL is fine; it is a SECRET)
    MODEL_SHA256  expected checksum (required whenever MODEL_URL is set)

Only the standard library is used (no extra packages).
"""
import hashlib
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CHUNK = 1024 * 1024  # 1 MB
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class ModelStoreError(RuntimeError):
    """Download or verification failed."""


def sha256_of(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe(url: str) -> str:
    """URL without query string/credentials, so SAS tokens never reach logs."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.hostname or ''}{p.path}"


def _check_url(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme == "https" or p.scheme == "file":
        return
    if p.scheme == "http" and p.hostname in LOCAL_HOSTS:
        return
    raise ModelStoreError(
        "MODEL_URL must be https (http is allowed only for localhost)"
    )


def _download(url: str, dest: Path, expected: str, timeout: int) -> str:
    _check_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # download next to the target, verify, then atomically move into place
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, suffix=".part")
    tmp = Path(tmp_name)
    try:
        h = hashlib.sha256()
        try:
            # fdopen first so the handle is always closed, even if the download fails
            with os.fdopen(fd, "wb") as out, urllib.request.urlopen(
                url, timeout=timeout
            ) as resp:
                while chunk := resp.read(CHUNK):
                    h.update(chunk)
                    out.write(chunk)
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ModelStoreError(
                f"Could not download model from {_safe(url)}: {type(e).__name__}"
            ) from None
        actual = h.hexdigest()
        if actual != expected:
            raise ModelStoreError(
                f"Checksum mismatch for {_safe(url)}: expected {expected[:12]}…, "
                f"got {actual[:12]}…. File rejected."
            )
        os.replace(tmp, dest)
        return actual
    finally:
        tmp.unlink(missing_ok=True)


def ensure_model(model_path, url=None, sha256=None, timeout=120):
    """Return the SHA256 of the model at model_path, or None if there is none.

    - file exists, no checksum expected      -> use it as is
    - file exists and matches the checksum   -> use it (no download)
    - file exists but differs, URL set       -> replace it (a new model version)
    - file missing, URL set                  -> download and verify
    - file missing, no URL                   -> None (caller reports it)
    """
    model_path = Path(model_path)
    expected = sha256.strip().lower() if sha256 else None

    if url and not expected:
        raise ModelStoreError("MODEL_SHA256 is required when MODEL_URL is set")

    if model_path.exists():
        actual = sha256_of(model_path)
        if not expected or actual == expected:
            return actual
        if not url:
            raise ModelStoreError(
                f"{model_path.name} does not match MODEL_SHA256 and no MODEL_URL is set"
            )
        # stale file (e.g. cached volume with the previous model): fall through

    if not url:
        return None
    return _download(url, model_path, expected, timeout)
