import os
import subprocess
import sys
from setuptools import setup, find_packages

if sys.version_info < (3, 6):
    raise Exception('python 3.6 or newer is required')

# Read version.py
__version__ = None
__description__ = None
with open('musered/version.py') as f:
    exec(f.read())

# If the version is not stable, we can add a git hash to the __version__
if '.dev' in __version__:
    # Find hash for __githash__ and dev number for __version__ (can't use hash
    # as per PEP440)
    command_hash = 'git rev-list --max-count=1 --abbrev-commit HEAD'
    command_number = 'git rev-list --count HEAD'

    try:
        commit_hash = subprocess.check_output(command_hash, shell=True)\
            .decode('ascii').strip()
        commit_number = subprocess.check_output(command_number, shell=True)\
            .decode('ascii').strip()
    except Exception:
        pass
    else:
        # We write the git hash and value so that they gets frozen if installed
        with open(os.path.join('musered', '_githash.py'), 'w') as f:
            f.write("__githash__ = \"{}\"\n".format(commit_hash))
            f.write("__dev_value__ = \"{}\"\n".format(commit_number))

        # We modify __version__ here too for commands such as egg_info
        # __version__ += commit_number

setup(
    name='musered',
    version=__version__,
    description=__description__,
    author='Simon Conseil',
    author_email='simon.conseil@univ-lyon1.fr',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=['mpdaf', 'python-cpl', 'tqdm', 'dataset', 'PyYAML',
                      'click', 'astroquery>0.3.8', 'secretstorage<3.0'],
    extras_require={
        'all': ['click_completion', 'click-repl'],
    },
    entry_points={
        'console_scripts': [
            'musered=musered.__main__:main',
        ]
    },
)
