Advanced topics
===============

Flags
-----

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
