import click
import logging
import os
import sys

from .musered import MuseRed
from .scripts.retrieve_data import retrieve_data
from .version import __version__

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

logger = logging.getLogger(__name__)

try:
    import click_completion
    click_completion.init()
except ImportError:
    pass


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(version=__version__)
@click.option('--loglevel', help='Log level (debug, info, warning, etc.)')
@click.option('--settings', default='settings.yml', envvar='MUSERED_SETTINGS',
              help='Settings file, default to settings.yml')
@click.option('--pdb', is_flag=True, help='Run pdb if an exception occurs')
@click.option('--debug', is_flag=True, help='Debug log level + pdb')
@click.pass_context
def cli(ctx, loglevel, settings, pdb, debug):
    """Main MuseRed command.

    See the help of the sub-commands for more details.

    By default musered tries to read a settings file (settings.yml) in the
    current directory. This file can also be set with --settings, or with the
    MUSERED_SETTINGS environment variable.

    The logging level can be set in the settings file, and overridden with
    --loglevel.

    """
    if not os.path.isfile(settings):
        logger.error("settings file '%s' not found", settings)
        sys.exit(1)

    ctx.obj = mr = MuseRed(settings)

    if debug:
        loglevel = 'debug'
        pdb = True

    if loglevel is not None:
        mr.set_loglevel(loglevel)
        if loglevel.lower() == 'debug':
            # this is for astroquery, but could be done better..
            logging.getLogger('astropy').setLevel('DEBUG')

    logger.info('Musered version %s', __version__)

    if pdb:
        def run_pdb(type, value, tb):
            import pdb
            import traceback
            traceback.print_exception(type, value, tb)
            pdb.pm()

        sys.excepthook = run_pdb


@click.option('--force', is_flag=True, help='force update for existing rows')
@click.pass_obj
def update_db(mr, force):
    """Create or update the database containing FITS keywords."""
    logger.info('Updating the database from the %s directory', mr.raw_path)
    mr.update_db(force=force)


@click.argument('dateobs', nargs=-1)
@click.option('--datasets', is_flag=True, help='List datasets')
@click.option('--nights', is_flag=True, help='List nights')
@click.option('--exps', is_flag=True, help='List exposures')
@click.pass_obj
def info(mr, dateobs, datasets, nights, exps):
    """Print info about raw and reduced data, or night or exposure."""

    if any([datasets, nights, exps]):
        if datasets:
            mr.list_datasets()
        if nights:
            mr.list_nights()
        if exps:
            mr.list_exposures()
    else:
        if len(dateobs) == 0:
            mr.info()
        else:
            for date in dateobs:
                mr.info_exp(date)


@click.argument('night', nargs=-1)
@click.option('--skip', is_flag=True, help='Skip already processed nights')
@click.option('--bias', is_flag=True, help='Run muse_bias')
@click.option('--dark', is_flag=True, help='Run muse_dark')
@click.option('--flat', is_flag=True, help='Run muse_flat')
@click.option('--wavecal', is_flag=True, help='Run muse_wavecal')
@click.option('--lsf', is_flag=True, help='Run muse_lsf')
@click.option('--twilight', is_flag=True, help='Run muse_twilight')
@click.pass_obj
def process_calib(mr, night, skip, bias, dark, flat, wavecal, lsf, twilight):
    """Process calibrations (bias, dark, flat, etc.) for NIGHT.

    By default, process calibrations for all nights, and all types except dark.

    """
    if len(night) == 0:
        night = None

    run_all = not any([bias, dark, flat, wavecal, lsf, twilight])
    if bias or run_all:
        mr.process_calib('bias', night_list=night, skip_processed=skip)
    if dark:
        mr.process_calib('dark', night_list=night, skip_processed=skip)
    if flat or run_all:
        mr.process_calib('flat', night_list=night, skip_processed=skip)
    if wavecal or run_all:
        mr.process_calib('wavecal', night_list=night, skip_processed=skip)
    if lsf or run_all:
        mr.process_calib('lsf', night_list=night, skip_processed=skip)
    if twilight or run_all:
        mr.process_calib('twilight', night_list=night, skip_processed=skip)


@click.argument('exp', nargs=-1)
@click.option('--skip', is_flag=True, help='Skip already processed exposures')
@click.option('--scibasic', is_flag=True, help='Run muse_scibasic')
@click.pass_obj
def process_exp(mr, exp, skip, scibasic):
    """Run recipes for science exposures.

    """
    if len(exp) == 0:
        exp = None

    run_all = not any([scibasic])
    if scibasic or run_all:
        mr.process_exp('scibasic', explist=exp, skip_processed=skip)


for cmd in (info, retrieve_data, update_db, process_calib, process_exp):
    cmd = click.command(context_settings=CONTEXT_SETTINGS)(cmd)
    cli.add_command(cmd)

try:
    from click_repl import register_repl
    register_repl(cli)
except ImportError:
    pass


def main():
    cli(prog_name='musered')


if __name__ == '__main__':
    main()
