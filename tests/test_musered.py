import glob
import logging
import os
import pytest
import textwrap
from click.testing import CliRunner

from musered import get_recipe_cls
from musered.__main__ import cli


def test_help(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    out = out[out.index('Commands:'):]
    assert len(out) > 10


def test_get_astropy_table(mr):
    tbl = mr.get_astropy_table('raw')
    assert len(tbl) == 155
    assert tbl.colnames[:10] == [
        'id', 'name', 'filename', 'path', 'night', 'run', 'ARCFILE',
        'DATE_OBS', 'EXPTIME', 'MJD_OBS']


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
