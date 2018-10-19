Python API
==========

MuseRed can also be used as a Python object, with the `~musered.MuseRed` class
which provides all the methods corresponding to the command-line sub-commands:

.. code-block:: python

    >>> from musered import MuseRed
    >>> mr = MuseRed(settings_file='settings.yml')
    >>> mr.list_datasets()
    - IC4406
    >>> mr.list_nights()
    - 2017-04-23
    - 2017-06-13
    - 2017-06-15
    - 2017-06-17
    - 2017-06-18
    - 2017-06-19
    - 2017-10-26


.. automodapi:: musered
   :no-heading:
