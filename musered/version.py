import os

__version__ = '0.2'
__description__ = 'Muse data reduction, quick and easy'

try:
    CURDIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    CURDIR = '.'


def _update_git_version():
    from contextlib import suppress
    from subprocess import check_output
    command_number = 'git -C {} rev-list --count HEAD'.format(CURDIR).split()
    with suppress(Exception):
        return check_output(command_number).decode('ascii').strip()


try:
    if '.dev' in __version__:
        commit_number = _update_git_version()
        if commit_number:
            __version__ += commit_number
        else:
            from ._githash import __dev_value__
            __version__ += __dev_value__
except Exception:
    pass
