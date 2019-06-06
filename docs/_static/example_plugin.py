import logging

import click


@click.argument('name')
@click.pass_obj
def my_command(mr, name):
    """Example plugin, say hello."""
    logger = logging.getLogger('musered')
    logger.info('Hello %s!', name)

    # mr is the MuseRed object, it can be used to access the database
    logger.info('raw: %d rows', mr.raw.count())
    logger.info('reduced: %d rows', mr.reduced.count())
