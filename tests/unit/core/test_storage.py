"""LocalStorage: the directory uploaded files live in (#3)."""

import pytest

from meshbee_core.storage import LocalStorage


def test_a_saved_file_is_read_back_from_its_path(tmp_path):
    storage = LocalStorage(tmp_path)

    storage.save("arnie/7/a.webp", b"bytes")

    assert storage.path("arnie/7/a.webp").read_bytes() == b"bytes"


def test_saving_leaves_no_temporary_file_behind(tmp_path):
    """The write goes through a temporary file that must be renamed, not left over."""
    storage = LocalStorage(tmp_path)

    storage.save("arnie/7/a.webp", b"bytes")

    assert [p.name for p in (tmp_path / "arnie" / "7").iterdir()] == ["a.webp"]


def test_deleting_a_file_that_is_already_gone_is_not_an_error(tmp_path):
    """Cleanup after a commit may race another; neither should fail the request."""
    LocalStorage(tmp_path).delete("arnie/7/missing.webp")


@pytest.mark.parametrize(
    "key", ["../outside.webp", "arnie/../../outside", "/etc/passwd", "", "a\\b"]
)
def test_a_key_cannot_reach_outside_the_directory(tmp_path, key):
    """Keys are built by the services, but a bug there must not become a path traversal."""
    with pytest.raises(ValueError):
        LocalStorage(tmp_path / "root").path(key)


def test_a_missing_directory_is_reported_as_not_writable(tmp_path):
    """What the API warns about at startup when ./storage was never created."""
    assert LocalStorage(tmp_path).is_writable()
    assert not LocalStorage(tmp_path / "missing").is_writable()
