Installation
============

First, clone the repository and install the package::

    pip install .

It is also possible to install with a few additional dependencies, for the
command-line interface::

    pip install .\[all\]

The following dependencies are required:

- astroquery>=0.3.9, to retrieve data from the ESO archive
- click, command-line interface
- dataset, database access
- joblib, multiprocessing
- mpdaf, MUSE Python utilities
- python-cpl, Python interface for the MUSE DRS
- PyYAML, for the settings file
- tqdm, progress bar

Storing password to retrieve data
---------------------------------

Astroquery can use the keyring_ package to store passwords. This can be
activated in the settings file, in the ``retrieve_data`` section. However the
keyring backend that is used by default depends on the OS and the availability
of a desktop environment, and this may fails badly on a remote server. You can
check that it works with commands like ``keyring --help`` or ``keyring
--list-backends``.

Alternative keyring can be used with the keyrings.alt_ package, for instance
the plain text backend may be useful though much less secure (!). First install
the package::

    $ pip install keyrings.alt

Check the config directory on your system::

    $ python -c "import keyring.util.platform_; print(keyring.util.platform_.config_root())"
    /home/conseil/.local/share/python_keyring

And edit the ``keyringrc.cfg`` file to specify the backend::

    $ less /home/conseil/.local/share/python_keyring/keyringrc.cfg
    [backend]
    default-keyring=keyrings.alt.file.PlaintextKeyring


.. _astroquery: https://astroquery.readthedocs.io/en/latest/
.. _keyring: https://pypi.org/project/keyring/
.. _keyrings.alt: https://pypi.org/project/keyrings.alt/


Using another database instead of SQLite
----------------------------------------

MuseRed uses by default an SQLite database, which is usually a good choice, but
it is sometimes useful to use another databases. In particular, when willing to
use several computing machines with a shared NFS storage, SQLite is not
recommended.

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
``psycopg2-binary`` for PostgreSQL, ``mysql-python`` for MySQL.
