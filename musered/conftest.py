def pytest_ignore_collect(path, config):
    if path.basename == '_githash.py':
        return True
