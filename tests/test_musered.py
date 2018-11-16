import logging
import os
import pytest
import textwrap
from click.testing import CliRunner

from musered import MuseRed
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

                name        muse_bias muse_flat muse_lsf muse_twilight muse_wavecal
        ------------------- --------- --------- -------- ------------- ------------
        2017-06-14T09:01:03         1        --       --            --           --
        2017-06-16T10:40:27         1        --       --            --           --
        2017-06-16T12:15:46        --         3       --            --           --
        2017-06-16T12:32:03        --        --        1            --            2
        2017-06-18T11:03:09         1        --       --            --           --
        2017-06-18T12:35:49        --         3       --            --           --
        2017-06-18T12:51:47        --        --        1            --            2
        2017-06-18T22:04:55        --        --       --             2           --
        2017-06-19T12:04:11        --         3       --            --           --
        2017-06-19T12:20:06        --        --        1            --            2
        2017-06-20T10:38:50         1        --       --            --           --

        Processed standard:

                  name          muse_scibasic muse_standard
        ----------------------- ------------- -------------
        2017-06-19T09:32:26.112             1             4

        Processed science data:

                  name          mpdaf_combine ... muse_scipost_rec
        ----------------------- ------------- ... ----------------
        2017-06-16T01:34:56.867            -- ...                2
        2017-06-16T01:37:47.867            -- ...                2
        2017-06-16T01:40:40.868            -- ...                2
        2017-06-16T01:43:32.868            -- ...                2
        2017-06-16T01:46:25.866            -- ...                2
        2017-06-16T01:49:19.866            -- ...                2
                     IC4406_drs            -- ...               --
                   IC4406_mpdaf             5 ...               --
                OFFSET_LIST_drs            -- ...               --
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
    result = runner.invoke(cli, ['info', '--raw', '2017-06-17'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert len(out) == 39

    # test missing exp/night
    mr.info_raw('2017-06-20')
    assert caplog.records[0].message == \
        'Could not find exposures for 2017-06-20'


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
        '2017-06-14T09:01:03',
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
        Running muse_bias for 4 calibration sequences
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
