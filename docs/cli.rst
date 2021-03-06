Command-line interface
======================

Every step can be run with sub-commands of the ``musered`` command. By default
it supposes that the command is run in the directory containing the settings
file, named ``settings.yml``. Otherwise this settings file can be specified
with ``--settings``.

It is also possible to setup `completion
<https://click.palletsprojects.com/en/7.x/bashcomplete/>`_, or to run the
subcommands in a REPL with ``musered repl`` (after installing `click-repl`_).

.. contents::

.. _click-repl: https://github.com/click-contrib/click-repl

.. click:: musered.__main__:cli
  :prog: musered
  :show-nested:

