import textwrap

from click.testing import CliRunner

from musered.__main__ import cli


def test_list_datasets(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--datasets"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Datasets:
        - IC4406 : 6 exposures
        """
    )


def test_list_runs(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--runs"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Runs:
        - GTO17 : 2017-04-01 - 2017-06-30, 6 exposures (1 flagged)
        """
    )


def test_list_nights(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--nights"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Nights:
        - 2017-04-23
        - 2017-06-13
        - 2017-06-15
        - 2017-06-17
        - 2017-06-18
        - 2017-06-19
        - 2017-10-25
        - 2017-10-26
        """
    )


def test_list_exposures(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--exps"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Exposures:
        - IC4406
          - 2017-06-16T01:34:56.867
          - 2017-06-16T01:37:47.867
          - 2017-06-16T01:40:40.868
          - 2017-06-16T01:43:32.868
          - 2017-06-16T01:46:25.866
          - 2017-06-16T01:49:19.866
        """
    )


def test_list_calibs(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info", "--calibs"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Calibrations:
        - BIAS
          - 2017-06-16T10:40:27
          - 2017-06-18T11:03:09
          - 2017-06-20T10:38:50
        - FLAT,LAMP
          - 2017-06-16T12:15:46
          - 2017-06-18T12:35:49
          - 2017-06-19T12:04:11
        - FLAT,LAMP,ILLUM
          - 2017-06-16T01:24:12
          - 2017-06-16T01:56:46
          - 2017-06-16T03:07:45
          - 2017-06-18T23:24:33
          - 2017-06-19T08:20:55
        - FLAT,SKY
          - 2017-06-18T22:04:55
        - OBJECT
          - 2017-06-16T01:34:08
        - STD
          - 2017-06-19T09:31:18
        - WAVE
          - 2017-06-16T12:32:03
          - 2017-06-18T12:51:47
          - 2017-06-19T12:20:06
        """
    )


def test_info(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
        Reduction version 0.1
        155 files

        Datasets:
        - IC4406 : 6 exposures

        Runs:
        - GTO17 : 2017-04-01 - 2017-06-30, 6 exposures (1 flagged)

        Raw data:

           name    BIAS FLAT,LAMP FLAT,LAMP,ILLUM FLAT,SKY IC4406 STD WAVE
        ---------- ---- --------- --------------- -------- ------ --- ----
        2017-06-15   11        11               3       --      6  --   15
        2017-06-17   11        11              --       --     --  --   15
        2017-06-18   --        11               2        4     --   1   15
        2017-06-19   11        --              --       --     --  --   --

        Processed calib data:

           name    bias flat lsf scibasic standard twilight wavecal
        ---------- ---- ---- --- -------- -------- -------- -------
        2017-06-15    1    3   1       --       --       --       2
        2017-06-17    1    3   1       --       --       --       2
        2017-06-18   --    3   1        1        4        2       2
        2017-06-19    1   --  --       --       --       --      --

        Processed science data:

                  name          mpdaf_combine exp_align ... scipost_rec zap
        ----------------------- ------------- --------- ... ----------- ---
        2017-06-16T01:34:56.867            --        -- ...           2  --
        2017-06-16T01:37:47.867            --        -- ...           2  --
        2017-06-16T01:40:40.868            --        -- ...           2  --
        2017-06-16T01:43:32.868            --        -- ...           2  --
        2017-06-16T01:46:25.866            --        -- ...           2  --
        2017-06-16T01:49:19.866            --        -- ...           2  --
                     IC4406_drs            --        -- ...          --  --
                   IC4406_mpdaf             5        -- ...          --   4
                OFFSET_LIST_drs            --         2 ...          --  --
        """
    )


def test_info_exp(mr, caplog):
    # test missing exp/night
    mr.set_loglevel("DEBUG")
    mr.info_exp("2017-06-20")
    assert caplog.records[0].message == "2017-06-20 not found"

    runner = CliRunner()
    result = runner.invoke(cli, ["info-exp", "2017-06-16T01:34:56.867"])
    assert result.exit_code == 0
    out = result.output.splitlines()
    for line in [
        "★ GTO logs:",
        "★ Weather Conditions:",
        "★ Recipe: muse_scibasic",
        "★ Recipe: muse_scipost_rec",
        "★ Recipe: muse_scipost",
        "★ Recipe: muse_scipost_make_cube",
    ]:
        assert line in out


def test_info_night(mr):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["info-exp", "--night", "2017-06-15", "--recipe", "bias"]
    )
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert "★ Recipe: muse_bias" in out

    result = runner.invoke(cli, ["info-exp", "--night", "2017-06-15", "--short"])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert "★ Recipe: muse_bias" in out


def test_info_raw(mr, capsys, caplog):
    runner = CliRunner()
    result = runner.invoke(cli, ["info-raw", "night:2017-06-17"])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert len(out) == 39

    result = runner.invoke(cli, ["info-raw", "night:2017-06-17", "OBJECT:BIAS"])
    assert result.exit_code == 0
    out = result.output.splitlines()
    assert len(out) == 13

    # test missing exp/night
    mr.info_raw(night="2017-06-20")
    assert caplog.records[-1].message == "Could not find exposures"


def test_info_qc(mr):
    runner = CliRunner()
    result = runner.invoke(
        cli, ["info", "--qc", "MASTER_FLAT", "--date", "2017-06-16T12:15:46"]
    )
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29  # 24 rows + header + expname

    result = runner.invoke(
        cli, ["info", "--qc", "MASTER_FLAT", "--date", "2017-06-16T*"]
    )
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29  # 24 rows + header + expname

    result = runner.invoke(cli, ["info", "--qc", "MASTER_FLAT"])
    assert result.exit_code == 0
    assert len(result.output.splitlines()) == 29 * 3  # 3 nights


def test_info_warnings(mr):
    runner = CliRunner()
    result = runner.invoke(cli, ["info-warnings"])
    assert result.exit_code == 0
    assert result.output == textwrap.dedent(
        """\
              name          muse_scipost muse_scipost_make_cube muse_wavecal
    ----------------------- ------------ ---------------------- ------------
    2017-06-16T01:34:56.867            1                      3           --
    2017-06-16T01:37:47.867            1                      3           --
    2017-06-16T01:40:40.868            1                     --           --
    2017-06-16T01:43:32.868            1                     --           --
    2017-06-16T01:46:25.866            1                     --           --
    2017-06-16T01:49:19.866            1                      3           --
    2017-06-19T12:20:06               --                     --            5
    """
    )

    result = runner.invoke(cli, ["info-warnings", "-m", "list", "-r", "muse_wavecal"])
    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "recipe_name  ...                            log_file                           ",
        "------------ ... --------------------------------------------------------------",
        "muse_wavecal ... ./reduced/0.1/logs/muse_wavecal-2018-11-14T20:03:11.243195.log",
    ]

    result = runner.invoke(
        cli, ["info-warnings", "-m", "detail", "-d", "2017-06-16T01:46:25.866"]
    )
    # cannot be fully tested since log file is not in the test directory
    assert result.exit_code == 1
    assert result.output.strip() == "muse_scipost, 2017-06-16T01:46:25.866, 1 warnings"
