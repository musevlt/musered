Advanced topics
===============

Flags
-----

Exposure selection for ``exp-combine``
--------------------------------------

Creating a new version from another one
---------------------------------------

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

To connect to the database, SQLAlchemy needs a `database url
<https://docs.sqlalchemy.org/en/latest/core/engines.html#database-urls>` which
contains the username, password, and url. Instead of putting this information in
the settings file, MuseRed allows instead to specify the name of an environment
variable that contain the url:

.. code-block:: yaml

    db_env: 'MUSERED_DB'

Additional dependencies may also be needed, depending on the database:
``psycopg2`` for PostgreSQL, ``mysql-python`` for MySQL.
