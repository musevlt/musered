import click
import logging
import os
import sys
from astroquery.eso import Eso

from .utils import load_yaml_config

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

    logger.debug('loading settings from %s', settings)
    ctx.obj = conf = load_yaml_config(settings)
    conf['debug'] = debug

    if list_datasets:
        logger.info('Available datasets:')
        for name in conf['datasets']:
            logger.info('- %s', name)
            sys.exit(0)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.argument('dataset', nargs=-1)
@click.option('--username', help='username')
@click.pass_obj
def retrieve_data(conf, dataset, username):
    """Retrieve files from DATASET from the ESO archive."""

    params = conf['retrieve_data']
    if username is not None:
        params = {**params, 'username': username}

    eso = Eso()
    eso.login(**params)

    destination = conf['paths']['raw']
    datasets = conf['datasets']
    for ds in dataset:
        if ds not in datasets:
            logger.error("dataset '%s' not found", ds)
            sys.exit(1)

        table = eso.query_instrument('muse', column_filters=datasets[ds])
        logger.info('Found %d exposures', len(table))
        logger.debug('\n'.join(table['DP.ID']))

        eso.retrieve_data(table['DP.ID'], destination=destination,
                          with_calib='raw')


cli.add_command(retrieve_data)


def main():
    cli(obj={}, prog_name='musered')


if __name__ == '__main__':
    main()
