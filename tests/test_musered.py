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
          - 2017-06-16T01:43:32.868
          - 2017-06-16T01:46:25.866
          - 2017-06-16T01:49:19.866
          - 2017-06-16T01:40:40.868
          - 2017-06-16T01:37:47.867
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

           name    muse_bias muse_flat muse_lsf muse_twilight muse_wavecal
        ---------- --------- --------- -------- ------------- ------------
        2017-06-13         1        --       --            --           --
        2017-06-15         1         3        1            --            2
        2017-06-17         1         3        1            --            2
        2017-06-18        --         3        1             2            2
        2017-06-19         1        --       --            --           --

        Processed standard:

                  name          muse_scibasic muse_standard
        ----------------------- ------------- -------------
        2017-06-19T09:32:26.112             1             4

        Processed science data:

                  name          muse_exp_align ... muse_scipost_rec
        ----------------------- -------------- ... ----------------
        2017-06-16T01:34:56.867             -- ...                2
        2017-06-16T01:37:47.867             -- ...                2
        2017-06-16T01:40:40.868             -- ...                2
        2017-06-16T01:43:32.868             -- ...                2
        2017-06-16T01:46:25.866             -- ...                2
        2017-06-16T01:49:19.866             -- ...                2
                OFFSET_LIST_drs              2 ...               --
                            drs             -- ...               --
                          mpdaf             -- ...               --
        """)


def test_info_exp(mr, capsys, caplog):
    # test missing exp/night
    mr.info_exp('2017-06-20')
    assert caplog.records[0].message == '2017-06-20 not found'

    runner = CliRunner()
    result = runner.invoke(cli, ['info', '2017-06-16T01:34:56.867'])
    assert result.exit_code == 0
    out = result.output.splitlines()
    for line in ['★ GTO logs:',
                 '★ Weather Conditions:',
                 '★ Recipe: muse_scibasic',
                 '★ Recipe: muse_scipost_rec',
                 '★ Recipe: muse_scipost',
                 '★ Recipe: muse_scipost_make_cube']:
        assert line in out


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


# FIXME: update with qc from merged files
# def test_info_qc(mr, capsys):
#     mr.info_qc('MASTER_FLAT', date_list='2017-06-17')
#     captured = capsys.readouterr()
#     assert len(captured.out.splitlines()) == 26  # 24 rows + header

#     mr.info_qc('MASTER_FLAT')
#     captured = capsys.readouterr()
#     assert len(captured.out.splitlines()) == 26 * 3  # 3 nights


def test_get_table(mr):
    tbl = mr.get_table('raw')
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
        '2017-06-13', '2017-06-15', '2017-06-17', '2017-06-19']


def test_process_calib(mr, caplog):
    caplog.set_level(logging.INFO)
    runner = CliRunner()
    result = runner.invoke(cli, ['process-calib', '--dry-run'])
    assert result.exit_code == 0
    assert [rec.message for rec in caplog.records] == textwrap.dedent("""\
        Running muse_bias for 4 nights
        Already processed, nothing to do
        Running muse_flat for 3 nights
        Already processed, nothing to do
        Running muse_wavecal for 3 nights
        Already processed, nothing to do
        Running muse_lsf for 3 nights
        Already processed, nothing to do
        Running muse_twilight for 1 nights
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
