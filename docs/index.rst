Welcome to MuseRed's documentation!
===================================

.. note::
   This is a work in progress !!

The aim of this project is to provide tools to reduce more easily MUSE
datasets, and for doing an "advanced" data reduction, similar to the HUDF one.
It handles the retrieval of the data from the ESO archive, and stores all the
metadata extracted from FITS headers in a database. Then it allows to run the
recipes from the MUSE pipeline on the calibrations and science exposures.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   reduction
   settings
   cli
   api

Installation
============

.. warning::
   Currently we need a development version of `astroquery`_, it can be
   installed with::

     pip install --pre "astroquery>0.3.8"

First, clone the repository and install the package::

    pip install .

About the command-line interface
================================

Every step can be run with sub-commands of the ``musered`` command. By default
it supposes that the command is run in the directory containing the settings
file, named ``settings.yml``. Otherwise this settings file can be specified
with ``--settings``.

See also the :doc:`cli` documentation.

It is also possible to setup completion (using `click-completion`_, TODO:
explain), or to run the subcommands in a REPL with ``musered repl`` (after
installing `click-repl`_).

Python API
==========

MuseRed can also be used as a Python object, with the `~musered.MuseRed` class
which provides all the methods corresponding to the command-line sub-commands:

.. code-block:: python

    >>> from musered import MuseRed
    >>> mr = MuseRed(settings_file='settings.yml')
    >>> mr.list_datasets()
    - IC4406
    >>> mr.list_nights()
    - 2017-04-23
    - 2017-06-13
    - 2017-06-15
    - 2017-06-17
    - 2017-06-18
    - 2017-06-19
    - 2017-10-26


.. _astroquery: https://astroquery.readthedocs.io/en/latest/
.. _click-completion: https://github.com/click-contrib/click-completion
.. _click-repl: https://github.com/click-contrib/click-repl
