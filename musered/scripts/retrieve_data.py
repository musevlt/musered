import click
import inspect
import logging
import os
import sys


@click.argument('dataset', nargs=-1)
@click.option('--username', help='username for the ESO archive')
@click.option('--help-query', is_flag=True, help="print query options")
@click.option('--dry-run', is_flag=True, help="don't retrieve files")
@click.option('--force', is_flag=True, help="request all objects")
@click.option('--no-update-db', is_flag=True, help="don't update the database")
@click.pass_obj
def retrieve_data(mr, dataset, username, help_query, dry_run, force,
                  no_update_db):
    """Retrieve files from DATASET from the ESO archive."""

    logger = logging.getLogger(__name__)
    if len(dataset) == 0:
        logger.error('You must provide at least one dataset')
        sys.exit(1)

    params = mr.conf['retrieve_data']
    if username is not None:
        params = {**params, 'username': username}

    from astroquery.eso import Eso

    if help_query:
        Eso.query_instrument('muse', help=True)
        return

    Eso.login(**params)

    Eso.ROW_LIMIT = -1

    # customize astroquery's cache location, to have it on the same device
    # as the final path
    Eso.cache_location = os.path.join(mr.raw_path, '.cache')
    os.makedirs(Eso.cache_location, exist_ok=True)

    for ds in dataset:
        if ds not in mr.datasets:
            logger.error("dataset '%s' not found", ds)
            sys.exit(1)

        conf = mr.datasets[ds]
        table = Eso.query_instrument(
            'muse',
            cache=conf.get('cache', False),
            # columns=conf.get('columns', []),  # does not work
            column_filters=conf['archive_filter']
        )
        logger.info('Found %d exposures', len(table))
        logger.debug('\n'.join(table['DP.ID']))
        print(table)
        if not dry_run:
            sig = inspect.signature(Eso.retrieve_data)
            if 'request_all_objects' in sig.parameters:
                Eso.retrieve_data(table['DP.ID'], destination=mr.raw_path,
                                  with_calib='raw', request_all_objects=force)
            else:
                Eso.retrieve_data(table['DP.ID'], destination=mr.raw_path,
                                  with_calib='raw')

    if not dry_run and not no_update_db:
        mr.update_db()
