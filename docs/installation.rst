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
- mpdaf,
- python-cpl, Python interface for the MUSE DRS
- PyYAML, for the settings file
- tqdm, progress bars

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
