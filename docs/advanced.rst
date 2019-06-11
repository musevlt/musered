Advanced topics
===============

.. contents::

Using flags
-----------

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

By default the ``exp-combine`` recipe will use all the exposures with the given
OBJECT name. Of course it may be useful to do a finer selection of the
exposures. One aspect of this is to use flags, to mark exposures affected by
a specific issue (which may or may not be fixable in a following reduction). But
it may also be useful to select exposures based on other criteria.

The ``names_with_selection`` setting allows to define selections of exposures
for the combination, using queries on the database. The following example
defines two selections with date ranges, using the ``run`` column from the
``raw`` table:

.. code-block:: yaml

  mpdaf_combine:
    from_recipe: muse_scipost
    names_with_selection:
      GTO26:
        raw: "run = 'GTO26'"
      GTO27:
        raw: "run = 'GTO27'"

Another example, combining the exposures with the best atmospheric conditions,
using the FWHM estimation from *MUSE-PSFR* which is stored in the ``PR_fwhmV``
column of the ``qa_raw`` table:

.. code-block:: yaml

  mpdaf_combine_best:
    from_recipe: muse_scipost
    names_with_selection:
      gradeA:
        qa_raw: '"PR_fwhmV" < 0.6'
      gradeAB:
        qa_raw: '"PR_fwhmV" < 0.8'
    exclude_flags: True

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
