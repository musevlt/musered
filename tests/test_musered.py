import glob
import logging
import os
import pytest
import textwrap
from click.testing import CliRunner

from musered import get_recipe_cls
from musered.__main__ import cli
from musered.utils import parse_raw_keywords, parse_qc_keywords

CURDIR = os.path.dirname(os.path.abspath(__file__))


def test_help(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    out = out[out.index('Commands:'):]
    assert len(out) > 10


def test_get_astropy_table(mr):
    tbl = mr.get_astropy_table('raw', indexes=['name'])
    assert len(tbl) == 155
    assert tbl.colnames[:10] == [
        'id', 'name', 'filename', 'path', 'night', 'run', 'ARCFILE',
        'DATE_OBS', 'EXPTIME', 'MJD_OBS']
    assert tbl.loc['2017-06-18T22:08:29.111']


def test_select_column(mr):
    assert len(mr.select_column('DPR_TYPE')) == 143
    assert len(mr.select_column('DPR_TYPE', distinct=True)) == 8


def test_select_date(mr):
    assert mr.select_dates('FLAT,SKY') == [
        '2017-06-18T22:07:08.110',
        '2017-06-18T22:08:29.111',
        '2017-06-18T22:09:50.110',
        '2017-06-18T22:11:12.111'
    ]
    assert mr.select_dates('MASTER_BIAS', table='reduced') == [
        '2017-06-16T10:40:27',
        '2017-06-18T11:03:09',
        '2017-06-20T10:38:50'
    ]


def test_process_calib(mr, caplog):
    caplog.set_level(logging.INFO)
    runner = CliRunner()
    result = runner.invoke(cli, ['process-calib', '--dry-run'])
    assert result.exit_code == 0
    assert [rec.message for rec in caplog.records] == textwrap.dedent("""\
        Running muse_bias for 3 calibration sequences
        Already processed, nothing to do
        Running muse_flat for 3 calibration sequences
        Already processed, nothing to do
        Running muse_wavecal for 3 calibration sequences
        Already processed, nothing to do
        Running muse_lsf for 3 calibration sequences
        Already processed, nothing to do
        Running muse_twilight for 1 calibration sequences
        Already processed, nothing to do
    """).splitlines()


def test_process_exp(mr, caplog):
    caplog.set_level(logging.INFO)
    runner = CliRunner()
    result = runner.invoke(cli, ['process-exp', '--dry-run'])
    assert result.exit_code == 0
    assert [rec.message for rec in caplog.records] == textwrap.dedent("""\
        Running muse_scibasic for 6 exposures
        Already processed, nothing to do
        Running muse_scibasic for 1 exposures
        Already processed, nothing to do
        Running muse_standard for 1 exposures
        Already processed, nothing to do
        Running muse_scipost for 6 exposures
        Already processed, nothing to do
    """).splitlines()


def test_clean(mr, caplog):
    caplog.set_level(logging.INFO)
    runner = CliRunner()
    result = runner.invoke(cli, ['clean', '-r', 'bias'])
    assert result.exit_code == 0
    assert [rec.message for rec in caplog.records] == textwrap.dedent("""\
        Dry-run mode, nothing will be done
        Would remove 4 exposures/nights from the database
    """).splitlines()

    caplog.clear()
    result = runner.invoke(cli, ['clean', '-n', '2017-06-13'])
    assert result.exit_code == 0
    assert [rec.message for rec in caplog.records] == textwrap.dedent("""\
        Dry-run mode, nothing will be done
        Would remove 1 exposures/nights from the database
    """).splitlines()


def test_frames(mr, monkeypatch):
    if not os.path.exists(mr.conf['muse_calib_path']):
        pytest.skip('static calib directory is missing')

    frames = mr.frames
    assert 'raman_lines.fits' in frames.static_files
    assert frames.static_by_catg['RAMAN_LINES'] == ['raman_lines.fits']

    assert frames.is_valid('2017-06-16T10:40:27')
    assert frames.is_valid('2017-06-16T10:40:27', DPR_TYPE='MASTER_BIAS')
    assert not mr.frames.is_valid('2017-06-14T09:01:03')

    assert frames.get_static('STD_FLUX_TABLE').endswith('std_flux_table.fits')
    assert frames.get_static('GEOMETRY_TABLE')\
        .endswith('geometry_table_wfm_gto17.fits')
    assert frames.get_static('GEOMETRY_TABLE', date='2017-09-21')\
        .endswith('geometry_table_wfm_gto19.fits')

    def mockglob(path):
        # monkey patch glob which is used to return the list of files
        return [path] * 24

    with monkeypatch.context() as m:
        m.setattr(glob, 'glob', mockglob)
        res = frames.find_calib('2017-06-17', 'MASTER_BIAS', 'WFM-AO-N')
        assert len(res) == 24
        assert res[0].endswith(
            '2017-06-18T11:03:09.WFM-AO-N/MASTER_BIAS*.fits')

    # test night with excluded MASTER_BIAS, should raise an error
    with pytest.raises(ValueError):
        frames.find_calib('2017-06-13', 'MASTER_BIAS', 'WFM-AO-N')

    # test night without MASTER_BIAS, should raise an error
    with pytest.raises(ValueError):
        res = frames.find_calib('2017-06-18', 'MASTER_BIAS', 'WFM-AO-N')

    # now allow a 1 day offset
    with monkeypatch.context() as m:
        m.setattr(glob, 'glob', mockglob)
        res = frames.find_calib('2017-06-18', 'MASTER_BIAS', 'WFM-AO-N',
                                day_off=1)
        assert len(res) == 24
        assert res[0].endswith(
            '2017-06-20T10:38:50.WFM-AO-N/MASTER_BIAS*.fits')

    def mockisfile(path):
        # monkey patch isfile
        print(path)
        return True

    recipe_cls = get_recipe_cls('scipost')
    recipe = mr._instantiate_recipe(recipe_cls, recipe_cls.recipe_name)
    recipe_conf = mr._get_recipe_conf('muse_scipost')
    with monkeypatch.context() as m:
        m.setattr(glob, 'glob', mockglob)
        m.setattr(os.path, 'isfile', mockisfile)
        res = frames.get_frames(recipe, night='2017-06-17',
                                ins_mode='WFM-AO-N', recipe_conf=recipe_conf)
    assert sorted(res.keys()) == [
        'ASTROMETRY_WCS', 'EXTINCT_TABLE', 'FILTER_LIST', 'LSF_PROFILE',
        'OFFSET_LIST', 'RAMAN_LINES', 'SKY_LINES', 'STD_RESPONSE',
        'STD_TELLURIC']


def test_illum(mr, caplog):
    caplog.set_level(logging.DEBUG)

    # normal case, returns the closest illum
    assert mr.find_illum('2017-06-15', 12.53, 57920.06) == \
        './raw/MUSE.2017-06-16T01:25:02.867.fits.fz'
    assert mr.find_illum('2017-06-15', 12.5, 57920.06) == \
        './raw/MUSE.2017-06-16T01:57:38.868.fits.fz'

    # only one illum < 2h
    caplog.clear()
    mr.set_loglevel('DEBUG')
    assert mr.find_illum('2017-06-15', 12.53, 57920.05906096 - 1.5/24) == \
        './raw/MUSE.2017-06-16T01:25:02.867.fits.fz'
    assert caplog.records[0].message == 'Only one ILLUM in less than 2h'
    mr.set_loglevel('INFO')

    # another night, no illum
    caplog.clear()
    assert mr.find_illum('2017-06-14', 11, 57920.06) is None
    assert caplog.records[0].message == 'No ILLUM found'

    # time diff > 2h, close temp
    caplog.clear()
    assert mr.find_illum('2017-06-15', 12.5, 57919) == \
        './raw/MUSE.2017-06-16T01:25:02.867.fits.fz'
    assert caplog.records[0].message == 'No ILLUM in less than 2h'

    # time diff > 2h, temp diff > 1
    caplog.clear()
    assert mr.find_illum('2017-06-15', 11, 57919) is None
    assert caplog.records[0].message == 'No ILLUM in less than 2h'
    assert caplog.records[2].message == \
        'ILLUM with Temp difference > 1°, not using it'

    # temp diff > 1, found one but returns nothing
    caplog.clear()
    assert mr.find_illum('2017-06-15', 11, 57920.06) is None
    assert caplog.records[0].message.startswith('Found ILLUM')


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


def test_flags(mr_memory):
    flags = mr_memory.flags

    # check custom flag defined in settings
    assert 'MY_FLAG' in flags.names

    # add flags to an exposure or a list of exposures
    flags.add('2017-06-16T01:34:56.867',
              flags.BAD_SLICE, flags.SLICE_GRADIENT)
    flags.add(['2017-06-16T01:34:56.867', '2017-06-16T01:40:40.868',
               '2017-06-16T01:43:32.868'], flags.SHORT_EXPTIME)

    # remove flag
    flags.remove('2017-06-16T01:43:32.868', flags.SHORT_EXPTIME)

    # raise error if flag is not set
    # with pytest.raises(ValueError):
    #     flags.remove('2017-06-16T01:43:32.868', flags.BAD_IMAQUALITY)

    # do not raise error is ignore_missing is True
    flags.remove('2017-06-16T01:43:32.868', flags.BAD_IMAQUALITY)

    # list flags for exposures
    assert flags.list('2017-06-16T01:34:56.867') == [
        flags.BAD_SLICE, flags.SHORT_EXPTIME, flags.SLICE_GRADIENT]
    assert (
        flags.list(['2017-06-16T01:40:40.868', '2017-06-16T01:43:32.868']) ==
        [[flags.SHORT_EXPTIME], []]
    )

    # query exposures with a set of flags
    assert (flags.find(flags.SHORT_EXPTIME, flags.BAD_SLICE) ==
            ['2017-06-16T01:34:56.867', '2017-06-16T01:40:40.868'])
    assert (flags.find(flags.SHORT_EXPTIME, flags.BAD_SLICE, _and=True) ==
            ['2017-06-16T01:34:56.867'])
    # assert (flags.find(flags.SHORT_EXPTIME, flags.BAD_SLICE, _not=True) ==
    #         ['2017-06-16T01:43:32.868'])
