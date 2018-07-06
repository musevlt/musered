import click
import logging
import os
import sys
from astroquery.eso import Eso

from .musered import MuseRed

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

logger = logging.getLogger(__name__)


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

    if not os.path.isfile(settings):
        logger.error("settings file '%s' not found", settings)
        sys.exit(1)

    ctx.obj = mr = MuseRed(settings)
    # mr.debug = debug

    if list_datasets:
        mr.list_datasets()


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('dataset', nargs=-1)
@click.option('--username', help='username')
@click.pass_context
def retrieve_data(ctx, dataset, username):
    """Retrieve files from DATASET from the ESO archive."""

    mr = ctx.obj
    params = mr.conf['retrieve_data']
    if username is not None:
        params = {**params, 'username': username}

    eso = Eso()
    eso.login(**params)
    os.makedirs(mr.rawpath, exist_ok=True)

    for ds in dataset:
        if ds not in mr.datasets:
            logger.error("dataset '%s' not found", ds)
            sys.exit(1)

        table = eso.query_instrument(
            'muse', column_filters=mr.datasets[ds]['filters'])
        logger.info('Found %d exposures', len(table))
        logger.debug('\n'.join(table['DP.ID']))
        eso.retrieve_data(table['DP.ID'], destination=mr.rawpath,
                          with_calib='raw')

    # ctx.invoke(update_database)


cli.add_command(retrieve_data)


def main():
    cli(prog_name='musered')


if __name__ == '__main__':
    main()
