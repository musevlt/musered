Advanced topics
===============

Flags
-----

It is possible to add flags to exposures, which can then be used in the
exposures combination. These flags are linked to a version of the reduction.
MuseRed comes with a set of predefined flags, which are defined in the
``musered.flags`` module:

 .. autodata::
    musered.FLAGS

It is also possible to define additional flags in the settings file:

.. literalinclude:: _static/settings.yml
   :start-at: Define additional flags
   :end-at: MY_FLAG

To use flags, one must add them to the individual exposures using the Python
API. The `musered.MuseRed.flags` attribute is a `musered.QAFlags` object, with
various methods to add, remove, or list flags for a given exposure, or to find
exposures with specific flags.

.. todo:: Add example, which probably needs an update of the test database.

It is then possible to use these flags to exclude exposures for the combine
recipe. The ``exclude_flags`` setting can be set to `True` to exclude all
flagged exposures, or it can be a list of flags to exclude:

.. code-block:: yaml

  mpdaf_combine:
    from_recipe: muse_scipost
    exclude_flags:
      - SHORT_EXPTIME
      - VERYBAD_IMAQUALITY
      - VERYBAD_SLICE


Exposure selection for ``exp-combine``
--------------------------------------

Managing versions
-----------------

MuseRed allows to create new versions of the reduction, by incrementing the
``version`` value in the settings file. This is useful to keep track of what was
done for a given version, keeping all the information in the ``reduced`` table
(which name is actually ``reduced_{version}``).

When creating a new version, a new ``reduced_{version}`` table is created, but
it can be useful to restart the reduction from a specific step, instead of
reprocessing everything from the beginning.  So to reuse files that were reduced
in a previous version, what is needed is to have access to the database records
for these files. The `~musered.MuseRed.copy_reduced` method can be used for this
purpose, to copy database records from a previous version in the current
``reduced`` table. These records contain the path to the files from the previous
version.
