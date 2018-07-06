import dataset
import logging
import os
import yaml

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy import event, pool
from pprint import pprint


def load_yaml_config(filename):
    """Load a YAML config file, with string substitution."""
    with open(filename, 'r') as f:
        conftext = f.read()
        conf = yaml.load(conftext)
        return yaml.load(conftext.format(**conf))


def load_db(filename, **kwargs):
    """Open a sqlite database with dataset."""

    kwargs.setdefault('engine_kwargs', {})

    # Use a NullPool by default, which is sqlalchemy's default but dataset
    # uses instead a StaticPool.
    kwargs['engine_kwargs'].setdefault('poolclass', pool.NullPool)

    debug = os.getenv('SQLDEBUG')
    if debug is not None:
        logging.getLogger(__name__).info('Activate debug mode')
        kwargs['engine_kwargs']['echo'] = True

    db = dataset.connect(f'sqlite:///{filename}', **kwargs)

    @event.listens_for(Engine, 'connect')
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys = ON')
        cursor.execute('PRAGMA cache_size = -100000')
        cursor.execute('PRAGMA journal_mode = WAL')
        cursor.close()

    return db


def pprint_record(records):
    """Pretty print for a list of records from a dataset query."""
    for rec in records:
        pprint(dict(list(rec.items())))


def select_distinct(db, tablename, column):
    """Returns the distinct values for 'column' from 'tablename'."""
    table = db[tablename].table
    return sorted(o[column] for o in db.query(
        select([getattr(table.c, column)]).distinct(column)))
