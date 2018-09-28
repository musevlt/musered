import os
import pytest
import textwrap
from musered import MuseRed

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   '..', 'docs', '_static')


@pytest.fixture
def mr():
    os.chdir(DIR)
    return MuseRed()


def test_list_datasets(mr, capsys):
    mr.list_datasets()
    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent("""\
        Datasets:
        - IC4406 : 6 exposures
        """)


def test_list_nights(mr, capsys):
    mr.list_nights()
    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent("""\
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


def test_list_exposures(mr, capsys):
    mr.list_exposures()
    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent("""\
        Exposures:
        - IC4406
          - 2017-06-16T01:34:56.867
          - 2017-06-16T01:43:32.868
          - 2017-06-16T01:46:25.866
          - 2017-06-16T01:49:19.866
          - 2017-06-16T01:40:40.868
          - 2017-06-16T01:37:47.867
        """)


def test_info(mr, capsys):
    mr.info()
    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent("""\
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
