import glob
import logging
import os
import pytest
import textwrap
from click.testing import CliRunner

from musered import MuseRed, get_recipe_cls
from musered.__main__ import cli

CURDIR = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(CURDIR, '..', 'docs', '_static')


@pytest.fixture
def mr():
    cwd = os.getcwd()
    os.chdir(TESTDIR)
    yield MuseRed()
    os.chdir(cwd)


def test_help(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    out = out[out.index('Commands:'):]
    assert len(out) > 10


def test_list_datasets(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--datasets'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Datasets:
        - IC4406 : 6 exposures
        """)


def test_list_runs(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--runs'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Runs:
        - GTO17 : 2017-04-01 - 2017-06-30, 6 exposures
        """)


def test_list_nights(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--nights'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Nights:
        - 2017-04-23
        - 2017-06-13
        - 2017-06-15
        - 2017-06-17
        - 2017-06-18
        - 2017-06-19
        - 2017-10-25
        - 2017-10-26
        """)


def test_list_exposures(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--exps'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Exposures:
        - IC4406
          - 2017-06-16T01:34:56.867
          - 2017-06-16T01:37:47.867
          - 2017-06-16T01:40:40.868
          - 2017-06-16T01:43:32.868
          - 2017-06-16T01:46:25.866
          - 2017-06-16T01:49:19.866
        """)


def test_info(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Reduction version 0.1
        155 files

        Datasets:
        - IC4406 : 6 exposures

        Runs:
        - GTO17 : 2017-04-01 - 2017-06-30, 6 exposures

        Raw data:

           name    BIAS DARK FLAT,LAMP FLAT,LAMP,ILLUM FLAT,SKY IC4406 STD WAVE
        ---------- ---- ---- --------- --------------- -------- ------ --- ----
        2017-06-13   11    5        --              --       --     --  --   --
        2017-06-15   11   --        11               3       --      6  --   15
        2017-06-17   11   --        11              --       --     --  --   15
        2017-06-18   --   --        11               2        4     --   1   15
        2017-06-19   11   --        --              --       --     --  --   --

        Processed calib data:

           name    bias flat lsf scibasic standard twilight wavecal
        ---------- ---- ---- --- -------- -------- -------- -------
        2017-06-15    1    3   1       --       --       --       2
        2017-06-17    1    3   1       --       --       --       2
        2017-06-18   --    3   1        1        4        2       2
        2017-06-19    1   --  --       --       --       --      --

        Processed science data:

                  name          mpdaf_combine ... scipost_make_cube scipost_rec
        ----------------------- ------------- ... ----------------- -----------
        2017-06-16T01:34:56.867            -- ...                 2           2
        2017-06-16T01:37:47.867            -- ...                 2           2
        2017-06-16T01:40:40.868            -- ...                 2           2
        2017-06-16T01:43:32.868            -- ...                 2           2
        2017-06-16T01:46:25.866            -- ...                 2           2
        2017-06-16T01:49:19.866            -- ...                 2           2
                     IC4406_drs            -- ...                --          --
                   IC4406_mpdaf             5 ...                --          --
                OFFSET_LIST_drs            -- ...                --          --
        """)


def test_info_exp(mr, caplog):
    # test missing exp/night
    mr.set_loglevel('DEBUG')
    mr.info_exp('2017-06-20')
    assert caplog.records[0].message == '2017-06-20 not found'

    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--exp', '2017-06-16T01:34:56.867'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    for line in ['★ GTO logs:',
                 '★ Weather Conditions:',
                 '★ Recipe: muse_scibasic',
                 '★ Recipe: muse_scipost_rec',
                 '★ Recipe: muse_scipost',
                 '★ Recipe: muse_scipost_make_cube']:
        assert line in out


def test_info_night(mr, caplog):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--night', '2017-06-15',
                                 '--recipe', 'bias'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert '★ Recipe: muse_bias' in out

    result = runner.invoke(cli, ['info', '--night', '2017-06-15', '--short'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert '★ Recipe: muse_bias' in out


def test_info_raw(mr, capsys, caplog):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--raw', 'night:2017-06-17'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert len(out) == 39

    result = runner.invoke(cli, ['info', '--raw',
                                 'night:2017-06-17,OBJECT:BIAS'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert len(out) == 13

    # test missing exp/night
    mr.info_raw(night='2017-06-20')
    assert caplog.records[0].message == 'Could not find exposures'


def test_info_qc(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--qc', 'MASTER_FLAT',
                                 '--date', '2017-06-16T12:15:46'])
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29  # 24 rows + header + expname

    result = runner.invoke(cli, ['info', '--qc', 'MASTER_FLAT',
                                 '--date', '2017-06-16T*'])
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29  # 24 rows + header + expname

    result = runner.invoke(cli, ['info', '--qc', 'MASTER_FLAT'])
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29 * 3  # 3 nights


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
