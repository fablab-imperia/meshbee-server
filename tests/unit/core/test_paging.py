"""Tests for the paging value objects (meshbee_core/paging.py)."""

import dataclasses

import pytest

from meshbee_core.paging import EVERYTHING, Page, Paging


def test_the_default_window_is_the_whole_uncounted_list():
    """
    A caller that never pages must get what it got before paging existed.

    Every repository list function defaults to EVERYTHING, so a non-empty
    default here would silently truncate lists, and `total` on by default would
    add a COUNT query to every list nobody asked to count.
    """
    assert EVERYTHING == Paging()
    assert EVERYTHING.limit is None
    assert EVERYTHING.offset == 0
    assert EVERYTHING.total is False


def test_the_shared_default_window_cannot_be_changed():
    """
    EVERYTHING is a default argument shared by every list call.

    If it were mutable, one caller narrowing it would narrow every later call
    in the process.
    """
    with pytest.raises(dataclasses.FrozenInstanceError):
        EVERYTHING.limit = 10


def test_a_page_is_uncounted_unless_a_total_is_given():
    """None, not 0, marks "not counted": 0 is a real total for an empty list."""
    assert Page(items=[]).total is None
    assert Page(items=[], total=0).total == 0
