import dataset
import datetime
import itertools
import logging
import os
import numpy as np
import re
import yaml

from astropy.io import ascii, fits
from astropy.table import Table, MaskedColumn, vstack
from collections import OrderedDict, defaultdict
from sqlalchemy.engine import Engine
from sqlalchemy import event, pool, sql, func

from .settings import RAW_FITS_KEYWORDS

EXP_PATTERN = r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}.\d{3}'
DATETIME_PATTERN = '%Y-%m-%dT%H:%M:%S.%f'
DATE_PATTERN = '%Y-%m-%d'
NOON = datetime.time(20, 40, 0)
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


def normalize_recipe_name(recipe_name):
    if not recipe_name.startswith('muse_'):
        recipe_name = 'muse_' + recipe_name
    return recipe_name


def parse_raw_keywords(flist, force=False, processed=None, runs=None):
    logger = logging.getLogger(__name__)

    nskip = 0
    rows = []
    runs = runs or {}
    processed = processed or []

    keywords = [k.split('/')[0].strip()
                for k in RAW_FITS_KEYWORDS.splitlines() if k]

    for f in ProgressBar(flist):
        with open(f, mode='rb') as fd:
            if fd.read(30) != b'SIMPLE  =                    T':
                logger.error('skipping invalid FITS file %s', f)
                continue

        logger.debug('parsing %s', f)
        hdr = fits.getheader(f, ext=0)
        if not force and hdr['ARCFILE'] in processed:
            nskip += 1
            continue

        row = OrderedDict([('name', get_exp_name(f)),
                           ('filename', os.path.basename(f)),
                           ('path', f)])

        if 'DATE-OBS' in hdr:
            date = parse_datetime(hdr['DATE-OBS'])
            night = date.date()
            # Same as MuseWise
            if date.time() < NOON:
                night -= ONEDAY
            row['night'] = night.isoformat()

            for run_name, run in runs.items():
                if run['start_date'] <= night <= run['end_date']:
                    row['run'] = run_name
                    break
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


def query_count_to_table(db, tablename, exclude_obj=None, where=None):
    datecol = 'night' if tablename == 'raw' else 'name'
    countcol = 'OBJECT' if tablename == 'raw' else 'recipe_name'
    c = db[tablename].table.c

    whereclause = [c[datecol].isnot(None), c[countcol].isnot(None)]
    if where is not None:
        whereclause.append(where)

    query = (sql.select([c[datecol], c[countcol], func.count()])
             .where(sql.and_(*whereclause))
             .group_by(c[datecol], c[countcol]))

    # reorganize rows to have types (in columns) per night (rows)
    rows = defaultdict(dict)
    keys = set()
    for name, obj, count in db.executable.execute(query):
        if exclude_obj and obj in exclude_obj:
            continue
        rows[name]['name'] = name
        rows[name][obj] = count
        keys.add(obj)

    if len(rows) == 0:
        return

    # set default counts
    for row, key in itertools.product(rows.values(), keys):
        row.setdefault(key, 0)

    t = Table(rows=list(rows.values()), masked=True)
    # move name column to the beginning
    t.columns.move_to_end('name', last=False)
    for col in t.columns.values()[1:]:
        col[col == 0] = np.ma.masked

    # if only_one:
    #     for col in t.columns.values()[1:]:
    #         # shorten recipe names
    #         col.name = col.name.replace('muse_', '')
    #         # here it would print the number of frames for a recipe,
    #         # which is not the goal. replace with 1...
    #         # col[col > 0] = 1
    return t


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


def parse_gto_db(musered_db, gto_dblist):
    ranks = {2: 'A', 3: 'B', 4: 'C', 5: 'D', 6: 'X', 7: 'a', 8: 'b'}
    exps = list(musered_db['raw'].find(DPR_TYPE='OBJECT'))
    OBstart = [exp['OBS_START'] for exp in exps]
    arcf = [exp['ARCFILE'] for exp in exps]

    flags, comments, fcomments = {}, {}, {}
    for f in gto_dblist:
        db = load_db(f)
        flags.update({r['OBstart']: r
                      for r in db['OBflags'].find(OBstart=OBstart)})
        comments.update({r['OBstart']: r
                         for r in db['OBcomments'].find(OBstart=OBstart)})
        fcomments.update({r['arcfile']: r
                          for r in db['fcomments'].find(arcfile=arcf)})

    rows = []
    for exp in exps:
        comm = comments.get(exp['OBS_START'], {})
        fcomm = fcomments.get(exp['ARCFILE'], {})
        flag = flags.get(exp['OBS_START'], {})
        rows.append({
            'name': exp['name'],
            'ARCFILE': exp['ARCFILE'],
            'OBS_START': exp['OBS_START'],
            'version': '0',
            'flag': ranks.get(flag.get('flag'), ''),
            'comment': comm.get('comment', ''),
            'date': comm.get('date', ''),
            'author': comm.get('author', ''),
            'fcomment': fcomm.get('comment', ''),
            'fdate': fcomm.get('date', ''),
            'fauthor': fcomm.get('author', '')
        })

    with musered_db as tx:
        table = tx['gto_logs']
        table.drop()
        table.insert_many(rows)
        table.create_index(['name', 'OBstart', 'flag', 'version'])

    return table


def parse_weather_conditions(mr):
    """Parse weather conditions from the .NL.txt files associated to
    observations.
    """
    logger = logging.getLogger(__name__)

    tables = []
    query = (sql.select([mr.rawc.night, mr.rawc.path])
             .where(mr.rawc.DPR_TYPE == 'OBJECT')
             .group_by(mr.rawc.night))

    for night, path in mr.execute(query):
        cond_file = path.replace('.fits.fz', '.NL.txt')
        logger.debug('Night %s, %s', night, cond_file)

        get_lines = False
        lines = []
        with open(cond_file) as f:
            # Find lines between "Weather observations" and the next separator
            # line. Also skip malformed lines ("New update at...").
            for line in f:
                if line.startswith('Weather observations'):
                    get_lines = True
                elif get_lines:
                    if line.startswith('----------------------'):
                        break
                    if not line.startswith('New update'):
                        lines.append(line)

        try:
            tbl = ascii.read(''.join(lines))
        except Exception as e:
            logger.warning('Failed to parse lines: %s', e)
            continue
        tbl['night'] = night

        dates = []
        for row in tbl:
            night = row['night']
            time = row['Time']
            d = datetime.datetime.strptime(f'{night}T{time}', '%Y-%m-%dT%H:%M')
            if d.time() < NOON:
                d += ONEDAY
            dates.append(d.isoformat())

        tbl['date'] = dates
        tbl.remove_column('Time')
        tables.append(tbl)

    tables = vstack(tables)
    # Move the night column at beginning
    tables.columns.move_to_end('night', last=False)

    logger.info('Importing weather conditions, %d entries', len(tables))
    rows = [dict(zip(tables.colnames, row)) for row in tables]
    upsert_many(mr.db, 'weather_conditions', rows, ['night', 'date'])


def upsert_many(db, tablename, rows, keys):
    """Use dataset.Table.upsert for a list of rows."""
    with db as tx:
        table = tx[tablename]
        for row in rows:
            table.upsert(row, keys=keys)
