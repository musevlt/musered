import click
import logging
import os
import sys
from astroquery.eso import Eso


@click.argument('dataset', nargs=-1)
@click.option('--username', help='username for the ESO archive')
@click.option('--help-query', is_flag=True, help="print query options")
@click.option('--dry-run', is_flag=True, help="don't retrieve files")
@click.option('--no-update-db', is_flag=True, help="don't update the database")
@click.pass_obj
def retrieve_data(mr, dataset, username, help_query, dry_run, no_update_db):
    """Retrieve files from DATASET from the ESO archive."""

    logger = logging.getLogger(__name__)
    params = mr.conf['retrieve_data']
    if username is not None:
        params = {**params, 'username': username}

    eso = Eso()

    if help_query:
        eso.query_instrument('muse', help=True)
        return

    eso.login(**params)
    os.makedirs(mr.raw_path, exist_ok=True)

    for ds in dataset:
        if ds not in mr.datasets:
            logger.error("dataset '%s' not found", ds)
            sys.exit(1)

        table = eso.query_instrument(
            'muse', column_filters=mr.datasets[ds]['archive_filter'])
        logger.info('Found %d exposures', len(table))
        logger.debug('\n'.join(table['DP.ID']))
        print(table)
        if not dry_run:
            eso.retrieve_data(table['DP.ID'], destination=mr.raw_path,
                              with_calib='raw')

    if not dry_run and not no_update_db:
        mr.update_db()
