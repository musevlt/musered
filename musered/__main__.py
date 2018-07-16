import click
import logging
import os
import sys

from .musered import MuseRed
from .scripts.retrieve_data import retrieve_data

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

logger = logging.getLogger(__name__)

try:
    import click_completion
    click_completion.init()
except ImportError:
    pass


@click.group(context_settings=CONTEXT_SETTINGS, invoke_without_command=True)
@click.version_option(version='0.1')
@click.option('--debug', is_flag=True, help='Debug mode')
@click.option('--info', is_flag=True, help='Information about the database')
@click.option('--list-datasets', is_flag=True, help='List datasets')
@click.option('--list-nights', is_flag=True, help='List nights')
@click.option('--settings', default='settings.yml', envvar='MUSERED_SETTINGS',
              help='Settings file, default to settings.yml')
@click.pass_context
def cli(ctx, debug, info, list_datasets, list_nights, settings):
    """Muse data reduction."""

    if debug:
        logging.getLogger('musered').setLevel('DEBUG')
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
    # mr.debug = debug

    if info:
        mr.info()
    elif list_datasets:
        mr.list_datasets()
    elif list_nights:
        mr.list_nights()


@click.option('--force', is_flag=True, help='force update for existing rows')
@click.pass_obj
def update_db(mr, force):
    """Create or update the database containing FITS keywords."""
    mr.update_db(force=force)


@click.argument('night', nargs=-1)
@click.option('--bias', is_flag=True, help='Run muse_bias')
@click.option('--dark', is_flag=True, help='Run muse_dark')
@click.option('--flat', is_flag=True, help='Run muse_flat')
@click.pass_obj
def process_calib(mr, night, bias, dark, flat):
    """Process calibrations (bias, dark, flat) for NIGHT.

    By default, process calibrations for all nights, and all types.

    """
    if len(night) == 0:
        night = None

    run_all = not any([bias, dark, flat])
    if bias or run_all:
        mr.process_calib('BIAS', night_list=night)
    if dark or run_all:
        mr.process_calib('DARK', night_list=night)
    if flat or run_all:
        mr.process_calib('FLAT,LAMP', night_list=night)


for cmd in (retrieve_data, update_db, process_calib):
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
