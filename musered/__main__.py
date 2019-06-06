import click
import importlib
import logging
import os
import sys
import yaml

from .musered import MuseRed
from .scripts.retrieve_data import retrieve_data, check_integrity
from .scripts.update_qa import update_qa
from .scripts.shell import shell
from .version import __version__

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

logger = logging.getLogger(__name__)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__)
@click.option(
    "--redversion",
    help="version of the reduction (overrides the " "version in settings",
)
@click.option("--loglevel", help="log level (debug, info, warning, etc.)")
@click.option("--drslevel", help="log level for the DRS")
@click.option(
    "--settings",
    default="settings.yml",
    envvar="MUSERED_SETTINGS",
    help="settings file, default to settings.yml",
)
@click.option("--pdb", is_flag=True, help="run pdb if an exception occurs")
@click.option("--debug", is_flag=True, help="debug log level + pdb")
@click.pass_context
def cli(ctx, redversion, loglevel, drslevel, settings, pdb, debug):
    """Main MuseRed command.

    See the help of the sub-commands for more details.

    By default musered tries to read a settings file (``settings.yml``) in the
    current directory. This file can also be set with ``--settings``, or with
    the ``MUSERED_SETTINGS`` environment variable.

    The logging level can be set in the settings file, and overridden with
    ``--loglevel``.

    """
    if not os.path.isfile(settings):
        logger.error("settings file '%s' not found", settings)
        sys.exit(1)

    if debug:
        loglevel = "debug"
        pdb = True

    if loglevel is not None:
        if loglevel.lower() == "debug":
            # this is for astroquery, but could be done better..
            logging.getLogger("astropy").setLevel("DEBUG")

    try:
        ctx.obj = mr = MuseRed(settings, version=redversion, loglevel=loglevel)
    except Exception as e:
        logger.error("failed to create the Musered object: %s", e)
        if debug or pdb:
            raise
        sys.exit(1)

    if drslevel is not None:
        mr.set_loglevel(drslevel, cpl=True)

    logger.debug("Musered version %s", __version__)

    if pdb:

        def run_pdb(type, value, tb):
            import pdb
            import traceback

            traceback.print_exception(type, value, tb)
            pdb.pm()

        sys.excepthook = run_pdb


@click.option("-f", "--force", is_flag=True, help="force update for existing rows")
@click.pass_obj
def update_db(mr, force):
    """Create or update the database containing FITS keywords."""
    logger.info("Updating the database from the %s directory", mr.raw_path)
    mr.update_db(force=force)


@click.option("--type", multiple=True, help="type of file to parse (DPR.TYPE)")
@click.option("--recipe", help="recipe for which files are parsed")
@click.option("-f", "--force", is_flag=True, help="force update for existing rows")
@click.pass_obj
def update_qc(mr, type, recipe, force):
    """Create or update the database containing QC keywords."""
    logger.info("Updating the QC tables")
    mr.update_qc(dpr_types=type, recipe_name=recipe, force=force)


@click.option("--datasets", is_flag=True, help="list all datasets")
@click.option("--nights", is_flag=True, help="list all nights")
@click.option("--runs", is_flag=True, help="list all runs")
@click.option("--calibs", is_flag=True, help="list calibration sequences")
@click.option("--exps", is_flag=True, help="list all exposures")
@click.option("--qc", help="show QC keywords")
@click.option("--date", multiple=True, help="show info for a given date")
@click.option("--run", help="show info for a given run")
@click.option(
    "--excluded", is_flag=True, help="show excluded exps (for the main info report)"
)
@click.option(
    "--tables",
    default="raw,calib,science",
    help="tables to show, comma-separated list, allowed values are "
    "raw, calib, and science. By default all tables are displayed.",
)
@click.option("--no-header", is_flag=True, help="hide header")
@click.pass_obj
def info(
    mr, datasets, nights, runs, calibs, exps, qc, date, run, excluded, tables, no_header
):
    """Print info about raw and reduced data, or night or exposure."""

    if any([datasets, nights, exps, runs, calibs]):
        if datasets:
            mr.list_datasets()
        if nights:
            mr.list_nights()
        if runs:
            mr.list_runs()
        if calibs:
            mr.list_calibs()
        if exps:
            mr.list_exposures()
    elif qc:
        mr.info_qc(qc, date_list=date)
    else:
        mr.info(
            date_list=date,
            run=run,
            filter_excludes=not excluded,
            show_tables=tables.split(","),
            header=not no_header,
        )


@click.option(
    "-m",
    "--mode",
    default="summary",
    help="display mode",
    type=click.Choice(["summary", "list", "detail"]),
)
@click.option("-d", "--date", multiple=True, help="show info for a given date")
@click.option("-r", "--recipe", multiple=True, help="recipe name to show")
@click.pass_obj
def info_warnings(mr, mode, date, recipe):
    """Print warnings.

    - ``--mode summary`` prints a table with the number of warnings per recipe
      and exposure name.

    - ``--mode list`` prints the list of exposures with warnings, with the log
      filename.

    - ``--mode detail`` prints all warnings for each exposure.

    """
    mr.info_warnings(date_list=date, recipes=recipe, mode=mode)


@click.argument("select", nargs=-1)
@click.pass_obj
def info_raw(mr, select):
    """Print a table with raw exposures.

    The displayed files can be limited to the result of a query, with key:value
    items passed as arguments. Example::

        $ musered info-raw DPR_CATG:CALIB night:2017-06-18

    """
    kw = dict([item.split(":") for item in select])
    mr.info_raw(**kw)


@click.argument("exp", nargs=-1)
@click.option("--night", is_flag=True, help="show reduction log for a night")
@click.option("--short", is_flag=True, help="shortened output for --exp")
@click.option("-r", "--recipe", multiple=True, help="recipe name to show")
@click.pass_obj
def info_exp(mr, exp, night, short, recipe):
    """Show reduction log for a night or exposure.

    Example::

        $ musered info-exp 2017-06-16T01:34:56.867

        $ musered info-exp --night --short 2017-06-17

    """
    if night:
        dateobs = mr.prepare_dates(exp, datecol="name", table="reduced")
        show_weather = False
    else:
        dateobs = mr.prepare_dates(exp, datecol="name")
        show_weather = True

    for date in dateobs:
        mr.info_exp(date, full=not short, recipes=recipe, show_weather=show_weather)


@click.option("-r", "--recipe", multiple=True)
@click.option("-d", "--date", multiple=True)
@click.option("-n", "--night", multiple=True)
@click.option("--force", is_flag=True, help="nothing is done if this is not set")
@click.option("--keep-files", is_flag=True, help="do not delete files")
@click.pass_obj
def clean(mr, recipe, date, night, force, keep_files):
    """Remove data and database entries for a given recipe and dates."""
    mr.clean(
        recipe_list=recipe,
        date_list=date,
        night_list=night,
        remove_files=not keep_files,
        force=force,
    )


@click.argument("date", nargs=-1)
@click.option("-f", "--force", is_flag=True, help="force re-processing nights")
@click.option("--dry-run", is_flag=True, help="do not run the recipe")
@click.option("--bias", is_flag=True, help="run muse_bias")
@click.option("--dark", is_flag=True, help="run muse_dark")
@click.option("--flat", is_flag=True, help="run muse_flat")
@click.option("--wavecal", is_flag=True, help="run muse_wavecal")
@click.option("--lsf", is_flag=True, help="run muse_lsf")
@click.option("--twilight", is_flag=True, help="run muse_twilight")
@click.pass_obj
def process_calib(mr, date, force, dry_run, bias, dark, flat, wavecal, lsf, twilight):
    """Process calibrations (bias, dark, flat, etc.) for given nights.

    By default, process calibrations for all nights, and all types except dark.
    Already processed calibrations are skipped unless using ``--force``.

    """
    if len(date) == 0:
        date = None

    # if no option was given, run all steps
    run_all = not any([bias, dark, flat, wavecal, lsf, twilight])

    for step in ("bias", "dark", "flat", "wavecal", "lsf", "twilight"):
        if locals()[step] or (step != "dark" and run_all):
            if force:
                mr.clean(f"muse_{step}", date_list=date, remove_files=False, force=True)
            mr.process_calib(step, dates=date, skip=not force, dry_run=dry_run)


@click.argument("date", nargs=-1)
@click.option("-f", "--force", is_flag=True, help="force re-processing exposures")
@click.option("--dry-run", is_flag=True, help="do not run the recipe")
@click.option("--scibasic", is_flag=True, help="run muse_scibasic")
@click.option("--standard", is_flag=True, help="run muse_standard")
@click.option("--scipost", is_flag=True, help="run muse_scipost")
@click.option("--makecube", is_flag=True, help="run muse_scipost_make_cube")
@click.option("--superflat", is_flag=True, help="run superflat")
@click.option("--zap", is_flag=True, help="run zap")
@click.option("--params", help="name of the parameters block")
@click.option("--dataset", help="process exposures for a given dataset")
@click.pass_obj
def process_exp(
    mr,
    date,
    force,
    dry_run,
    scibasic,
    standard,
    scipost,
    makecube,
    superflat,
    zap,
    params,
    dataset,
):
    """Run recipes for science exposures.

    By default, run scibasic, standard, and scipost, for all exposures.
    Already processed exposures are skipped unless using ``--force``.

    """
    if len(date) == 0:
        date = None

    kwargs = dict(dates=date, skip=not force, params_name=params, dry_run=dry_run)
    run_all = not any([scibasic, standard, scipost, makecube, superflat, zap])

    if scibasic or run_all:
        # if force:
        #     mr.clean('scibasic', date_list=date, remove_files=False)
        mr.process_exp("scibasic", dataset=dataset, **kwargs)

    if standard or run_all:
        # if force:
        #     mr.clean('standard', date_list=date, remove_files=False)
        mr.process_standard(**kwargs)

    if scipost or run_all:
        # if force:
        #     mr.clean('scipost', date_list=date, remove_files=False)
        mr.process_exp("scipost", dataset=dataset, **kwargs)

    if makecube:
        # if force:
        #     mr.clean('scipost_make_cube', date_list=date, remove_files=False)
        mr.process_exp("scipost_make_cube", dataset=dataset, **kwargs)

    if superflat:
        mr.process_exp("superflat", dataset=dataset, **kwargs)

    if zap:
        mr.process_exp("zap", dataset=dataset, **kwargs)


@click.argument("dataset")
@click.option("--method", default="drs", help="method to use: drs (default) or imphot")
@click.option("--name", help="output name, default to method")
@click.option("--params", help="name of the parameters block")
@click.option(
    "--filter",
    default="white",
    help="filter to use for the images"
    " (drs only): white (default), Johnson_V, Cousins_R, Cousins_I",
)
@click.option(
    "--date",
    multiple=True,
    help="exposure to process, by default all exposures are used",
)
@click.option("-f", "--force", is_flag=True, help="force re-processing (imphot only)")
@click.option("--dry-run", is_flag=True, help="do not run the recipe")
@click.option("--njobs", default=1, help="number of parallel process (imphot)")
@click.pass_obj
def exp_align(mr, dataset, method, name, params, filter, date, force, dry_run, njobs):
    """Compute offsets between exposures."""
    if method == "drs":
        recipe_name = "muse_exp_align"
    elif method == "imphot":
        recipe_name = "imphot"
    else:
        raise ValueError(f"unknown method {method}")

    mr.exp_align(
        dataset,
        recipe_name=recipe_name,
        filt=filter,
        name=name,
        params_name=params,
        exps=date,
        force=force,
        dry_run=dry_run,
        n_jobs=njobs,
    )


@click.argument("dataset")
@click.option("--params", help="name of the parameters block")
@click.option(
    "--method",
    default="drs",
    help="method to use: drs (default) "
    "or mpdaf. This can be overridden in the settings file.",
)
@click.option("--name", help='output name, default to "{dataset}_{recipe}"')
@click.option("--dry-run", is_flag=True, help="do not run the recipe")
@click.option("-f", "--force", is_flag=True, help="force re-processing")
@click.pass_obj
def exp_combine(mr, dataset, method, params, name, dry_run, force):
    """Compute offsets between exposures."""
    if method == "drs":
        recipe_name = "muse_exp_combine"
    elif method == "mpdaf":
        recipe_name = "mpdaf_combine"
    else:
        raise ValueError(f"unknown method {method}")

    mr.exp_combine(
        dataset,
        params_name=params,
        recipe_name=recipe_name,
        name=name,
        dry_run=dry_run,
        force=force,
    )


@click.argument("run", nargs=-1)
@click.option("--params", help="name of the parameters block")
@click.option("-f", "--force", is_flag=True, help="force re-processing")
@click.pass_obj
def std_combine(mr, run, params, force):
    """Combine std exposures for a given run."""
    if len(run) == 0:
        run = mr.runs
    mr.std_combine(run, params_name=params, force=force)


for cmd in (
    info,
    info_warnings,
    info_raw,
    info_exp,
    clean,
    retrieve_data,
    update_db,
    update_qc,
    process_calib,
    update_qa,
    process_exp,
    exp_align,
    exp_combine,
    shell,
    check_integrity,
    std_combine,
):
    cli.command(context_settings=CONTEXT_SETTINGS)(cmd)

# loading plugins
cfg = os.path.join(click.get_app_dir("musered", force_posix=True), "plugins.yml")
if os.path.exists(cfg):
    with open(cfg) as f:
        conf = yaml.safe_load(f)
    plugins = conf.get("plugins", {})
    for path in plugins.get("paths"):
        sys.path.insert(0, path)

    try:
        for line in plugins.get("commands"):
            modname, cmdname = line.split(":")
            mod = importlib.import_module(modname)
            cmd = getattr(mod, cmdname)
            cmd = click.command(context_settings=CONTEXT_SETTINGS)(cmd)
            logger.debug("Loading command %s from %s", cmdname, modname)
            cli.add_command(cmd)
    finally:
        for path in plugins.get("paths"):
            sys.path.remove(path)

try:
    from click_repl import register_repl

    register_repl(cli)
except ImportError:
    pass


def main():
    cli(prog_name="musered")


if __name__ == "__main__":
    main()
