import logging
import numpy as np
import os
import shutil
from musered.utils import (
    parse_raw_keywords, parse_qc_keywords, find_outliers_qc_chan, stat_qc_chan,
    find_outliers, dict_values, ensure_list, parse_weather_conditions
)

CURDIR = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(CURDIR, '..', 'docs', '_static')


def test_dict_values():
    d = dict(a=['foo'], b=['bar', 'baz'])
    assert dict_values(d) == ['foo', 'bar', 'baz']


def test_ensure_list():
    assert ensure_list('foo') == ['foo']
    assert ensure_list(['foo']) == ['foo']
    assert ensure_list(np.array([1, 2])) == [1, 2]


def test_parse_keywords(mr, caplog, tmpdir):
    caplog.set_level(logging.WARNING)
    testfile = os.path.join(CURDIR, 'data',
                            'MUSE.2017-06-16T01:34:56.867.fits')

    fakefile = str(tmpdir.join('fake.fits'))
    with open(fakefile, 'w', encoding='ascii') as f:
        f.write('this is an invalid file')

    rows = parse_raw_keywords([testfile, fakefile],
                              runs=mr.conf.get('runs'))
    assert len(rows) == 1
    assert caplog.records[0].message.startswith('invalid FITS file')

    row = rows[0]
    for key, expected in [('name', '2017-06-16T01:34:56.867'),
                          ('filename', 'MUSE.2017-06-16T01:34:56.867.fits'),
                          ('night', '2017-06-15'),
                          ('run', 'GTO17'),
                          ('ARCFILE', 'MUSE.2017-06-16T01:34:56.867.fits'),
                          ('DATE_OBS', '2017-06-16T01:34:56.000'),
                          ('OBJECT', 'IC4406 (white)'),
                          ('RA', 215.609208),
                          ('INS_DROT_POSANG', 135.6),
                          ('INS_MODE', 'WFM-AO-N'),
                          ('INS_TEMP11_VAL', 12.73),
                          ('OBS_NAME', 'IC4406'),
                          ('OBS_START', '2017-06-16T01:23:29'),
                          ('OBS_TARG_NAME', 'IC4406'),
                          ('OCS_SGS_AG_FWHMX_MED', 0.607),
                          ('OCS_SGS_FWHM_MED', 0.404),
                          ('PRO_DATANCOM', 24),
                          ('TEL_AIRM_END', 1.062),
                          ('TEL_AMBI_WINDDIR', 281.5),
                          ('TEL_MOON_RA', 340.834993),
                          ('TPL_START', '2017-06-16T01:34:08')]:
        assert row[key] == expected


def test_parse_qc(mr):
    testfile = os.path.join(CURDIR, 'data',
                            'MUSE.2017-06-16T01:34:56.867.fits')
    rows = parse_qc_keywords([testfile])
    assert len(rows) == 1

    row = rows[0]
    for key, expected in {
            'QC_SCIPOST_FWHM_NVALID': 6,
            'QC_SCIPOST_NDET': 6,
            'QC_SCIPOST_POS1_X': 83.0,
            'QC_SCIPOST_POS1_Y': 149.0,
            'filename': 'MUSE.2017-06-16T01:34:56.867.fits',
            'hdu': 'PRIMARY'}.items():
        assert row[key] == expected


def test_parse_weather(mr, caplog):
    parse_weather_conditions(mr)
    assert caplog.messages == ['Skipping 11 nights',
                               'Nothing to do for weather conditions']

    caplog.clear()
    parse_weather_conditions(mr, force=True)
    assert caplog.messages[1] == \
        'File ./raw/MUSE.2017-06-16T01:34:56.867.NL.txt not found'

    caplog.clear()
    shutil.copytree(os.path.join(TESTDIR, 'raw'), 'raw')
    parse_weather_conditions(mr, force=True)
    assert caplog.messages == [
        'Night 2017-06-15, ./raw/MUSE.2017-06-16T01:34:56.867.NL.txt',
        'Importing weather conditions, 11 entries']


def test_qc_outliers(mr):
    t = find_outliers_qc_chan(mr, 'qc_MASTER_BIAS',
                              [f'QC_BIAS_MASTER{k}_RON' for k in range(1, 5)])
    assert t.colnames == ['NAME', 'QC', 'CHAN', 'VAL', 'MEAN', 'STD', 'NSIGMA']
    assert len(t) == 0

    t = find_outliers_qc_chan(mr, 'qc_MASTER_FLAT',
                              [f'QC_FLAT_MASTER_SLICE{k}_MEAN' for k in
                               range(1, 3)], nsigma=2)
    assert len(t) == 7
    assert set(t['QC']) == {
        'QC_FLAT_MASTER_SLICE1_MEAN', 'QC_FLAT_MASTER_SLICE2_MEAN'}

    t = stat_qc_chan(mr, 'qc_MASTER_BIAS',
                     [f'QC_BIAS_MASTER{k}_RON' for k in range(1, 5)])
    assert t.colnames == ['CHAN', 'QC', 'MEAN', 'STD', 'NCLIP', 'NKEEP']
    assert len(t) == 96  # 24 channels * 4 quadrants

    out = find_outliers(mr.qa_reduced, 'skyB', sigma_lower=2, sigma_upper=2)
    assert out['names'] == ['2017-06-16T01:43:32.868']
