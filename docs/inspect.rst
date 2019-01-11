Inspecting the current status
=============================

The `musered info` command provides several ways to inspect the content of the
database and the state of the reduction.

.. contents::

.. program-output:: musered info --help
   :prompt:
   :cwd: _static

Datasets, nights, exposures
---------------------------

Most commands can take either a night or exposure name as input, so it is useful
to get easily the list of nights or exposures:

.. program-output:: musered info --datasets --nights --exps
   :prompt:
   :cwd: _static

Raw data
--------

``--raw`` takes a semicolon-separated list of ``key:value`` items that define
a selection on the ``raw`` table, e.g. ``night:2018-08-14;DPR_CATG:CALIB``.

To list all raw data files for a given night:

.. program-output:: musered info --raw night:2017-06-17
   :prompt:
   :cwd: _static

Reduction status
----------------

Without arguments the command gives an overview of the current state of the
reduction, with the number and type for the raw data, processed calibration, and
reduced data:

.. program-output:: musered info
   :prompt:
   :cwd: _static

To view only a specific table, use ``--table`` (raw, calib, science):

.. program-output:: musered info --tables raw
   :prompt:
   :cwd: _static

Reduction log for a night or exposure
-------------------------------------

This allows to see all the recipes that have been executed for a given night or
exposure, with the execution date, log file, output directory, etc.:

.. program-output:: musered info --night 2017-06-17 --short
   :prompt:
   :cwd: _static

.. program-output:: musered info --exp 2017-06-16T01:46:25.866
   :prompt:
   :cwd: _static

QC parameters
-------------

To view the QC parameters for a given type (``DPR_TYPE``) and night or exposure:

.. program-output:: musered info --qc MASTER_FLAT --date 2017-06-17
   :prompt:
   :cwd: _static
