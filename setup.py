from setuptools import setup, find_packages

# Read version from version.py
# __version__ = None
# with open('mydrs/version.py') as f:
#     exec(f.read())

setup(
    name='musered',
    version='0.1dev',
    packages=find_packages(),
    zip_safe=False,
    install_requires=['numpy', 'matplotlib', 'astropy', 'python-cpl',
                      'mpdaf', 'sqlalchemy', 'dataset', 'PyYAML'],
    # entry_points={
    #     'console_scripts': [
    #         'create_db = mydrs.reduction.create_db:main',
    #     ]
    # },
)
