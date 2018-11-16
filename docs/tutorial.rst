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

See the next paragraph for the meaning of ``archive_filter``.


Data retrieval
--------------

Retrieving a dataset is done with `Astroquery
<https://astroquery.readthedocs.io/en/latest/eso/eso.html>`__. To find all the
possible query options for Muse, that can be uses with the ``archive_filter``
setting, use this::

    $ musered retrieve-data --help-query

``archive_filter`` must then contain a list of key/value items, defining a query
on the ESO archive.  For the IC4406 example we just use the target name, but it
is also possible to specify dates, instrument mode, or a programme ID.

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
    One drawback of this deduplication is that, if an OBJECT file was retrieved
    but the process was interrupted before all its calibrations were retrieved,
    at the next execution the missing calibrations will not be downloaded.

    This is fixed with Astroquery 0.3.9.dev582 (``pip install
    astroquery==0.3.9.dev582``) and using the ``--force`` option which will
    force the query to be done with all OBJECT files.


Ingesting metadata in a database
--------------------------------

Then the next step is to ingest FITS keywords in a SQLite database. This step
is triggered automatically by the ``retrieve-data`` command, but it can also be
run manually if needed, with::

    $ musered update-db

This command can be run each time new data are retrieved, and by default it will
add only the new files that are not yet in the database.

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
name, but this can also be specified with ``--params`` which can be used to run
the same recipe with different sets of paramaters.  The paramater names and
values are the same as the DRS ones.

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

TODO: Allow to specify frames for a given night

The number of nights before and after the current one, for which frames are
searched for, can be specified with ``offsets``:

.. code-block:: yaml

   muse_wavecal:
      frames:
         offsets:
            STD_TELLURIC: 5
            STD_RESPONSE: 5
            TWILIGHT_CUBE: 3


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
^^^^^^^^^^^^^^^^^

To compute the offsets between exposures, with the ``muse_exp_align`` recipe::

    $ musered exp-align IC4406

A method can be specified with ``--method``. The default is ``drs`` which
corresponds to the ``muse_exp_align`` recipe, and it is also possible to use
``imphot`` with ``--method=imphot``. The ``--name`` option can be used to give
a name (default to the dataset name) to identify later the ``OFFSET_LIST``
frame.

Creating recentered cubes
^^^^^^^^^^^^^^^^^^^^^^^^^

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
^^^^^^^^^^^^^^^^^^^

To combine the exposures, with the ``muse_exp_combine`` recipe::

    $ musered exp-combine IC4406

And with the parameters with the ``OFFSET_LIST`` frame:

.. literalinclude:: _static/settings.yml
   :start-at: muse_exp_combine:
   :end-at: OFFSET_LIST: '{workdir}/OFFSET_LIST_new.fits'

It is also possible to use MPDAF to combine the data cube. For this we need
data cubes, which can be produced directly with ``muse_scipost`` or later from
the pixtables. The ``muse_scipost_make_cube`` recipe allows to create cubes
from ``PIXTABLE_REDUCED``::

   $ musered process-exp --makecube

.. literalinclude:: _static/settings.yml
   :start-at: muse_scipost_make_cube:
   :end-at: output_dir

.. literalinclude:: _static/settings.yml
   :start-at: mpdaf_combine:
   :end-at: version

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

