"""This module contains all default settings."""

RAW_FITS_KEYWORDS = """
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
ESO TEL MOON DEC         / [deg] DEC (J2000)
ESO TEL MOON RA          / [deg] RA (J2000)
ESO TPL START            / TPL start time
"""
"""
This is the list of keywords that are read from the raw FITS files and
ingested in the database.
"""

# List of static calibration frames
STATIC_FRAMES = (
    "ASTROMETRY_WCS",
    "BADPIX_TABLE",
    "EXTINCT_TABLE",
    "FILTER_LIST",
    "GEOMETRY_TABLE",
    "LINE_CATALOG",
    # 'NONLINEARITY_GAIN'
    "RAMAN_LINES",
    "SKY_LINES",
    "STD_FLUX_TABLE",
    "VIGNETTING_MASK",
)
