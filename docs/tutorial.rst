How to reduce your data
=======================

See also the :doc:`cli` and the :doc:`api` documentation.

To show a complete reduction example, and describe all the steps, we will go
through the reduction of the `planetary nebula IC4406
<https://www.eso.org/public/images/eso1724a/>`_, which was observed during the
`Wide Field Mode AO Commissioning
<http://eso.org/sci/publications/announcements/sciann17116.html>`_.

.. contents::


Settings
--------

All the configuration is stored in a YAML file, by default ``settings.yml`` in
the current directory. This file contains all the settings about directories,
global options, parameters for the *musered* commands, and for the reduction
recipes.

See also the :doc:`settings` example.

The first part of the file contains general variables, like the corking
directory; the raw, reduced and calibration paths; version numbers; and logging
level:

.. literalinclude:: _static/settings.yml
   :start-at: workdir
   :end-at: loglevel

When the file is read, the top-level keys are substituted, which allows to reuse
keys, for example with path definitions: ``'{workdir}/reduced/{version}'`` will
be replaced by ``'./reduced/0.1'``.


Dataset definition
------------------

The first important step in the organisation of the reduction is the concept of
*dataset*. This defines a set of files that are retrieved and reduced together.
For instance to define a `IC4406` dataset:

.. literalinclude:: _static/settings.yml
   :start-at: datasets
   :end-at: obs_targ_name

See the next paragraph for the meaning of *archive_filter*.


Data retrieval
--------------

Retrieving a dataset is done with `Astroquery
<https://astroquery.readthedocs.io/en/latest/eso/eso.html>`__. To find all the
possible query options for Muse, to use in the *archive_filter* for your
dataset, use this::

    $ musered retrieve_data --help-query

In the IC4406 example we just use the target name, but it may be needed to
specify also dates, instrument mode, etc.

Once a dataset is defined in the settings file, its data files can be retrieved
with this command::

    $ musered retrieve_data IC4406

Note that this also retrieves the calibration files associated to the data.  All
files are placed in a unique directory (defined by the ``raw_path`` setting),
which allows to avoid duplicating files for different datasets. When executing
again this command, Astroquery checks which OBJECT files have already been
downloaded, and makes the query only with the missing ones. Then another check
is done for the calibration files, so only the missing files are retrieved.

.. warning::
    One drawback of this deduplication is that, if an OBJECT file was retrieved
    but the process was interrupted before all its calibrations were retrieved,
    at the next execution the missing calibrations will not be downloaded.


Ingesting metadata in a database
--------------------------------

Then the next step is to ingest FITS keywords in a SQLite database. This step
is triggered automatically by the ``retrieve_data`` command, but it can also be
run manually if needed, with::

    $ musered update_db


Inspecting the database
-----------------------

The `musered info` command provides several ways to inspect the content of the
database and the state of the reduction. We give a few examples below, 


::

    $ musered info --datasets --nights --exps
    INFO Musered version 0.1.dev73
    Datasets:
    - IC4406
    Nights:
    - 2017-04-23
    - 2017-06-13
    - 2017-06-15
    - 2017-06-17
    - 2017-06-18
    - 2017-06-19
    - 2017-10-26
    Exposures:
    - IC4406
      - 2017-06-16T01:34:56.867
      - 2017-06-16T01:43:32.868
      - 2017-06-16T01:46:25.866
      - 2017-06-16T01:49:19.866
      - 2017-06-16T01:40:40.868
      - 2017-06-16T01:37:47.867


Running recipes
---------------

Calibrations
^^^^^^^^^^^^

Processing the calibrations is done with the ``musered process_calib`` command.
The different steps can be run for a given night or for all nights, and the
``--skip`` parameter allows to avoid reprocessing the nights that have already
been processed.

The currently available steps and the related command-line options are:

- ``muse_bias``: ``--bias``
- ``muse_dark``: ``--dark``
- ``muse_flat``: ``--flat``
- ``muse_wavecal``: ``--wavecal``
- ``muse_lsf``: ``--lsf``
- ``muse_twilight``: ``--twilight``

By default, when no option is given, all steps except ``muse_dark`` are run.
The ``MASTER_DARK`` frames are also excluded from the inputs of the other
recipes.

For instance, to run the ``muse_bias`` recipe for a given night::

    $ musered process_calib --bias 2017-06-15

Or to run ``muse_flat`` recipe for all nights, skipping already processed
nights::

    $ musered process_calib --flat --skip


scibasic
^^^^^^^^

::

    $ musered process_exp --scibasic


Standard
^^^^^^^^

Reduces a standard exposure including both the ``muse_scibasic`` and the
``muse_standard`` steps::

    $ musered process_exp --standard
