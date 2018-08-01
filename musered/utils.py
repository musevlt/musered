import dataset
import datetime
import logging
import os
import numpy as np
import re
import yaml

from astropy.io import fits
from astropy.table import Table, MaskedColumn
from collections import OrderedDict
from sqlalchemy.engine import Engine
from sqlalchemy import event, pool

from .settings import RAW_FITS_KEYWORDS

EXP_PATTERN = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}'
DATETIME_PATTERN = '%Y-%m-%dT%H:%M:%S.%f'
DATE_PATTERN = '%Y-%m-%d'
NOON = datetime.time(18, 30, 0)
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


def load_table(db, name, indexes=None):
    logger = logging.getLogger(__name__)
    table = db[name]
    first = table.find_one()
    t = Table(list(zip(*[list(o.values()) for o in table.find()])),
              names=list(first.keys()), masked=True)

    for name, col in t.columns.items():
        if col.dtype is np.dtype(object):
            try:
                data = col.data.data.astype(float)
            except Exception:
                pass
            else:
                logger.debug('Converted %s column to float', col.name)
                c = MaskedColumn(name=col.name, dtype=float, fill_value=np.nan,
                                 data=np.ma.masked_invalid(data))
                t.replace_column(name, c)
        elif np.issubdtype(col.dtype, np.floating):
            t[name] = np.ma.masked_greater_equal(t[name], 1e20)
    if indexes:
        t.add_index(indexes)
    return t


def get_exp_name(filename):
    """Return the exposure id from a filename."""
    try:
        return re.findall(EXP_PATTERN, filename)[0]
    except IndexError:
        return None


def parse_datetime(exp):
    return datetime.datetime.strptime(exp, DATETIME_PATTERN)


def parse_date(exp):
    return datetime.datetime.strptime(exp, DATE_PATTERN).date()


def normalize_keyword(key):
    """Normalize FITS keywords to use it as a database column name."""
    if key.startswith('ESO '):
        key = key[4:]
    return key.replace(' ', '_').replace('-', '_')


def parse_raw_keywords(flist, force=False, processed=None):
    nskip = 0
    rows = []
    processed = processed or []

    keywords = [k.split('/')[0].strip()
                for k in RAW_FITS_KEYWORDS.splitlines() if k]

    for f in ProgressBar(flist):
        hdr = fits.getheader(f, ext=0)
        if not force and hdr['ARCFILE'] in processed:
            nskip += 1
            continue

        row = OrderedDict([('name', get_exp_name(f)),
                           ('filename', os.path.basename(f)),
                           ('path', f)])

        if 'DATE-OBS' in hdr:
            date = parse_datetime(hdr['DATE-OBS'])
            row['night'] = date.date()
            # Same as MuseWise
            if date.time() < NOON:
                row['night'] -= ONEDAY
            row['night'] = row['night'].isoformat()
        else:
            row['night'] = None

        for key in keywords:
            row[normalize_keyword(key)] = hdr.get(key)

        rows.append(row)

    return rows, nskip


def parse_qc_keywords(flist):
    rows = []
    for f in sorted(flist):
        hdr = fits.getheader(f)
        cards = {normalize_keyword(key): val
                 for key, val in hdr['ESO QC*'].items()}
        if len(cards) == 0:
            break  # no QC params
        rows.append({'filename': os.path.basename(f), **cards})
    return rows


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
