import dataset
import datetime
import logging
import os
import re
import yaml

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy import event, pool
from pprint import pprint

EXP_PATTERN = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}'
DATE_PATTERN = '%Y-%m-%dT%H:%M:%S.%f'
NOON = datetime.time(16, 0, 0)
ONEDAY = datetime.timedelta(days=1)


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


def get_exp_name(filename):
    """Return the exposure id from a filename."""
    try:
        return re.findall(EXP_PATTERN, filename)[0]
    except IndexError:
        return None


def exp2datetime(exp):
    return datetime.datetime.strptime(exp, DATE_PATTERN)


def isnotebook():  # pragma: no cover
    try:
        shell = get_ipython().__class__.__name__
        if shell == 'ZMQInteractiveShell':
            return True   # Jupyter notebook or qtconsole
        elif shell == 'TerminalInteractiveShell':
            return False  # Terminal running IPython
        else:
            return False  # Other type (?)
    except NameError:
        return False      # Probably standard Python interpreter


def ProgressBar(*args, **kwargs):
    logger = logging.getLogger('origin')
    if logging.getLevelName(logger.getEffectiveLevel()) == 'ERROR':
        kwargs['disable'] = True

    from tqdm import tqdm, tqdm_notebook
    func = tqdm_notebook if isnotebook() else tqdm
    return func(*args, **kwargs)
