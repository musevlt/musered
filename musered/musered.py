import cpl
import datetime
import logging
import os
from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import OrderedDict, Counter
from mpdaf.log import ColoredFormatter
from sqlalchemy import sql

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


class MuseRed:

    def __init__(self, settings_file='settings.yml'):
        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file
        self.conf = load_yaml_config(settings_file)

        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.db = load_db(self.conf['db'])
        self.raw = self.db['raw']
        self.logdir = self.conf['cpl']['logdir']

        self.init_cpl()

    @lazyproperty
    def nights(self):
        return self.select_column('night', distinct=True)

    def list_datasets(self):
        """Print the list of datasets."""
        for name in self.datasets:
            print(f'- {name}')

    def list_nights(self):
        """Print the list of nights."""
        for x in self.nights:
            print(f'- {x:%Y-%m-%d}')

    def info(self):
        print(f'{self.raw.count()} files\n')

        print('Datasets:')
        self.list_datasets()
        print('\nNights:')
        objects = self.select_column('night')
        for obj, count in sorted(Counter(objects).items()):
            print(f'- {obj:%Y-%m-%d} : {count}')

        print('\nObjects:')
        objects = self.select_column('OBJECT')
        for obj, count in sorted(Counter(objects).items()):
            # skip uninteresting objects
            if obj in ('Bad pixel table for MUSE (BADPIX_TABLE)',
                       'Mask to signify the vignetted region in the MUSE FOV',
                       'Astrometric calibration (ASTROMETRY)',
                       'HgCd+Ne+Xe LINE_CATALOG for MUSE'):
                continue
            print(f'- {obj:15s} : {count}')

    def select_column(self, name, notnull=True, distinct=False,
                      whereclause=None):
        col = self.raw.table.c[name]
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
        if conf['msg'] is not None:
            cpl.esorex.msg.level = conf['msg']  # terminal logging
        if conf['msg_format'] is not None:
            cpl.esorex.msg.format = msg_format = conf['msg_format']
            cpl.esorex.msg.handler.setFormatter(ColoredFormatter(msg_format))
        if conf['esorex_msg_format'] is not None:
            cpl.esorex.log.format = conf['esorex_msg_format']
        if conf['logdir'] is not None:
            os.makedirs(conf['logdir'], exist_ok=True)
            # if logfilename is not None:

    def process_calib(self, calib_type, night_list=None):
        from .recipes.calib import BIAS, DARK, FLAT

        calib_cls = {'BIAS': BIAS, 'DARK': DARK, 'FLAT,LAMP': FLAT}
        if calib_type not in calib_cls:
            raise ValueError(f'invalid calib_type {calib_type}')

        recipe = calib_cls[calib_type]()

        NIGHT = self.raw.table.c.night
        OBJECT = self.raw.table.c.OBJECT

        if night_list is not None:
            night_list = [parse_date(night) for night in night_list]
        else:
            night_list = self.select_column('night', distinct=True,
                                            whereclause=(OBJECT == calib_type))

        for n in night_list:
            date = datetime.datetime.now().isoformat()
            cpl.esorex.log.filename = os.path.join(
                self.logdir, f"{calib_type}-{date}.log")

            whereclause = sql.and_(NIGHT == n, OBJECT == calib_type)
            flist = self.select_column('path', whereclause=whereclause)
            self.logger.info('night %s : %d bias files', n, len(flist))
            recipe.run(flist)
            break
