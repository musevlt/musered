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
    cwd = os.getcwd()
    os.chdir(TESTDIR)
    yield MuseRed()
    os.chdir(cwd)
