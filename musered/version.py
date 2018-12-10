import os

__version__ = '0.2.dev'
__description__ = 'Muse data reduction, quick and easy'


def _update_git_version():
    from subprocess import run
    CURDIR = os.path.dirname(os.path.abspath(__file__))
    command_number = 'git -C {} rev-list --count HEAD'.format(CURDIR).split()
    p = run(command_number, capture_output=True)
    if p.returncode == 0:
        return p.stdout.decode('ascii').strip()


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
