"""Tests for model_store: no network needed (file:// URLs)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from model_store import ModelStoreError, ensure_model, sha256_of  # noqa: E402


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "remote" / "model.onnx"
    src.parent.mkdir()
    src.write_bytes(b"pretend this is a model" * 1000)
    return src, src.as_uri(), sha256_of(src)


def test_downloads_and_verifies(tmp_path, source):
    _, url, digest = source
    dest = tmp_path / "models" / "model.onnx"
    assert ensure_model(dest, url, digest) == digest
    assert dest.exists()
    assert not list(dest.parent.glob("*.part"))


def test_wrong_checksum_is_rejected_and_nothing_is_saved(tmp_path, source):
    _, url, _ = source
    dest = tmp_path / "models" / "model.onnx"
    with pytest.raises(ModelStoreError, match="Checksum mismatch"):
        ensure_model(dest, url, "0" * 64)
    assert not dest.exists()
    assert not list(dest.parent.glob("*.part"))


def test_checksum_is_required_with_url(tmp_path, source):
    _, url, _ = source
    with pytest.raises(ModelStoreError, match="MODEL_SHA256 is required"):
        ensure_model(tmp_path / "m.onnx", url, None)


def test_existing_matching_file_is_not_downloaded(tmp_path, source):
    src, _, digest = source
    dest = tmp_path / "model.onnx"
    dest.write_bytes(src.read_bytes())
    # URL is bogus: if it were used, this would fail
    assert ensure_model(dest, "file:///does/not/exist", digest) == digest


def test_stale_file_is_replaced_by_new_version(tmp_path, source):
    _, url, digest = source
    dest = tmp_path / "model.onnx"
    dest.write_bytes(b"old model")
    assert ensure_model(dest, url, digest) == digest
    assert sha256_of(dest) == digest


def test_stale_file_without_url_is_an_error(tmp_path):
    dest = tmp_path / "model.onnx"
    dest.write_bytes(b"old model")
    with pytest.raises(ModelStoreError, match="does not match"):
        ensure_model(dest, None, "0" * 64)


def test_existing_file_without_settings_is_used_as_is(tmp_path):
    dest = tmp_path / "model.onnx"
    dest.write_bytes(b"local model")
    assert ensure_model(dest) == sha256_of(dest)


def test_missing_file_and_no_url_returns_none(tmp_path):
    assert ensure_model(tmp_path / "model.onnx") is None


def test_bad_url_error_does_not_leak_the_token(tmp_path):
    bad = (tmp_path / "nope.onnx").as_uri() + "?sig=SECRETTOKEN"
    with pytest.raises(ModelStoreError) as e:
        ensure_model(tmp_path / "model.onnx", bad, "a" * 64)
    assert "SECRETTOKEN" not in str(e.value)


def test_plain_http_to_a_remote_host_is_refused(tmp_path):
    with pytest.raises(ModelStoreError, match="https"):
        ensure_model(tmp_path / "m.onnx", "http://example.com/m.onnx", "a" * 64)
