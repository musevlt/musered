import cpl
import datetime
import itertools
import logging
import numpy as np
import operator
import os
import textwrap
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
    """The main class handling all MuseRed's logic.

    This class manages the database, and use the settings file, to provide all
    the methods to operate on the datasets.

    """

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
        """Print a summary of the raw and reduced data."""
        print(f'{self.raw.count()} files\n')

        print('Datasets:')
        self.list_datasets()

        # uninteresting objects to exclude from the report
        excludes = ('Astrometric calibration (ASTROMETRY)', )

        # count files per night and per type
        for table, datecol, countcol, title in (
                (self.raw, 'night', 'OBJECT', 'Raw'),
                (self.reduced, 'date_obs', 'recipe_name', 'Processed')):

            print(f'\n{title} data:\n')
            if datecol not in table.columns:
                print('Nothing yet.')
                return

            col = table.table.columns
            query = (sql.select([col[datecol], col[countcol],
                                 func.count(col[datecol])])
                     .where(sql.and_(
                         col[datecol].isnot(None),
                         col[countcol].isnot(None)
                     ))
                     .group_by(col[datecol], col[countcol]))

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

            if title == 'Processed':
                for col in t.columns.values()[1:]:
                    # shorten recipe names
                    col.name = col.name.replace('muse_', '')
                    # here it would print the number of time a recipe was run,
                    # which is not the goal. replace with 1...
                    col[col > 0] = 1

            t.pprint(max_lines=-1)

    def info_exp(self, date_obs):
        """Print information about a given exposure or night."""
        res = defaultdict(list)
        for r in self.reduced.find(date_obs=date_obs):
            res[r['recipe_name']].append(r)

        res = list(res.values())
        res.sort(key=lambda x: x[0]['date_run'])

        print(textwrap.dedent(f"""
        ==================
         {date_obs}
        ==================
        """))

        for recipe in res:
            o = recipe[0]
            frames = ', '.join(r['OBJECT'] for r in recipe)
            print(textwrap.dedent(f"""\
            recipe: {o['recipe_name']}
            - date    : {o['date_run']}
            - log     : {o['log_file']}
            - frames  : {frames}
            - path    : {o['path']}
            - warning : {o['nbwarn']}
            - runtime : {o['user_time']:.1f} (user) {o['sys_time']:.1f} (sys)
            """))

    def select_column(self, name, notnull=True, distinct=False,
                      whereclause=None, table='raw'):
        """Select values from a column of the database."""
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
        """Return calibration files for a given night, type, and mode."""
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

    def get_calib_frames(self, recipe, night, ins_mode, day_off=0,
                         exclude_frames=None):
        """Return a dict with all calibration frames for a recipe."""
        frames = {}
        exclude_frames = set(exclude_frames or recipe.exclude_frames)

        for frame in set(recipe.calib_frames) - exclude_frames:
            if frame in STATIC_FRAMES:
                frames[frame] = self.static_calib.get(frame, date=night)
            else:
                frames[frame] = self.find_calib(night, frame, ins_mode,
                                                day_off=day_off)

        return frames

    def find_illum(self, night, ref_temp, ref_mjd_date):
        """Find the best ILLUM exposure for the night.

        First, illums are sorted by date to find the closest one in time, then
        if there are multiple illums within 2 hours, the one with the closest
        temperature is used.

        """
        illums = sorted(
            (o['DATE_OBS'],                       # Date
             abs(o['INS_TEMP7_VAL'] - ref_temp),  # Temperature difference
             abs(o['MJD_OBS'] - ref_mjd_date),    # Date difference
             o['path'])                           # File path
            for o in self.raw.find(DPR_TYPE='FLAT,LAMP,ILLUM', night=night))

        if len(illums) == 0:
            self.logger.warning('No ILLUM found')
            return

        # Filter illums to keep the ones within 2 hours
        close_illums = [illum for illum in illums if illum[2] < 2/24.]

        if len(close_illums) == 0:
            self.logger.warning('No ILLUM in less than 2h')
            res = illums[0]
        elif len(close_illums) == 1:
            self.logger.debug('Only one ILLUM in less than 2h')
            res = illums[0]
        else:
            self.logger.debug('More than one ILLUM in less than 2h')
            # Sort by temperature difference
            illums.sort(key=operator.itemgetter(1))
            res = illums[0]
            for illum in illums:
                self.logger.debug('%.2f %.2f %s', *illum[:3])

        self.logger.info('Found ILLUM : %s (Temp diff: %.3f, Time diff: '
                         '%.2f min.)', res[0], res[1], res[2] * 24 * 60)
        return res[3]

    def run_recipe(self, recipe_cls, date_list, skip_processed=False,
                   by_night=False, **kwargs):
        DPR_TYPE = recipe_cls.DPR_TYPE
        recipe_name = recipe_cls.recipe_name
        label = 'night' if by_night else 'exposure'
        datecol = 'night' if by_night else 'date_obs'

        self.logger.info('Running %s for %d %ss',
                         recipe_name, len(date_list), label)
        self.logger.debug(f'{label}s: ' + ', '.join(map(str, date_list)))

        if skip_processed:
            processed = self.select_column(
                'date_obs', table='reduced', distinct=True,
                whereclause=(self.reduced.table.c.recipe_name == recipe_name))
            self.logger.debug('processed: ' +
                              ', '.join(map(str, sorted(processed))))
            if len(processed) == len(date_list):
                self.logger.info('Already processed, nothing to do')
                return
            else:
                self.logger.info('%d %ss already processed',
                                 len(processed), label)

        # Instantiate the recipe object
        recipe = recipe_cls(**self.conf['recipes']['common'])
        recipe_conf = self.conf['recipes'].get(recipe_name, {})

        for date_obs in date_list:
            if skip_processed and date_obs in processed:
                self.logger.debug('%s already processed', date_obs)
                continue

            res = list(self.raw.find(**{datecol: date_obs,
                                        'DPR_TYPE': DPR_TYPE}))
            flist = [o['path'] for o in res]
            ins_mode = set(o['INS_MODE'] for o in res)
            if len(ins_mode) > 1:
                raise ValueError(f'{label} with multiple INS.MODE, '
                                 'not supported yet')
            ins_mode = ins_mode.pop()
            self.logger.info('%s %s : %d %s files, mode=%s',
                             label, date_obs, len(flist), DPR_TYPE, ins_mode)

            output_dir = os.path.join(self.reduced_path, recipe.output_dir,
                                      f'{date_obs.isoformat()}.{ins_mode}')

            calib = self.get_calib_frames(
                recipe, date_obs, ins_mode, day_off=1,
                exclude_frames=recipe_conf.get('exclude_frames'))

            if recipe.use_illum:
                ref_temp = np.mean([o['INS_TEMP7_VAL'] for o in res])
                ref_date = np.mean([o['MJD_OBS'] for o in res])
                kwargs['illum'] = self.find_illum(date_obs, ref_temp, ref_date)

            params = recipe_conf.get('params')
            results = recipe.run(flist, output_dir=output_dir,
                                 params=params, **calib, **kwargs)

            self.logger.debug('Output frames : ', recipe.output_frames)
            date_run = datetime.datetime.now().isoformat()

            for out_frame in recipe.output_frames:
                # save in database for each output frame, but check before that
                # files were created for each frame (some are optional)
                if any(iglob(f"{output_dir}/{out_frame}*.fits")):
                    self.reduced.upsert({
                        'date_run': date_run,
                        'recipe_name': recipe_name,
                        'date_obs': date_obs,
                        'path': output_dir,
                        'OBJECT': out_frame,
                        'INS_MODE': ins_mode,
                        'user_time': results.stat.user_time,
                        'sys_time': results.stat.sys_time,
                        **recipe.dump()
                    }, ['date_obs', 'recipe_name', 'OBJECT'])

    def process_calib(self, recipe_name, night_list=None,
                      skip_processed=False, **kwargs):
        """Run a calibration recipe."""

        # create the cpl.Recipe object
        from .recipes.calib import get_recipe_cls
        recipe_name = 'muse_' + recipe_name
        recipe_cls = get_recipe_cls(recipe_name)

        # get the list of nights to process
        if night_list is not None:
            night_list = [parse_date(night) for night in night_list]
        else:
            whereclause = (self.raw.table.c.DPR_TYPE == recipe_cls.DPR_TYPE)
            night_list = self.select_column('night', distinct=True,
                                            whereclause=whereclause)
        night_list = list(sorted(night_list))

        self.run_recipe(recipe_cls, night_list, by_night=True,
                        skip_processed=skip_processed, **kwargs)
