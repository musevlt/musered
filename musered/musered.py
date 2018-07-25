import cpl
import datetime
import itertools
import logging
import numpy as np
import os
from astropy.io import fits
from astropy.table import Table
from astropy.utils.decorators import lazyproperty
from collections import OrderedDict, defaultdict
from glob import glob, iglob
from mpdaf.log import setup_logging
from sqlalchemy import sql, func

from .settings import RAW_FITS_KEYWORDS, STATIC_FRAMES
from .utils import (load_yaml_config, load_db, get_exp_name,
                    parse_date, parse_datetime, NOON, ONEDAY, ProgressBar)


class StaticCalib:
    """Manage static calibrations.

    It must be instantiated with a directory containing the default static
    calibration files, and a settings dict that can be used to define time
    periods where a given calibration file is valid.
    """

    def __init__(self, path, conf):
        self.path = path
        self.conf = conf

    @lazyproperty
    def files(self):
        return os.listdir(self.path)

    @lazyproperty
    def catg_list(self):
        cat = defaultdict(list)
        for f in self.files:
            key = fits.getval(os.path.join(self.path, f),
                              'ESO PRO CATG', ext=0)
            cat[key].append(f)
        return cat

    def get(self, key, date=None):
        file = None
        if key in self.conf:
            # if key is defined in the conf file, try to find a static calib
            # file that matched the date requirement
            for item, val in self.conf[key].items():
                if date is None:
                    file = item
                    break
                start_date = val.get('start_date', datetime.date.min)
                end_date = val.get('end_date', datetime.date.max)
                if start_date < date < end_date:
                    file = item
                    break

        if file is None:
            # found nothing, use default from the static calib directory
            if len(self.catg_list[key]) > 1:
                logger = logging.getLogger(__name__)
                logger.warning('multiple options for %s, using the first '
                               'one: %r', key, self.catg_list[key])
            file = self.catg_list[key][0]

        if file not in self.files:
            raise ValueError(f'could not find {file}')
        return os.path.join(self.path, file)


class MuseRed:

    def __init__(self, settings_file='settings.yml'):
        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file

        self.conf = load_yaml_config(settings_file)
        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.reduced_path = self.conf['reduced_path']

        self.db = load_db(self.conf['db'])
        self.raw = self.db.create_table('raw')
        self.reduced = self.db.create_table('reduced')

        self.static_calib = StaticCalib(self.conf['muse_calib_path'],
                                        self.conf['static_calib'])
        self.init_cpl_params()

    @lazyproperty
    def nights(self):
        """Return the list of nights for which data is available."""
        if 'night' in self.raw.columns:
            return self.select_column('night', distinct=True)
        else:
            return []

    def list_datasets(self):
        """Print the list of datasets."""
        for name in self.datasets:
            print(f'- {name}')

    def list_nights(self):
        """Print the list of nights."""
        for x in sorted(self.nights):
            print(f'- {x:%Y-%m-%d}')

    def info(self):
        print(f'{self.raw.count()} files\n')

        print('Datasets:')
        self.list_datasets()

        # uninteresting objects to exclude from the report
        excludes = ('Astrometric calibration (ASTROMETRY)', )

        # count files per night and per type
        for table, datecol, title in (
                (self.raw, 'night', 'Raw'),
                (self.reduced, 'date_obs', 'Processed')):

            print(f'\n{title} data:\n')
            if datecol not in table.columns:
                print('Nothing yet.')
                return

            col = table.table.columns
            query = (sql.select([col[datecol], col.OBJECT,
                                 func.count(col[datecol])])
                     .where(col[datecol].isnot(None))
                     .group_by(col[datecol], col.OBJECT))

            # reorganize rows to have types (in columns) per night (rows)
            rows = defaultdict(dict)
            keys = set()
            for date, obj, count in self.db.executable.execute(query):
                if obj in excludes:
                    continue
                rows[date]['date'] = date.isoformat()
                rows[date][obj] = count
                keys.add(obj)

            # set default counts
            for row, key in itertools.product(rows.values(), keys):
                row.setdefault(key, 0)

            t = Table(rows=list(rows.values()), masked=True)
            # move date column to the beginning
            t.columns.move_to_end('date', last=False)
            for col in t.columns.values()[1:]:
                col[col == 0] = np.ma.masked

            t.pprint(max_lines=-1)

    def select_column(self, name, notnull=True, distinct=False,
                      whereclause=None, table='raw'):
        col = self.db[table].table.c[name]
        wc = col.isnot(None) if notnull else None
        if whereclause is not None:
            wc = sql.and_(whereclause, wc)
        select = sql.select([col], whereclause=wc)
        if distinct:
            select = select.distinct(col)
        return [x[0] for x in self.db.executable.execute(select)]

    def update_db(self, force=False):
        """Create or update the database containing FITS keywords."""

        flist = []
        for root, dirs, files in os.walk(self.raw_path):
            for f in files:
                if f.endswith(('.fits', '.fits.fz')):
                    flist.append(os.path.join(root, f))
        self.logger.info('found %d FITS files', len(flist))

        keywords = [k.split('/')[0].strip()
                    for k in RAW_FITS_KEYWORDS.splitlines() if k]

        # get the list of files already in the database
        try:
            arcfiles = self.select_column('ARCFILE')
        except Exception:
            arcfiles = []

        nskip = 0
        rows = []
        for f in ProgressBar(flist):
            hdr = fits.getheader(f, ext=0)
            if not force and hdr['ARCFILE'] in arcfiles:
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
            else:
                row['night'] = None

            for key in keywords:
                col = key[4:] if key.startswith('ESO ') else key
                col = col.replace(' ', '_').replace('-', '_')
                row[col] = hdr.get(key)

            rows.append(row)

        self.raw.insert_many(rows)
        self.logger.info('inserted %d rows, skipped %d', len(rows), nskip)

        # cleanup cached attributes
        del self.nights

        for name in ('name', 'ARCFILE'):
            if not self.raw.has_index([name]):
                self.raw.create_index([name])

    def init_cpl_params(self):
        """Load esorex.rc settings and override with the settings file."""

        conf = self.conf['cpl']
        cpl.esorex.init()

        if conf['recipe_path'] is not None:
            cpl.Recipe.path = conf['recipe_path']
        if conf['esorex_msg'] is not None:
            cpl.esorex.log.level = conf['esorex_msg']  # file logging
        if conf['esorex_msg_format'] is not None:
            cpl.esorex.log.format = conf['esorex_msg_format']

        conf.setdefault('log_dir', os.path.join(self.reduced_path, 'logs'))
        os.makedirs(conf['log_dir'], exist_ok=True)

        # terminal logging: disable cpl's logger as it uses the root logger.
        cpl.esorex.msg.level = 'off'
        default_fmt = '%(levelname)s - %(name)s: %(message)s'
        setup_logging(name='cpl', level=conf.get('msg', 'info').upper(),
                      color=True, fmt=conf.get('msg_format', default_fmt))

        # default params for recipes
        params = self.conf['recipes'].setdefault('common', {})
        params.setdefault('log_dir', conf['log_dir'])
        params.setdefault('temp_dir', os.path.join(self.reduced_path, 'tmp'))

    def find_calib(self, night, OBJECT, ins_mode, nrequired=24, day_off=0):
        res = self.reduced.find_one(date_obs=night, INS_MODE=ins_mode,
                                    OBJECT=OBJECT)
        if res is None and day_off != 0:
            for off, direction in itertools.product(range(1, day_off + 1),
                                                    (1, -1)):
                off = datetime.timedelta(days=off * direction)
                res = self.reduced.find_one(
                    date_obs=night + off, INS_MODE=ins_mode, OBJECT=OBJECT)
                if res is not None:
                    self.logger.warning('Using %s from night %s',
                                        OBJECT, night + off)
                    break

        if res is None:
            raise ValueError(f'could not find {OBJECT} for night {night}')

        flist = sorted(glob(f"{res['path']}/{OBJECT}*.fits"))
        if len(flist) != nrequired:
            raise ValueError(f'found {len(flist)} {OBJECT} files '
                             f'instead of {nrequired}')
        return flist

    def get_calib_frames(self, recipe, night, ins_mode, day_off=0):
        frames = {}
        # TODO: add option to use DARK
        skip_frames = ('MASTER_DARK', 'NONLINEARITY_GAIN')
        for frame in recipe.calib_frames:
            if frame in STATIC_FRAMES:
                frames[frame] = self.static_calib.get(frame, date=night)
            elif frame not in skip_frames:
                frames[frame] = self.find_calib(night, frame, ins_mode,
                                                day_off=day_off)

        return frames

    def process_calib(self, recipe_name, night_list=None,
                      skip_processed=False):
        from .recipes.calib import get_calib_cls

        # create the cpl.Recipe object
        recipe_name = 'muse_' + recipe_name
        recipe_cls = get_calib_cls(recipe_name)
        OBJECT = recipe_cls.OBJECT

        # get the list of nights to process
        if night_list is not None:
            night_list = [parse_date(night) for night in night_list]
        else:
            night_list = self.select_column(
                'night', distinct=True,
                whereclause=(self.raw.table.c.OBJECT == OBJECT))
        night_list = list(sorted(night_list))

        info = self.logger.info
        info('%s, %d nights', recipe_name, len(night_list))
        self.logger.debug('nights: ' + ', '.join(map(str, night_list)))

        if skip_processed:
            night_processed = self.select_column(
                'date_obs', table='reduced', distinct=True,
                whereclause=(self.reduced.table.c.recipe_name == recipe_name))
            self.logger.debug('processed: ' +
                              ', '.join(map(str, sorted(night_processed))))
            if len(night_processed) == len(night_list):
                info('Already processed, nothing to do')
                return
            else:
                info('%d nights already processed', len(night_processed))

        # Instantiate the recipe object
        recipe = recipe_cls(**self.conf['recipes']['common'])
        recipe_params = self.conf['recipes'].get(recipe_name)

        for night in night_list:
            if skip_processed and night in night_processed:
                self.logger.debug('night %s already processed', night)
                continue

            res = list(self.raw.find(night=night, OBJECT=OBJECT))
            flist = [o['path'] for o in res]
            ins_mode = set(o['INS_MODE'] for o in res)
            if len(ins_mode) > 1:
                raise ValueError('night with multiple INS.MODE, not supported')
            ins_mode = ins_mode.pop()
            info('night %s, %d %s files, mode=%s', night, len(flist),
                 OBJECT, ins_mode)

            output_dir = os.path.join(self.reduced_path, recipe.output_dir,
                                      f'{night.isoformat()}.{ins_mode}')

            calib = self.get_calib_frames(recipe, night, ins_mode, day_off=1)
            results = recipe.run(flist, output_dir=output_dir,
                                 params=recipe_params, **calib)

            self.logger.debug('Output frames : ', recipe.output_frames)
            date_run = datetime.datetime.now().isoformat()

            for out_frame in recipe.output_frames:
                # save in database for each output frame, but check before that
                # files were created for each frame (some are optional)
                if any(iglob(f"{output_dir}/{out_frame}*.fits")):
                    self.reduced.upsert({
                        'date_run': date_run,
                        'recipe_name': recipe_name,
                        'date_obs': night,
                        'path': output_dir,
                        'OBJECT': out_frame,
                        'INS_MODE': ins_mode,
                        'user_time': results.stat.user_time,
                        'sys_time': results.stat.sys_time,
                        **recipe.dump()
                    }, ['date_obs', 'recipe_name', 'OBJECT'])
