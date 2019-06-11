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

The complete settings file is available :doc:`here <settings>`, we will go
through it in this page.

The first part of the file contains general variables, like the working
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
This also means that *musered* can be used to reduce several datasets at the
same time, which can be handy when they were observed in the same nights and
share the same calibrations.

For instance to define a `IC4406` dataset:

.. literalinclude:: _static/settings.yml
   :start-at: datasets
   :end-at: obs_targ_name

Here the first occurrence of IC4406 defines the dataset name, which will be
used in various Musered commands like for offsets computation or exposures
combination. Then the ``archive_filter`` block defines how the data is
retrieved from the ESO archive, see the next section.


Data retrieval
--------------

Retrieving data is done with `Astroquery
<https://astroquery.readthedocs.io/en/latest/eso/eso.html>`__. To find all the
possible query options for Muse, that can be uses with the ``archive_filter``
setting, use this::

    $ musered retrieve-data --help-query

``archive_filter`` must then contain a list of key/value items, defining
a query on the ESO archive. Each key given by ``--help-query`` corresponds to
an input of the ESO `Raw Data Query Form
<http://archive.eso.org/eso/eso_archive_main.html>`_

For the IC4406 example we just use the target name (``obs_targ_name``), but it
is also possible to specify dates, instrument mode (``ins_mode``), or
a programme ID (``prog_id``).

Once a dataset is defined in the settings file, its data files can be retrieved
with this command::

    $ musered retrieve-data IC4406

Note that this also retrieves the calibration files associated to the data.  All
files are placed in a unique directory (defined by the ``raw_path`` setting),
which allows to avoid duplicating files for different datasets. When executing
again this command, Astroquery checks which OBJECT files have already been
downloaded, and makes the query only with the missing ones. Then another check
is done for the calibration files, so only the missing files are retrieved.

.. warning::
    One drawback of this de-duplication is that, if an OBJECT file was
    retrieved but the process was interrupted before all its calibrations were
    retrieved, at the next execution the missing calibrations will not be
    downloaded.

    Using the ``--force`` option which will force the query to be done with all
    OBJECT files.

``retrieve-data`` offers a few more option, like specifying the start or end
date for the query (``--start``, ``--end``), which can be useful to speed-up
the query, or ``--calib`` to retrieve all the calibration files for a given
night.


Ingesting metadata in a database
--------------------------------

Then the next step is to ingest FITS keywords in a database (SQLite by
default). This step is triggered automatically by the ``retrieve-data``
command, but it can also be run manually if needed, with::

    $ musered update-db

This command can be run each time new data are retrieved, and by default it
will add only the new files that are not yet in the database.

During this step, the ``raw`` table is created or updated with FITS keywords
from all FITS files found in the ``raw_path`` directory. It will also ingest the
weather conditions from the text files downloaded from the ESO archive, in the
``weather_conditions`` table. And if the ``GTO_logs`` setting is filled with
some GTO database from ``muselog``, the ranks and comments from observer teams
are also ingested.


Inspecting the database
-----------------------

The `musered info` command provides several ways to inspect the content of the
database and the state of the reduction. See :doc:`inspect` for more details.

.. _date-selection:

Date selection
--------------

In various places it is needed to specify dates (settings, command-line). For
convenience it is possible to specify ranges of dates (runs), that can be
substituted in the settings file, or used in commands.

For instance this defines a ``GTO27`` run, with a tag that can be used later in
the settings (``&GTO17``):

.. literalinclude:: _static/settings.yml
   :start-at: runs
   :end-at: end_date

Recipe Configuration
--------------------

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
name, but this can also be specified with ``--params`` which can be used to run
the same recipe with different sets of paramaters.  The paramater names and
values are the same as the DRS ones.

Frames
------

Static calibrations
^^^^^^^^^^^^^^^^^^^

The static calibrations (badpix table, astrometry, geometry table, etc.) are
found in the ``muse_calib_path`` directory. It is possible to specify a range
of dates for which each file is valid. Here we use the runs defined above
(:ref:`date-selection`), with the ``*GTO17`` notation that makes
a substitution which the dictionary defined above:

.. literalinclude:: _static/settings.yml
   :start-at: Static calibrations
   :end-at: geometry_table_wfm_gto19

Frames associations
^^^^^^^^^^^^^^^^^^^

By default MuseRed search for calibration frames in the database, and use
automatically the frames for the current night (for ``MASTER_BIAS``,
``MASTER_FLAT``), or for the previous or following nights (for ``STD_TELLURIC``,
``STD_RESPONSE``, ``TWILIGHT_CUBE``).  ``MASTER_DARK`` and ``NONLINEARITY_GAIN``
are excluded by default.

The frames that are used by default can be configured with the ``frames`` dict:

.. code-block:: yaml

   muse_wavecal:
      frames:
         exclude: MASTER_DARK
         include: [MASTER_FLAT]

It is also possible to specify the path or the files that must be used:

.. code-block:: yaml

   muse_wavecal:
      frames:
         MASTER_BIAS: /path/to/MASTER_BIAS/
         MASTER_FLAT: /path/to/MASTER_FLAT/MASTER_FLAT*.fits

It is also possible to specify frames with a given range of validity, as
explained above:

.. code-block:: yaml

   muse_wavecal:
      frames:
         STD_RESPONSE:
            "{workdir}/path/to/STD_RESPONSE_GTO17.fits": *GTO17
            "{workdir}/path/to/STD_RESPONSE_GTO19.fits": *GTO19

The number of nights before and after the current one, for which frames are
searched for, can be specified with ``offsets``:

.. code-block:: yaml

   muse_scipost:
      frames:
         offsets:
            STD_TELLURIC: 5
            STD_RESPONSE: 5
            TWILIGHT_CUBE: 3

Frames exclusion
^^^^^^^^^^^^^^^^

It is possible to exclude globally some files or sequences of calibration,
which is useful when a sequence is of bad quality or incomplete, or sometimes
just because the ESO associations which lead to the retrieval of calibrations
that are not useful.

.. code-block:: yaml

   frames:
      exclude:
         raw:
            # This block matches any raw files, for instance for nights
            # with useless calibrations:
            - night: ["2018-08-11", "2018-08-18"]
         WAVE:
            # Block for a given DPR.TYPE == WAVE, then matching files for a
            # bad sequence identified by its TPL.START date:
            - TPL_START: "2018-08-15T19:20:20"

Setting custom frames
^^^^^^^^^^^^^^^^^^^^^

It may happen that one need to set a custom ``OFFSET_LIST`` or ``OUTPUT_WCS``.
This can be done by setting directly the file name. For example here the offsets
computed by the DRS are not good, so we could compute manually better offsets
and use something like this:

.. code-block:: yaml

    muse_exp_combine:
      frames:
        OFFSET_LIST: '{workdir}/reduced/{version}/exp_align/OFFSET_LIST_new.fits'


Running DRS recipes
-------------------

Calibrations
^^^^^^^^^^^^

Processing the calibrations is done with the ``musered process-calib`` command.
The different steps can be run for a given night or for all nights. By default
the calibrations that have already been processed are not reprocessed, but this
can be forced with the ``--force`` flag.

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

For instance, to run the ``muse_bias`` recipe for a given day::

    $ musered process-calib --bias "2017-06-16*"

Or to run ``muse_flat`` recipe for all nights::

    $ musered process-calib --flat

scibasic
^^^^^^^^

Running ``muse_scibasic`` is straightforward and can be done on all exposures
with::

    $ musered process-exp --scibasic

One can also give an exposure name to process a specific exposure.

standard
^^^^^^^^

Reduces a standard exposure including both the ``muse_scibasic`` and the
``muse_standard`` steps::

    $ musered process-exp --standard

scipost
^^^^^^^

``muse_scipost`` takes a lot of options and sometimes needs to be run multiple
times with different sets of options. The command to run is::

    $ musered process-exp --scipost

To run it with different options, for instance to produce more quickly images
for the offset computation, the parameters block can be specified with
``--params``::

    $ musered process-exp --scipost --params muse_scipost_rec

This would use a ``muse_scipost_rec`` block in the settings file, where the
Raman correction and the sky subtraction are deactivated:

.. literalinclude:: _static/settings.yml
   :start-at: # Example of a special version of scipost
   :end-at: save

Computing offsets
-----------------

The ``exp-align`` command provides ways to compute the offsets between
exposures, either with the DRS or with Imphot. The default is to use the DRS
with the ``muse_exp_align`` recipe::

    $ musered exp-align IC4406

The configuration for this recipe needs a ``from_recipe`` item, which specifies
the recipe from which images are used:

.. literalinclude:: _static/settings.yml
   :start-at: muse_exp_align:
   :end-at: filt

This produces an ``OFFSET_LIST`` file, which is stored by default with the name
``OFFSET_LIST_drs`` (in the ``name`` column).  The ``--name`` option can be used
to give another name  to identify the ``OFFSET_LIST`` frame.

It is also possible to use Imphot with ``--method=imphot`` and the following
settings. By default the file will be stored with the ``OFFSET_LIST_imphot``
name.

.. literalinclude:: _static/settings.yml
   :start-at: imphot:
   :end-at: hst_resample_each

The ``OFFSET_LIST`` file can also be computed by other means, when the DRS and
Imphot method does not work. This is case for our example field IC4406, for
which the correct offsets were computed manually and put in the file
``{workdir}/OFFSET_LIST_new.fits`` mentioned below.

Creating recentered cubes
-------------------------

It can be useful to create individual cubes for each exposures, to verify the
quality of each cube, measure the FWHM, or for doing some post-processing on the
cubes. Now that we have computed offsets, we can use the ``OFFSET_LIST`` frame
in the parameters, also with sky subtraction and saving additional outputs:

.. literalinclude:: _static/settings.yml
   :start-at: muse_scipost:
   :end-at: save

And run with::

    $ musered process-exp --scipost

Combining exposures
-------------------

With the DRS
^^^^^^^^^^^^

To combine the exposures for the IC4406 dataset, with the ``muse_exp_combine``
recipe::

    $ musered exp-combine IC4406

This will use by default the ``muse_exp_combine`` parameters block, which
includes here the ``OFFSET_LIST`` frame:

.. literalinclude:: _static/settings.yml
   :start-at: muse_exp_combine:
   :end-at: OFFSET_LIST: '{workdir}/OFFSET_LIST_new.fits'

With MPDAF
^^^^^^^^^^

It is also possible to use MPDAF to produce the combined data cube, using the
``--method`` argument::

    $ musered exp-combine --method mpdaf IC4406

By default this uses the ``mpdaf_combine`` parameters block, though as usual
this can be specified with the ``--params`` argument.

.. literalinclude:: _static/settings.yml
   :start-at: mpdaf_combine:
   :end-at: version

For this we need data cubes, which can be produced directly with
``muse_scipost`` (adding ``cube`` to the ``save`` option), or later from the
pixtables. As for other recipes, ``from_recipe`` allows to specify the recipe
from which data cubes are used.

The ``muse_scipost_make_cube`` recipe allows to create cubes from
``PIXTABLE_REDUCED``. To be combined by MPDAF, cubes must be on the same grid,
and thus they must use the same ``OUTPUT_WCS`` frame::

   $ musered process-exp --makecube

.. literalinclude:: _static/settings.yml
   :start-at: muse_scipost_make_cube:
   :end-at: output_dir

.. todo:: Add docs about mosaics.

.. todo:: Add docs about using weights.

.. todo:: Already implemented but needs documentation: exposures selection with
   database queries, exclusion of flagged exposures.

Combining standards
-------------------

.. todo:: Add docs about combining standards
