import click
import importlib
import logging
import os
import sys
import yaml

from .musered import MuseRed
from .scripts.retrieve_data import retrieve_data
from .scripts.update_qa import update_qa
from .scripts.shell import shell
from .version import __version__

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

logger = logging.getLogger(__name__)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__)
@click.option('--redversion', help='version of the reduction (overrides the '
              'version in settings')
@click.option('--loglevel', help='log level (debug, info, warning, etc.)')
@click.option('--drslevel', help='log level for the DRS')
@click.option('--settings', default='settings.yml', envvar='MUSERED_SETTINGS',
              help='settings file, default to settings.yml')
@click.option('--pdb', is_flag=True, help='run pdb if an exception occurs')
@click.option('--debug', is_flag=True, help='debug log level + pdb')
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

    ctx.obj = mr = MuseRed(settings, version=redversion)

    if debug:
        loglevel = 'debug'
        pdb = True

    if loglevel is not None:
        mr.set_loglevel(loglevel)
        if loglevel.lower() == 'debug':
            # this is for astroquery, but could be done better..
            logging.getLogger('astropy').setLevel('DEBUG')

    if drslevel is not None:
        mr.set_loglevel(drslevel, cpl=True)

    logger.debug('Musered version %s', __version__)

    if pdb:
        def run_pdb(type, value, tb):
            import pdb
            import traceback
            traceback.print_exception(type, value, tb)
            pdb.pm()

        sys.excepthook = run_pdb


@click.option('-f', '--force', is_flag=True,
              help='force update for existing rows')
@click.pass_obj
def update_db(mr, force):
    """Create or update the database containing FITS keywords."""
    logger.info('Updating the database from the %s directory', mr.raw_path)
    mr.update_db(force=force)


@click.option('--type', multiple=True, help='type of file to parse (DPR.TYPE)')
@click.option('--recipe', help='recipe for which files are parsed')
@click.pass_obj
def update_qc(mr, type, recipe):
    """Create or update the database containing QC keywords."""
    logger.info('Updating the QC tables')
    mr.update_qc(dpr_types=type, recipe_name=recipe)


@click.argument('dateobs', nargs=-1)
@click.option('--short', is_flag=True, help='shortened output for --exp')
@click.option('--datasets', is_flag=True, help='list datasets')
@click.option('--nights', is_flag=True, help='list nights')
@click.option('--runs', is_flag=True, help='list runs')
@click.option('--exps', is_flag=True, help='list exposures')
@click.option('--raw', is_flag=True, help='list raw exposures for a night')
@click.option('--qc', help='show QC keywords')
@click.pass_obj
def info(mr, dateobs, short, datasets, nights, runs, exps, raw, qc):
    """Print info about raw and reduced data, or night or exposure."""

    if any([datasets, nights, exps, runs]):
        if datasets:
            mr.list_datasets()
        if nights:
            mr.list_nights()
        if runs:
            mr.list_runs()
        if exps:
            mr.list_exposures()
    elif raw:
        mr.info_raw(dateobs)
    elif qc:
        mr.info_qc(qc, date_list=dateobs)
    else:
        if len(dateobs) == 0:
            mr.info()
        else:
            for date in dateobs:
                mr.info_exp(date, full=not short)


@click.argument('recipe_name')
@click.argument('date', nargs=-1)
@click.option('--keep-files', is_flag=True, help='do not delete files')
@click.pass_obj
def clean(mr, recipe_name, date, keep_files):
    """Remove data and database entries for a given recipe and dates."""
    mr.clean(recipe_name, date_list=date, remove_files=not keep_files)


@click.argument('date', nargs=-1)
@click.option('-f', '--force', is_flag=True, help='force re-processing nights')
@click.option('--dry-run', is_flag=True, help='do not run the recipe')
@click.option('--bias', is_flag=True, help='run muse_bias')
@click.option('--dark', is_flag=True, help='run muse_dark')
@click.option('--flat', is_flag=True, help='run muse_flat')
@click.option('--wavecal', is_flag=True, help='run muse_wavecal')
@click.option('--lsf', is_flag=True, help='run muse_lsf')
@click.option('--twilight', is_flag=True, help='run muse_twilight')
@click.pass_obj
def process_calib(mr, date, force, dry_run, bias, dark, flat, wavecal, lsf,
                  twilight):
    """Process calibrations (bias, dark, flat, etc.) for given nights.

    By default, process calibrations for all nights, and all types except dark.
    Already processed calibrations are skipped unless using ``--force``.

    """
    if len(date) == 0:
        date = None

    # if no option was given, run all steps
    run_all = not any([bias, dark, flat, wavecal, lsf, twilight])

    for step in ('bias', 'dark', 'flat', 'wavecal', 'lsf', 'twilight'):
        if locals()[step] or (step != 'dark' and run_all):
            if force:
                mr.clean(f'muse_{step}', date_list=date, remove_files=False)
            mr.process_calib(step, dates=date, skip=not force, dry_run=dry_run)


@click.argument('date', nargs=-1)
@click.option('-f', '--force', is_flag=True,
              help='force re-processing exposures')
@click.option('--dry-run', is_flag=True, help='do not run the recipe')
@click.option('--scibasic', is_flag=True, help='run muse_scibasic')
@click.option('--standard', is_flag=True, help='run muse_standard')
@click.option('--scipost', is_flag=True, help='run muse_scipost')
@click.option('--makecube', is_flag=True, help='run muse_scipost_make_cube')
@click.option('--params', help='name of the parameters block')
@click.option('--dataset', help='process exposures for a given dataset')
@click.pass_obj
def process_exp(mr, date, force, dry_run, scibasic, standard, scipost,
                makecube, params, dataset):
    """Run recipes for science exposures.

    By default, run scibasic, standard, and scipost, for all exposures.
    Already processed exposures are skipped unless using ``--force``.

    """
    if len(date) == 0:
        date = None

    kwargs = dict(dates=date, skip=not force, params_name=params,
                  dry_run=dry_run)
    run_all = not any([scibasic, standard, scipost, makecube])

    if scibasic or run_all:
        # if force:
        #     mr.clean('scibasic', date_list=date, remove_files=False)
        mr.process_exp('scibasic', dataset=dataset, **kwargs)

    if standard or run_all:
        # if force:
        #     mr.clean('standard', date_list=date, remove_files=False)
        mr.process_standard(**kwargs)

    if scipost or run_all:
        # if force:
        #     mr.clean('scipost', date_list=date, remove_files=False)
        mr.process_exp('scipost', dataset=dataset, **kwargs)

    if makecube:
        # if force:
        #     mr.clean('scipost_make_cube', date_list=date, remove_files=False)
        mr.process_exp('scipost_make_cube', dataset=dataset, **kwargs)


@click.argument('dataset')
@click.option('--method', default='drs',
              help='method to use: drs (default) or imphot')
@click.option('--name', help='output name, default to method')
@click.option('--params', help='name of the parameters block')
@click.option('--filter', default='white', help='filter to use for the images'
              ' (drs only): white (default), Johnson_V, Cousins_R, Cousins_I')
@click.option('--date', multiple=True,
              help='exposure to process, by default all exposures are used')
@click.pass_obj
def compute_offsets(mr, dataset, method, name, params, filter, date):
    """Compute offsets between exposures."""
    mr.compute_offsets(dataset, method=method, filt=filter, name=name,
                       params_name=params, exps=date)


@click.argument('dataset')
@click.option('--params', help='name of the parameters block')
@click.option('--method', default='drs', help='method to use: drs (default) '
              'or mpdaf. This can be overridden in the settings file.')
@click.pass_obj
def exp_combine(mr, dataset, method, params):
    """Compute offsets between exposures."""
    mr.exp_combine(dataset, params_name=params, method=method, name=None)


for cmd in (info, clean, retrieve_data, update_db, update_qc, process_calib,
            update_qa, process_exp, compute_offsets, exp_combine, shell):
    cli.command(context_settings=CONTEXT_SETTINGS)(cmd)

# loading plugins
cfg = os.path.join(click.get_app_dir('musered', force_posix=True),
                   'plugins.yml')
if os.path.exists(cfg):
    with open(cfg) as f:
        conf = yaml.load(f)
    plugins = conf.get('plugins', {})
    for path in plugins.get('paths'):
        sys.path.insert(0, path)

    try:
        for line in plugins.get('commands'):
            modname, cmdname = line.split(':')
            mod = importlib.import_module(modname)
            cmd = getattr(mod, cmdname)
            cmd = click.command(context_settings=CONTEXT_SETTINGS)(cmd)
            logger.debug('Loading command %s from %s', cmdname, modname)
            cli.add_command(cmd)
    finally:
        for path in plugins.get('paths'):
            sys.path.remove(path)

try:
    from click_repl import register_repl
    register_repl(cli)
except ImportError:
    pass


def main():
    cli(prog_name='musered')


if __name__ == '__main__':
    main()
