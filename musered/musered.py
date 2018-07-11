import logging
import os
from astropy.io import fits
from collections import OrderedDict
from sqlalchemy import sql

from .utils import (load_yaml_config, load_db,
                    get_exp_name, exp2datetime, NOON, ONEDAY, ProgressBar)

# ESO INS TEMP4 NAME = 'Ambient Temperature' / Temperature sensor name
# ESO INS TEMP7 NAME = 'Right IFU Temperature 1' / Temperature sensor nam

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
ESO INS TEMP7 VAL        / Right IFU Temperature 1
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
        self.rawpath = self.conf['paths']['raw']
        self.db = load_db(self.conf['db'])
        self.raw = self.db['raw']

    def list_datasets(self):
        self.logger.info('Available datasets:')
        for name in self.datasets:
            self.logger.info('- %s', name)

    def update_db(self):
        """Create or update the database containing FITS keywords."""

        flist = []
        for root, dirs, files in os.walk(self.rawpath):
            for f in files:
                if f.endswith(('.fits', '.fits.fz')):
                    flist.append(os.path.join(root, f))
        self.logger.info('found %d FITS files', len(flist))

        keywords = [k.split('/')[0].strip()
                    for k in FITS_KEYWORDS.splitlines() if k]

        # get the list of files already in the database
        try:
            arcfiles = [x[0] for x in self.db.executable.execute(
                sql.select([self.raw.table.c.ARCFILE]))]
        except Exception:
            arcfiles = []

        nskip = 0
        rows = []
        for f in ProgressBar(flist):
            hdr = fits.getheader(f, ext=0)
            if hdr['ARCFILE'] in arcfiles:
                nskip += 1
                continue

            row = OrderedDict([('name', get_exp_name(f)),
                               ('filename', os.path.basename(f))])

            if 'DATE-OBS' in hdr:
                date = exp2datetime(hdr['DATE-OBS'])
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

        for name in ('name', 'ARCFILE'):
            if not self.raw.has_index([name]):
                self.raw.create_index([name])
