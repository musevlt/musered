MUSE Data Reduction
===================

.. note::
   This is a work in progress !!

The aim of this project is to provide tools to reduce more easily MUSE
datasets, and for doing an "advanced" data reduction, similar to the HUDF one.

.. warning::
   Currently we need a development version of *astroquery*, it can be installed
   with::

     pip install --pre "astroquery>0.3.8"

First, clone the repository and install the package::

    pip install .

Settings
--------

All the configuration must be done in a YAML file, by default ``settings.yml``
in the current directory. This file contains all the settings about
directories, global options, parameters for the *musered* commands, and for the
reduction recipes.

One important thing in the organisation of the reduction is the concept of
*dataset*. This defines a set of files that are retrieved and reduced together.
For instance to define a `IC4406` dataset (observed during WFM-AO
commissioning)::

    datasets:
      IC4406:
        archive_filter:
          # "column_filters" passed to astroquery.Eso.query_instrument
          obs_targ_name: IC4406

See below for the meaning of *archive_filter*.

About the command-line interface
--------------------------------

Every step can be run with sub-commands of the ``musered`` command. It is also
possible to setup completion (TODO: explain), or to run the subcommands in
a REPL with ``musered repl``.

Data retrieval
--------------

Retrieving a dataset is done with `Astroquery
<https://astroquery.readthedocs.io/en/latest/eso/eso.html>`_. To find all the
possible query options for Muse, to use in the *archive_filter* for your
dataset, use this::

    from astroquery.eso import Eso
    eso = Eso()
    eso.query_instrument('muse', help=True)

Once a dataset is defined in the settings file, its data files can be retrieved
with this command::

    musered retrieve_data IC4406

Note that this also retrieve the calibration files associated to the data. And
all files are placed in a unique directory, which allows to avoid duplicating
files for different datasets.

Ingesting metadata in a database
--------------------------------

Then the next step is to ingest FITS keywords in a SQLite database. This step
is triggered automatically by the ``retrieve_data`` command, but it can also be
run manually if needed, with::

    musered update_db

Running recipes
---------------

Calibrations
~~~~~~~~~~~~

To run ``muse_bias`` recipe for a given night::

    musered process_calib --bias 2017-06-15

To run ``muse_flat`` recipe for all nights, skipping already processed nights::

    musered process_calib --flat --skip
