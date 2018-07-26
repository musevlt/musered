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
@click.option('--debug', is_flag=True, help='Debug mode')
@click.option('--list-datasets', is_flag=True, help='List datasets')
@click.option('--list-nights', is_flag=True, help='List nights')
@click.option('--settings', default='settings.yml', envvar='MUSERED_SETTINGS',
              help='Settings file, default to settings.yml')
@click.pass_context
def cli(ctx, debug, list_datasets, list_nights, settings):
    """Muse data reduction."""

    if debug:
        logging.getLogger('musered').setLevel('DEBUG')
        logging.getLogger('musered').handlers[0].setLevel('DEBUG')
        logging.getLogger('astropy').setLevel('DEBUG')

        def run_pdb(type, value, tb):
            import pdb
            import traceback
            traceback.print_exception(type, value, tb)
            pdb.pm()

        sys.excepthook = run_pdb

    if not os.path.isfile(settings):
        logger.error("settings file '%s' not found", settings)
        sys.exit(1)

    ctx.obj = mr = MuseRed(settings)
    logger.info('Musered version %s', __version__)
    # mr.debug = debug

    if list_datasets:
        mr.list_datasets()
    elif list_nights:
        mr.list_nights()


@click.option('--force', is_flag=True, help='force update for existing rows')
@click.pass_obj
def update_db(mr, force):
    """Create or update the database containing FITS keywords."""
    logger.info('Updating the database from the %s directory', mr.raw_path)
    mr.update_db(force=force)


@click.argument('dateobs', nargs=-1)
@click.pass_obj
def info(mr, dateobs):
    """Create or update the database containing FITS keywords."""
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


for cmd in (info, retrieve_data, update_db, process_calib):
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
