import click
import inspect
import logging
import os
import sys
import itertools
import pprint
from astropy.table import Table

logger = logging.getLogger(__name__)

@click.argument('date', nargs=-1)
@click.option('--sky', is_flag=True, help='update QA with sky flux')
@click.option('--recipe', help='recipe name')
@click.option('--force', is_flag=True, help="force update of database")
@click.option('--dry-run', is_flag=True, help="don't update the database")
@click.pass_obj
def update_qa(mr, date, sky, recipe, force, dry_run):
    """Update QA database."""

    if len(date) == 0:
        date = None

    kwargs = dict(dates=date, skip=not force, dry_run=dry_run, recipe_name=recipe)

    if sky:
        qa_sky(mr, **kwargs)


def qa_sky(mr, recipe_name=None, dates=None, skip=True, dry_run=False):
# get the list of dates to process
    if dates is None:
        dates = list(itertools.chain.from_iterable(mr.exposures.values()))
    else:
        dates = mr._prepare_dates(dates, 'OBJECT', 'name')

    if recipe_name is None:
        recipe_name = 'muse_scipost'
    elif not recipe_name.startswith('muse_'):
        recipe_name = 'muse_' + recipe_name

    rows = mr.reduced.find(recipe_name=recipe_name, DPR_TYPE='SKY_SPECTRUM', name=dates)
    if skip:
        exists = [row['name'] for row in mr.qa.find(BSKY={'!=':None})]
    qarows = []
    for row in rows:
        if skip and row['name'] in exists:
            continue
        skyname = row['path'] + '/SKY_SPECTRUM_0001.fits'
        skytab =  Table.read(skyname)
        skyflux = _sky(skytab)
        logger.debug('Name %s Sky %s', row['name'], skyflux)
        qarows.append({'name':row['name'], **skyflux})
    if dry_run:
        pprint.pprint(qarows)
    else:
        with mr.db as tx:
            for row in qarows:
                tx[mr.qa.name].upsert(row, ['name'])

def _sky(s):
    skyflux = {}
    for band,l1,l2 in [['BSKY',4850,6000],['VSKY',6000,8000],['RSKY',8000,9300]]:
        flux = float(s['data'][(s['lambda']>=l1) & (s['lambda']<=l2)].mean())
        skyflux[band] = flux
    return skyflux
