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


def test_list_datasets(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ['info', '--datasets'])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent("""\
        Datasets:
        - IC4406 : 6 exposures
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

        Raw data:

           name    BIAS DARK FLAT,LAMP FLAT,LAMP,ILLUM FLAT,SKY IC4406 STD WAVE
        ---------- ---- ---- --------- --------------- -------- ------ --- ----
        2017-06-13   11    5        --              --       --     --  --   --
        2017-06-15   11   --        11               3       --      6  --   15
        2017-06-17   11   --        11              --       --     --  --   15
        2017-06-18   --   --        11               2        4     --   1   15
        2017-06-19   11   --        --              --       --     --  --   --

        Processed data:

        Nothing yet.
        """)


def test_info_raw(mr, capsys):
    mr.info_raw('2017-06-17')
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 39


def test_info_qc(mr, capsys):
    mr.info_qc('MASTER_FLAT', date_list='2017-06-17')
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 26  # 24 rows + header

    mr.info_qc('MASTER_FLAT')
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 26 * 3  # 3 nights


def test_get_table(mr):
    tbl = mr.get_table('raw')
    assert len(tbl) == 155
    assert tbl.colnames[:10] == [
        'id', 'name', 'filename', 'path', 'night', 'ARCFILE', 'DATE_OBS',
        'EXPTIME', 'MJD_OBS', 'OBJECT']
