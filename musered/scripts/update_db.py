import click
import logging
import os
from astropy.io import fits
from collections import OrderedDict
from os.path import basename

from ..utils import get_exp_name, exp2datetime, NOON, ONEDAY, ProgressBar

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


def iter_fits_files(path):
    for root, dirs, files in os.walk(path):
        for f in files:
            if f.endswith(('.fits', '.fits.fz')):
                yield os.path.join(root, f)


def get_keywords(filenames, bar=None):
    keywords = [k.split('/')[0].strip()
                for k in FITS_KEYWORDS.splitlines() if k]

    for f in filenames:
        # hdr = fits.getheader(f, ext=0, ignore_missing_end=True)
        hdr = fits.getheader(f, ext=0)

        # if tablename in ('std_response', 'std_telluric'):
        #     match = NIGHT_PATTERN.search(f)
        #     if match:
        #         night = datetime.date(*[int(x) for x in match.groups()])

        # match = GTO_PATTERN.search(f)
        # run = match.groups()[0] if match else ''
        keys = OrderedDict([
            ('name', get_exp_name(f)),
            ('filename', basename(f)),
            # ('filepath', f),
            # ('run', run),
        ])

        if 'DATE-OBS' in hdr:
            date = exp2datetime(hdr['DATE-OBS'])
            night = date.date()
            # Same as MuseWise
            if date.time() < NOON:
                night -= ONEDAY
            keys['night'] = night

        for key in keywords:
            col = key[4:] if key.startswith('ESO ') else key
            col = col.replace(' ', '_').replace('-', '_')
            val = hdr.get(key)
            if val is not None:
                keys[col] = val

        if bar:
            bar.update()
        yield keys


@click.pass_context
def update_db(ctx):
    """Ingest FITS keywords."""

    logger = logging.getLogger(__name__)
    mr = ctx.obj
    table = mr.db['raw']
    flist = list(iter_fits_files(mr.rawpath))
    logger.info('found %d FITS files', len(flist))

    with ProgressBar(total=len(flist)) as bar:
        table.insert_many(get_keywords(flist, bar=bar))
