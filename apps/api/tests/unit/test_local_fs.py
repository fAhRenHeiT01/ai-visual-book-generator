"""Filesystem storage obeys the injected byte port and confines keys to its root."""

from importlib import import_module
from io import BytesIO
from pathlib import Path
import sys

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "apps/api/src"))


def storage_class():
    assert (ROOT / "apps/api/src/bookgen/adapters/storage/local_fs.py").is_file(), "LocalFSStorage must be implemented"
    return import_module("bookgen.adapters.storage.local_fs").LocalFSStorage


def test_storage_round_trip_and_existing_port(tmp_path):
    from bookgen.adapters.ports import StorageAdapter

    storage = storage_class()(tmp_path / "uploads")
    assert isinstance(storage, StorageAdapter)
    key = storage.put("originals/data.bin", b"\x00original bytes\xff")
    assert storage.get(key) == b"\x00original bytes\xff"
    assert storage.get("originals/data.bin") == b"\x00original bytes\xff"
    storage.put("originals/data.bin", b"replacement")
    assert storage.get(key) == b"replacement"


@pytest.mark.parametrize("size", [(1600, 800), (800, 1600)])
def test_original_and_separately_decodable_thumbnail(tmp_path, size):
    storage = storage_class()(tmp_path)
    from bookgen.domain.profiler import ImageInput, profile_content

    output = BytesIO()
    Image.new("RGB", size).save(output, format="PNG")
    data = output.getvalue()
    result = profile_content("", [ImageInput(data)], storage=storage)
    asset, = result.assets
    assert storage.get(asset.storage_key) == data
    with Image.open(BytesIO(storage.get(asset.storage_key))) as original:
        assert original.size == size
    with Image.open(BytesIO(storage.get(asset.thumbnail_key))) as thumbnail:
        thumbnail.load()
        assert max(thumbnail.size) <= 768
        assert thumbnail.width / thumbnail.height == size[0] / size[1]


@pytest.mark.parametrize("key", ["../outside.bin", "nested/../../outside.bin", "", "."])
def test_keys_cannot_escape_root_or_refer_to_root(tmp_path, key):
    storage = storage_class()(tmp_path / "uploads")
    with pytest.raises(ValueError, match="storage root"):
        storage.put(key, b"no")
    with pytest.raises(ValueError, match="storage root"):
        storage.get(key)
    assert not (tmp_path / "outside.bin").exists()


def test_absolute_outside_path_is_rejected(tmp_path):
    storage = storage_class()(tmp_path / "uploads")
    with pytest.raises(ValueError, match="storage root"):
        storage.put(str(tmp_path / "outside.bin"), b"no")


def test_missing_object_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        storage_class()(tmp_path).get("absent.bin")


def test_delete_is_confined_and_missing_keys_are_safe_to_retry(tmp_path):
    storage = storage_class()(tmp_path / 'uploads')
    key = storage.put('owned/original', b'owned')
    other = storage.put('other/original', b'other')
    storage.delete(key)
    storage.delete(key)
    assert not Path(key).exists()
    assert storage.get(other) == b'other'
    for invalid in ('../outside', '', '.'):
        with pytest.raises(ValueError, match='storage root'):
            storage.delete(invalid)
