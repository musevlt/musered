import click
import logging
import os
import sys
from astroquery.eso import Eso


@click.argument('dataset', nargs=-1)
@click.option('--username', help='username')
@click.option('--dry-run', is_flag=True)
@click.pass_context
def retrieve_data(ctx, dataset, username, dry_run):
    """Retrieve files from DATASET from the ESO archive."""

    logger = logging.getLogger(__name__)
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
        if dry_run:
            print(table)
        else:
            eso.retrieve_data(table['DP.ID'], destination=mr.rawpath,
                              with_calib='raw')

    # ctx.invoke(update_database)
