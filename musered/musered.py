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
from glob import glob
from mpdaf.log import setup_logging
from sqlalchemy import sql, func

from .utils import (load_yaml_config, load_db, get_exp_name,
                    parse_date, parse_datetime, NOON, ONEDAY, ProgressBar)

FITS_KEYWORDS = """
ARCFILE                  / Archive File Name
DATE-OBS                 / Observing date
EXPTIME                  / Integration time
MJD-OBS                  / Obs start
OBJECT                   / Original target
ORIGFILE                 / Original File Name
RA
DEC

ESO DPR CATG             / Observation category
ESO DPR TYPE             / Observation type
ESO INS DROT POSANG      / [deg] Derotator position angle
ESO INS MODE             / Instrument mode used.
ESO INS TEMP4 VAL        / Ambient Temperature
ESO INS TEMP7 VAL        / Right IFU Temperature 1
ESO INS TEMP11 VAL       / Left IFU Temperature 1
ESO OBS NAME             / OB name
ESO OBS START            / OB start time
ESO OBS TARG NAME        / OB target name
ESO OCS SGS AG FWHMX MED / [arcsec] AG FWHM X median value
ESO OCS SGS AG FWHMY MED / [arcsec] AG FWHM Y median value
ESO OCS SGS AG FWHMX RMS / [arcsec] AG FWHM X RMS value
ESO OCS SGS AG FWHMY RMS / [arcsec] AG FWHM Y RMS value
ESO OCS SGS FWHM MED     / [arcsec] SGS FWHM median value
ESO OCS SGS FWHM RMS     / [arcsec] SGS FWHM RMS value
ESO PRO DATANCOM         / Number of combined frames
ESO TEL AIRM END         / Airmass at end
ESO TEL AIRM START       / Airmass at start
ESO TEL AMBI WINDDIR     / [deg] Observatory ambient wind direction
ESO TEL AMBI WINDSP      / [m/s] Observatory ambient wind speed queri
ESO TEL MOON DEC
ESO TEL MOON RA
"""

# FIXME: do we need all this ?
# ESO OCS SGS AG FWHMX AVG
# ESO OCS SGS AG FWHMX MAX
# ESO OCS SGS AG FWHMX MED
# ESO OCS SGS AG FWHMX MIN
# ESO OCS SGS AG FWHMX RMS
# ESO OCS SGS AG FWHMY AVG
# ESO OCS SGS AG FWHMY MAX
# ESO OCS SGS AG FWHMY MED
# ESO OCS SGS AG FWHMY MIN
# ESO OCS SGS AG FWHMY RMS
# ESO OCS SGS FLUX AVG
# ESO OCS SGS FLUX MAX
# ESO OCS SGS FLUX MED
# ESO OCS SGS FLUX MIN
# ESO OCS SGS FLUX RMS
# ESO OCS SGS FLUX RMSPRC
# ESO OCS SGS FWHM AVG
# ESO OCS SGS FWHM MAX
# ESO OCS SGS FWHM MED
# ESO OCS SGS FWHM MIN
# ESO OCS SGS FWHM RMS
# ESO OCS SGS NOBJ
# ESO OCS SGS OFFSET DECSUM
# ESO OCS SGS OFFSET RASUM


class StaticCalib:

    def __init__(self, path, conf):
        self.path = path
        self.conf = conf

    @lazyproperty
    def files(self):
        return os.listdir(self.path)

    def _find_file(self, key, default, date=None):
        for item in self.conf:
            if key not in item:
                continue
            if date is None:
                file = item[key]
                break
            start_date = item.get('start_date', datetime.date.min)
            end_date = item.get('end_date', datetime.date.max)
            if start_date < date < end_date:
                file = item[key]
                break
        else:
            # found nothing, use default
            file = default

        if file not in self.files:
            raise ValueError(f'could not find {file}')
        return os.path.join(self.path, file)

    def badpix_table(self, date=None):
        return self._find_file('badpix_table', 'badpix_table.fits', date=date)


class MuseRed:

    def __init__(self, settings_file='settings.yml'):
        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file

        self.conf = load_yaml_config(settings_file)
        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.reduced_path = self.conf['reduced_path']
        self.log_dir = self.conf['cpl']['log_dir']

        self.db = load_db(self.conf['db'])
        self.raw = self.db['raw']
        self.reduced = self.db['reduced']

        self.static_calib = StaticCalib(self.conf['muse_calib_path'],
                                        self.conf['static_calib'])
        self.init_cpl()

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

        if 'night' not in self.raw.columns:
            print('Nothing yet.')
            return

        # uninteresting objects to exclude from the report
        excludes = ('Astrometric calibration (ASTROMETRY)', )

        # count files per night and per type
        col = self.raw.table.columns
        query = (sql.select([col.night, col.OBJECT, func.count(col.night)])
                 .where(col.night.isnot(None))
                 .group_by(col.night, col.OBJECT))

        # reorganize rows to have types (in columns) per night (rows)
        rows = defaultdict(dict)
        keys = set()
        for night, obj, count in self.db.executable.execute(query):
            if obj in excludes:
                continue
            rows[night]['night'] = night.isoformat()
            rows[night][obj] = count
            keys.add(obj)

        # set default counts
        for row, key in itertools.product(rows.values(), keys):
            row.setdefault(key, 0)

        t = Table(rows=list(rows.values()), masked=True)
        # move night column to the beginning
        t.columns.move_to_end('night', last=False)
        for col in t.columns.values()[1:]:
            col[col == 0] = np.ma.masked

        print('\nRaw data:\n')
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
                    for k in FITS_KEYWORDS.splitlines() if k]

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

            for key in keywords:
                col = key[4:] if key.startswith('ESO ') else key
                col = col.replace(' ', '_').replace('-', '_')
                val = hdr.get(key)
                if val is not None:
                    row[col] = val

            rows.append(row)

        self.raw.insert_many(rows)
        self.logger.info('inserted %d rows, skipped %d', len(rows), nskip)

        # cleanup cached attributes
        del self.nights

        for name in ('name', 'ARCFILE'):
            if not self.raw.has_index([name]):
                self.raw.create_index([name])

    def init_cpl(self):
        """Load esorex.rc settings and override with the settings file."""

        conf = self.conf['cpl']
        cpl.esorex.init()

        if conf['recipe_path'] is not None:
            cpl.Recipe.path = conf['recipe_path']
        if conf['esorex_msg'] is not None:
            cpl.esorex.log.level = conf['esorex_msg']  # file logging
        if conf['esorex_msg_format'] is not None:
            cpl.esorex.log.format = conf['esorex_msg_format']
        if conf['log_dir'] is not None:
            os.makedirs(conf['log_dir'], exist_ok=True)

        # terminal logging: disable cpl's logger as it uses the root logger.
        cpl.esorex.msg.level = 'off'
        default_fmt = '%(levelname)s - %(name)s: %(message)s'
        setup_logging(name='cpl', level=conf.get('msg', 'info').upper(),
                      color=True, fmt=conf.get('msg_format', default_fmt))

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
            if frame == 'BADPIX_TABLE':
                frames[frame] = self.static_calib.badpix_table(date=night)
            elif frame not in skip_frames:
                frames[frame] = self.find_calib(night, frame, ins_mode,
                                                day_off=day_off)

        return frames

    def get_recipe_params(self, recipe_name):
        """Return the dict of params for a recipe."""
        conf = self.conf['recipes']
        params = {**conf.get('common', {}), **conf.get(recipe_name, {})}
        params.setdefault('log_dir', self.log_dir)
        return params

    def process_calib(self, calib_type, night_list=None, skip_processed=False):
        from .recipes.calib import get_calib_cls

        # create the cpl.Recipe object
        recipe_cls = get_calib_cls(calib_type)
        recipe_name = recipe_cls.recipe_name
        params = self.get_recipe_params(recipe_name)
        self.logger.debug('params: %r', params)

        # get the list of nights to process
        if night_list is not None:
            night_list = [parse_date(night) for night in night_list]
        else:
            night_list = self.select_column(
                'night', distinct=True,
                whereclause=(self.raw.table.c.OBJECT == calib_type))
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
        recipe = recipe_cls(**params)

        for night in night_list:
            if skip_processed and night in night_processed:
                self.logger.debug('night %s already processed', night)
                continue

            res = list(self.raw.find(night=night, OBJECT=calib_type))
            flist = [o['path'] for o in res]
            ins_mode = set(o['INS_MODE'] for o in res)
            if len(ins_mode) > 1:
                raise ValueError('night with multiple INS.MODE, not supported')
            ins_mode = ins_mode.pop()
            info('night %s, %d bias files, mode=%s', night, len(flist),
                 ins_mode)

            output_dir = os.path.join(self.reduced_path, recipe.output_dir,
                                      f'{night.isoformat()}.{ins_mode}')

            calib = self.get_calib_frames(recipe, night, ins_mode, day_off=1)
            results = recipe.run(flist, output_dir=output_dir, **calib)

            self.logger.debug('Output frames : ', recipe.output_frames)
            date_run = datetime.datetime.now().isoformat()

            for out_frame in recipe.output_frames:
                # save in database for each output frame, but check before that
                # files were created for each frame (some are optional)
                flist = sorted(glob(f"{output_dir}/{out_frame}*.fits"))
                if len(flist) == 0:
                    continue
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
