Welcome to MuseRed's documentation!
===================================

This project provides tools to help reducing MUSE datasets, including "advanced"
recipes inherited from the HUDF_ data reduction [1710.03002]_. It handles the
retrieval of the data from the ESO archive, and stores all the metadata
extracted from FITS headers in a database (SQLite by default). Then it allows to
run the recipes from the MUSE pipeline on the calibrations and science
exposures.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   tutorial
   advanced
   inspect
   settings
   cli
   api
   changelog


.. _HUDF: http://muse-vlt.eu/science/udf/
.. [1710.03002] https://arxiv.org/abs/1710.03002
