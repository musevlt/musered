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
database and the state of the reduction. See :doc:`inspect` for more details.

Running recipes
---------------

Configuration
^^^^^^^^^^^^^

The parameters for each recipe can be specified in the ``recipes`` block in the
settings file. By default this is not needed as the default parameters from the
DRS are used, and MuseRed finds automatically the calibration frames. The
``common`` block can be used to set parameters for all recipes (for instance for
the temporary directory), and the example below shows how to set
``--saveimages=true`` for the ``muse_wavecal`` recipe:

.. literalinclude:: _static/settings.yml
   :start-at: recipes:
   :end-at: saveimages

By default the parameters for a recipe must be set in a block with the recipe
name, but this can be specified with ``--params``.

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

Running ``muse_scibasic`` is straightforward and can be done on all exposures
with::

    $ musered process_exp --scibasic

One can also give an exposure name to process a specific exposure.

standard
^^^^^^^^

Reduces a standard exposure including both the ``muse_scibasic`` and the
``muse_standard`` steps::

    $ musered process_exp --standard

scipost
^^^^^^^

``muse_scipost`` takes a lot of options and sometimes needs to be run multiple
times with different sets of options. The command to run is::

    $ musered process_exp --scipost

To run it with different options, for instance to produce more quickly images
for the offset computation, the parameters block can be specified with
``--params``::

    $ musered process_exp --scipost --params muse_scipost_rec

This would use a ``muse_scipost_rec`` block in the settings file, where the
Raman correction and the sky subtraction are deactivated:

.. literalinclude:: _static/settings.yml
   :start-at: muse_scipost_rec
   :end-at: skymethod

Computing offsets
^^^^^^^^^^^^^^^^^

To compute the offsets between exposures, with the ``muse_exp_align`` recipe::

    $ musered compute_offsets IC4406

A method can be specified with ``--method`` but currently only the ``drs``
method is implemented. This name must be used later to set the ``OFFSET_LIST``
frame in the parameters.

Creating recentered cubes
^^^^^^^^^^^^^^^^^^^^^^^^^

It can be useful to create individual cubes for each exposures, to verify the
quality of each cube, measure the FWHM, or for doing some post-processing on the
cubes. Now that we have computed offsets, we can use the ``OFFSET_LIST`` frame
in the parameters, with also sky subtraction and saving additional outputs:

.. literalinclude:: _static/settings.yml
   :start-at: muse_scipost
   :end-at: save

And run with::

    $ musered process_exp --scipost

Combining exposures
^^^^^^^^^^^^^^^^^^^

To combine the exposures, with the ``muse_exp_combine`` recipe::

    $ musered exp_combine IC4406

And with the parameters with the ``OFFSET_LIST`` frame:

.. code-block:: yaml

    muse_exp_combine:
        OFFSET_LIST: drs

Setting custom frames
^^^^^^^^^^^^^^^^^^^^^

It may happen that one need to set a custom ``OFFSET_LIST`` or ``OUTPUT_WCS``.
This can be done by setting directly the file name. For example here the offsets
computed by the DRS are not good, so we could compute manually better offsets
and use something like:

.. code-block:: yaml

    muse_exp_combine:
        OFFSET_LIST: '{workdir}/reduced/{version}/exp_align/OFFSET_LIST_new.fits'

