import os
import pytest

from musered import MuseRed

CURDIR = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(CURDIR, '..', 'docs', '_static')


def pytest_ignore_collect(path, config):
    if path.basename == '_githash.py':
        return True


@pytest.fixture
def mr():
    """Fixture to get the MuseRed object."""
    cwd = os.getcwd()
    os.chdir(TESTDIR)
    yield MuseRed()
    os.chdir(cwd)


@pytest.fixture
def mr_memory():
    """Fixture to get the MuseRed object with a fresh in-memory database."""
    cwd = os.getcwd()
    os.chdir(TESTDIR)
    yield MuseRed(settings_kw={'db': ':memory:'})
    os.chdir(cwd)
