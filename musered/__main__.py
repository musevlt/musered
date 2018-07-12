import click
import logging
import os
import sys

from .musered import MuseRed
from .scripts.retrieve_data import retrieve_data
from .scripts.update_db import update_db

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
@click.option('--list-datasets', is_flag=True, help='List datasets')
@click.option('--settings', default='settings.yml', envvar='MUSERED_SETTINGS',
              help='Settings file, default to settings.yml')
@click.pass_context
def cli(ctx, debug, list_datasets, settings):
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

    if list_datasets:
        mr.list_datasets()
        sys.exit(0)


for cmd in (retrieve_data, update_db):
    cmd = click.command(context_settings=CONTEXT_SETTINGS)(cmd)
    cli.add_command(cmd)


def main():
    cli(prog_name='musered')


if __name__ == '__main__':
    main()
