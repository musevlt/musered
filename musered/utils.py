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
from astropy.stats import sigma_clip
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

    def expanduser(confdict):
        """Expand ~ in paths."""
        for key in ('workdir', 'raw_path', 'reduced_path', 'muse_calib_path'):
            if key in confdict:
                confdict[key] = os.path.expanduser(confdict[key])
        if 'recipe_path' in confdict.get('cpl', {}):
            confdict['cpl']['recipe_path'] = os.path.expanduser(
                confdict['cpl']['recipe_path'])
        return confdict

    # We need to do 2 passes, before and after key substitution
    conf = yaml.load(conftext)
    conf = expanduser(conf)
    conf = yaml.load(conftext.format(**conf))
    conf = expanduser(conf)

    return conf


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
    """Return the exposure id from a filename.

    >>> get_exp_name('MUSE.2018-09-08T10:19:47.146.fits.fz')
    '2018-09-08T10:19:47.146'
    >>> get_exp_name('raw/MUSE.2018-09-08T10:19:47.146.fits.fz')
    '2018-09-08T10:19:47.146'
    >>> get_exp_name('foo.fits')
    >>>

    """
    try:
        return re.findall(EXP_PATTERN, filename)[0]
    except IndexError:
        return None


def parse_datetime(exp):
    """Parse an exposure name to a datetime object.

    >>> parse_datetime('2018-09-08T10:19:47.146')
    datetime.datetime(2018, 9, 8, 10, 19, 47, 146000)

    """
    return datetime.datetime.strptime(exp, DATETIME_PATTERN)


def parse_date(exp):
    """Parse a date string to a datetime object.

    >>> parse_date('2018-09-08')
    datetime.date(2018, 9, 8)

    """
    return datetime.datetime.strptime(exp, DATE_PATTERN).date()


def normalize_keyword(key):
    """Normalize FITS keywords to use it as a database column name.

    >>> normalize_keyword('foo')
    'foo'
    >>> normalize_keyword('FOO BAR')
    'FOO_BAR'
    >>> normalize_keyword('FOO-BAR')
    'FOO_BAR'
    >>> normalize_keyword('ESO INS MODE')
    'INS_MODE'
    >>> normalize_keyword('ESO DPR TYPE')
    'DPR_TYPE'

    """
    if key.startswith('ESO '):
        key = key[4:]
    return key.replace(' ', '_').replace('-', '_')


def parse_raw_keywords(flist, runs=None):
    logger = logging.getLogger(__name__)
    rows = []
    runs = runs or {}
    now = datetime.datetime.now().isoformat()
    keywords = [k.split('/')[0].strip()
                for k in RAW_FITS_KEYWORDS.splitlines() if k]

    for f in ProgressBar(flist):
        with open(f, mode='rb') as fd:
            if fd.read(30) != b'SIMPLE  =                    T':
                logger.error('skipping invalid FITS file %s', f)
                continue

        logger.debug('parsing %s', f)
        hdr = fits.getheader(f, ext=0)
        row = OrderedDict([('name', get_exp_name(f)),
                           ('filename', os.path.basename(f)),
                           ('path', f),
                           ('night', None),
                           ('date_import', now)])

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

        for key in keywords:
            row[normalize_keyword(key)] = hdr.get(key)

        rows.append(row)

    return rows


def parse_qc_keywords(flist):
    logger = logging.getLogger(__name__)
    rows = []
    for f in sorted(flist):
        with fits.open(f) as hdul:
            for hdu in hdul:
                if '.' in hdu.name:
                    name, ext = hdu.name.split('.')
                    if ext in ('DQ', 'STAT'):
                        continue
                else:
                    name = hdu.name
                cards = {normalize_keyword(key): val
                         for key, val in hdu.header['ESO QC*'].items()}
                if len(cards) == 0:
                    logger.debug('%s - %s : no QC keywords', f, name)
                    continue
                rows.append({'filename': os.path.basename(f),
                             'hdu': name, **cards})
    return rows


def query_count_to_table(table, exclude_obj=None, where=None,
                         date_list=None, run=None, calib=False, datecol='name',
                         countcol='OBJECT', exclude_names=None):
    c = table.table.c

    if date_list:
        if len(date_list) == 1:
            whereclause = [c[datecol].like(f'%{date_list[0]}%')]
        else:
            whereclause = [c[datecol].in_(date_list)]
    elif run is not None and 'run' in c:
        whereclause = [c['run'].like(f'%{run}%')]
    else:
        whereclause = [c[datecol].isnot(None)]

    whereclause.append(c[countcol].isnot(None))

    if exclude_obj is not None:
        whereclause.append(c.OBJECT.notin_(exclude_obj))
    if exclude_names is not None:
        whereclause.append(c.name.notin_(exclude_names))
    if where is not None:
        whereclause.append(where)

    query = (sql.select([c[datecol], c[countcol], func.count()])
             .where(sql.and_(*whereclause))
             .group_by(c[datecol], c[countcol]))

    # reorganize rows to have types (in columns) per night (rows)
    rows = defaultdict(dict)
    keys = set()
    for name, obj, count in table.db.executable.execute(query):
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

    for col in t.columns.values()[1:]:
        # shorten recipe names
        col.name = col.name.replace('muse_', '')

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
    logger = logging.getLogger(__name__)
    if logging.getLevelName(logger.getEffectiveLevel()) == 'DEBUG':
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


def parse_weather_conditions(mr, force=False):
    """Parse weather conditions from the .NL.txt files associated to
    observations.
    """
    logger = logging.getLogger(__name__)

    wc = (mr.rawc.DPR_TYPE == 'OBJECT')
    if not force:
        weather_tbl = mr.db['weather_conditions']
        existing_nights = [o['night'] for o in weather_tbl.find()]
        logger.debug('Skipping %d nights', len(existing_nights))
        wc = wc & (mr.rawc.night.notin_(existing_nights))

    query = (sql.select([mr.rawc.night, mr.rawc.path])
             .where(wc)
             .group_by(mr.rawc.night))
    tables = []

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

        # Fix when comment is incorrect, typically when there is no comment
        if tbl['Comment'].dtype.kind != 'U':
            tbl.replace_column('Comment', [str(s) for s in tbl['Comment']])

        if tbl.masked:
            tbl = tbl.filled()

        dates = []
        for row in tbl:
            night = row['night']
            time = row['Time']
            d = datetime.datetime.strptime(f'{night}T{time}', '%Y-%m-%dT%H:%M')
            if d.time() < NOON:
                d += ONEDAY
            dates.append(d.isoformat())

        tbl['date'] = dates
        tables.append(tbl)

    if len(tables) == 0:
        logger.debug('Nothing to do for weather conditions')
        return

    tables = vstack(tables)
    # Move the night column at beginning
    tables.columns.move_to_end('night', last=False)

    logger.info('Importing weather conditions, %d entries', len(tables))
    rows = [dict(zip(tables.colnames, row)) for row in tables]
    upsert_many(mr.db, 'weather_conditions', rows, ['night', 'date'])


def upsert_many(db, tablename, rows, keys):
    """Use dataset.Table.upsert for a list of rows.

    >>> import dataset
    >>> db = dataset.connect('sqlite:///:memory:')
    >>> table = db['sometable']
    >>> table.insert(dict(name='John Doe', age=37))
    1
    >>> upsert_many(db, 'sometable', [dict(name='John Doe', age=42)], ['name'])
    >>> table.find_one()
    OrderedDict([('id', 1), ('name', 'John Doe'), ('age', 42)])

    """
    with db as tx:
        table = tx[tablename]
        for row in rows:
            table.upsert(row, keys=keys)


def join_tables(db, tablenames, whereclause=None, columns=None, keys=None,
                use_labels=True, isouter=False, debug=False, **params):
    """Join table with other catalogs.

    >>> import dataset
    >>> from pprint import pprint
    >>> db = dataset.connect('sqlite:///:memory:')
    >>> table = db['sometable']
    >>> table.insert(dict(name='John Doe', age=37))
    1
    >>> table2 = db['sometable2']
    >>> table2.insert(dict(name='John Doe', gender='male'))
    1
    >>> pprint(next(join_tables(db, ['sometable', 'sometable2'])))
    OrderedDict([('sometable_id', 1),
                 ('sometable_name', 'John Doe'),
                 ('sometable_age', 37),
                 ('sometable2_id', 1),
                 ('sometable2_name', 'John Doe'),
                 ('sometable2_gender', 'male')])

    Parameters
    ----------
    db:
        The database
    tablenames:
        List of table names
    whereclause:
        The SQLAlchemy selection clause.
    columns: list of str
        List of columns to retrieve (all columns if None).
    keys: list of tuple
        List of keys to do the join for each catalog. If None, the IDs of
        each catalog are used (from the ``idname`` attribute). Otherwise it
        must be a list of tuples, where each tuple contains the key for
        self and the key for the other catalog.
    use_labels: bool
        By default, all columns are selected which may gives name
        conflicts. So ``use_labels`` allows to rename the columns by
        prefixinf the name with the catalog name.
    isouter: bool
        If True, render a LEFT OUTER JOIN, instead of JOIN.
    params: dict
        Additional parameters are passed to `sqlalchemy.sql.select`.

    """
    tables = [db[name].table for name in tablenames]
    if columns is None:
        columns = tables

    if keys is None:
        keys = [('name', 'name')] * (len(tables) - 1)

    query = sql.select(columns, use_labels=use_labels,
                       whereclause=whereclause, **params)
    joincl = tables[0]
    for (key1, key2), other in zip(keys, tables[1:]):
        joincl = joincl.join(other, tables[0].c[key1] == other.c[key2],
                             isouter=isouter)
    query = query.select_from(joincl)

    if debug:
        print(query)
    return db.query(query)


def all_subclasses(cls):
    return set(cls.__subclasses__()).union(
        [s for c in cls.__subclasses__() for s in all_subclasses(c)])


def find_outliers(table, colname, name='name', exps=None, sigma_lower=5,
                  sigma_upper=5):
    """Find outliers in a subset of a table,column.

    Parameters
    ----------
    table: mr.table
    colname: str
      name of column
    name: str
      exposure column name
    exps: list
      list of exposures to search
    sigma_lower: float
      value of lower sigma rejection (must be positive)
    sigma_upper: float
      value of upper sigma rejection

    Return
    ------
    dict
      names: list of exposure with deviant values
      vals: list of deviant values
      nsig: list of rejection factors
      mean: mean value
      std: standard deviation
    """
    logger = logging.getLogger(__name__)
    if exps is not None:
        res = table.find(name=exps)
    else:
        res = table.find()
    tab = [[e[colname], e[name]] for e in res if e[colname] is not None]
    vals = list(zip(*tab))[0]
    names = list(zip(*tab))[1]
    vclip = sigma_clip(vals, sigma_lower=sigma_lower, sigma_upper=sigma_upper,
                       copy=True)
    flagged = np.count_nonzero(vclip.mask)
    logger.debug('Found %d outliers values of %s over %d lines',
                 flagged, colname, len(vals))
    mean = np.ma.mean(vclip)
    std = np.ma.std(vclip)
    if flagged == 0:
        vals = []
        nsig = []
        names = []
    else:
        vals = np.array(vals)[vclip.mask]
        vals = vals.tolist()
        nsig = (vals - mean) / std
        nsig = nsig.tolist()
        names = np.array(names)[vclip.mask]
        names = names.tolist()
    return(dict(names=names, vals=vals, nsig=nsig, mean=mean, std=std))


def stat_qc_chan(mr, table, qclist, nsigma=5, run=None):
    # FIXME run not implemented
    """compute statitics of QC calibration table with 24 channels

    Parameters
    ----------
    mr: musered object
    table: str
      name of table
    qclist: list of str
      list of the QC column names
    nsigma: float
      value of sigma rejection
    run: str
      run id

    Return
    ------
    astropy table
      chan: channel column
      qc: ac name column
      mean: mean value
      std: standard deviation
      nclip: number of clipped values
      nkeep: number of kept values
    """
    nclipped = []
    nkeep = []
    mean = []
    std = []
    channels = []
    qc = []
    for k in range(1, 25):
        for q in qclist:
            qc.append(q)
            channels.append(k)
            vals = [c[q] for c in mr.db[table].find(hdu=f'CHAN{k:02d}')]
            clipvals = sigma_clip(vals, sigma=nsigma)
            nclipped.append(np.count_nonzero(clipvals.mask))
            nkeep.append(np.count_nonzero(~clipvals.mask))
            mean.append(np.ma.mean(clipvals))
            std.append(np.ma.std(clipvals))
    tab = Table(data=[channels, qc, mean, std, nclipped, nkeep],
                names=['CHAN', 'QC', 'MEAN', 'STD', 'NCLIP', 'NKEEP'])
    return tab


def find_outliers_qc_chan(mr, table, qclist, nsigma=5, run=None):
    # FIXME run not implemented
    """find outliers in a QC calibration table with 24 channels

    Parameters
    ----------
    mr: musered object
    table: str
      name of table
    qclist: list of str
      list of the QC column names
    nsigma: float
      value of sigma rejection
    run: str
      run id

    Return
    ------
    astropy table
      name: column of exposure with deviant values
      qc: ac name column
      chan: channel column
      val: value
      mean: mean value
      std: standard deviation
      nsig: rejection factors
    """
    out_name = []
    out_val = []
    out_mean = []
    out_std = []
    out_err = []
    out_qc = []
    out_chan = []
    for k in range(1, 25):
        for q in qclist:
            vals = []
            names = []
            for c in mr.db[table].find(hdu=f'CHAN{k:02d}'):
                names.append(c['name'])
                vals.append(c[q])
            clipvals = sigma_clip(vals, sigma=nsigma)
            if np.count_nonzero(clipvals.mask) == 0:
                continue
            mean = np.ma.mean(clipvals)
            std = np.ma.std(clipvals)
            for n, v in zip(np.array(names)[clipvals.mask],
                            np.array(vals)[clipvals.mask]):
                err = np.abs((v - mean) / std)
                out_mean.append(mean)
                out_std.append(std)
                out_name.append(n)
                out_chan.append(k)
                out_qc.append(q)
                out_val.append(v)
                out_err.append(err)
    tab = Table(names=['NAME', 'QC', 'CHAN', 'VAL', 'MEAN', 'STD', 'NSIGMA'],
                data=[out_name, out_qc, out_chan, out_val, out_mean, out_std,
                      out_err])
    for c in ['VAL', 'MEAN', 'STD', 'NSIGMA']:
        tab[c].format = '.3f'
    return tab


def dict_values(d):
    """Return a list of all values in a dict."""
    return list(itertools.chain(*d.values()))
