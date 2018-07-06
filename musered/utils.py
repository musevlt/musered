import dataset
import logging
import yaml
from sqlalchemy import select
from pprint import pprint


def load_yaml_config(filename):
    """Load a YAML config file, with string substitution."""
    with open(filename, 'r') as f:
        conftext = f.read()
        conf = yaml.load(conftext)
        return yaml.load(conftext.format(**conf))


def load_db(filename, verbose=False, **kwargs):
    """Open a sqlite database with dataset."""
    if not verbose:
        dataset.database.log.addHandler(logging.NullHandler())
    return dataset.connect('sqlite:///{}'.format(filename), **kwargs)


def pprint_record(records):
    """Pretty print for a list of records from a dataset query."""
    for rec in records:
        pprint(dict(list(rec.items())))


def select_distinct(db, tablename, column):
    """Returns the distinct values for 'column' from 'tablename'."""
    table = db[tablename].table
    return sorted(o[column] for o in db.query(
        select([getattr(table.c, column)]).distinct(column)))
