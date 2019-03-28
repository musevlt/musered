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


Using another database instead of SQLite
----------------------------------------

MuseRed uses the `dataset <http://github.com/pudo/dataset/>`_ package to access
the database, and this package is itself based on the `SQLAlchemy
<https://www.sqlalchemy.org/>`_ ORM. So MuseRed is able to use any database
supported by SQLAlchemy, e.g. SQLite, PostgreSQL, or MySQL for the most
well-known.

By default (in the documentation and example settings file), MuseRed uses
SQLite as this database requires no setup and is easy to use and backup:

.. code-block:: yaml

    db: 'musered.db'

But SQLite has some limitations, the most annoying being for parallel use of
the database. In particular one should not use SQLite from multiple computers
with a database stored on a NFS mount. In this case one should move to a more
robust database with MySQL or PostgreSQL.

To connect to the database, SQLAlchemy needs a `database URL
<https://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls>` which
contains the username, password, and URL. Instead of putting this information in
the settings file, MuseRed allows instead to specify the name of an environment
variable that contain the URL:

.. code-block:: yaml

    db_env: 'MUSERED_DB'

Additional dependencies may also be needed, depending on the database:
``psycopg2`` for PostgreSQL, ``mysql-python`` for MySQL.
