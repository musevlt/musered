Installation
============

First, clone the repository and install the package::

    pip install .

It is also possible to install with a few additional dependencies, for the
command-line interface::

    pip install .\[all\]

The following dependencies are required:

- astroquery>=0.3.9, to retrieve data from the ESO archive
- click, command-line interface
- dataset, database access
- joblib, multiprocessing
- mpdaf,
- python-cpl, Python interface for the MUSE DRS
- PyYAML, for the settings file
- tqdm, progress bars

.. _astroquery: https://astroquery.readthedocs.io/en/latest/
