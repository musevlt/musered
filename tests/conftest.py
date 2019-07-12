import os
import shutil

import pytest
from musered import MuseRed

CURDIR = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(CURDIR, "..", "docs", "_static")


def pytest_ignore_collect(path, config):
    if path.basename == "_githash.py":
        return True


@pytest.fixture
def mr(tmpdir):
    """Fixture to get the MuseRed object."""
    cwd = os.getcwd()
    tmpdir = str(tmpdir)
    shutil.copy(os.path.join(TESTDIR, "settings.yml"), tmpdir)
    shutil.copy(os.path.join(TESTDIR, "musered.db"), tmpdir)
    os.chdir(tmpdir)
    yield MuseRed()
    os.chdir(cwd)
