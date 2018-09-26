import click
import inspect
import logging
import os
import sys
import itertools
import pprint
from astropy.table import Table
import numpy as np
import psfrec

logger = logging.getLogger(__name__)

@click.argument('date', nargs=-1)
@click.option('--sky', is_flag=True, help='update qa_reduced table with sky flux in B,V,R')
@click.option('--sparta', is_flag=True, help='update qa_raw table with average sparta seeing and gl data')
@click.option('--psfrec', is_flag=True, help='run PSF reconstruction and update qa_raw table')
@click.option('--recipe', help='recipe name')
@click.option('--force', is_flag=True, help="force update of database")
@click.option('--dry-run', is_flag=True, help="don't update the database")
@click.pass_obj
def update_qa(mr, date, sky, sparta, psfrec, recipe, force, dry_run):
    """Update QA databases (qa_raw and qa_reduced)."""

    if len(date) == 0:
        dates = list(itertools.chain.from_iterable(mr.exposures.values()))
    else:
        dates = mr._prepare_dates(date, 'OBJECT', 'name')

    kwargs = dict(dates=dates, skip=not force, dry_run=dry_run)

    if sky:
        qa_sky(mr, recipe_name=recipe, **kwargs)
    if sparta:
        qa_sparta(mr, **kwargs)
    if psfrec:
        qa_psfrec(mr, **kwargs)


def qa_sky(mr, recipe_name=None, dates=None, skip=True, dry_run=False):

    if recipe_name is None:
        recipe_name = 'muse_scipost'
    elif not recipe_name.startswith('muse_'):
        recipe_name = 'muse_' + recipe_name

    rows = mr.reduced.find(recipe_name=recipe_name, DPR_TYPE='SKY_SPECTRUM', name=dates)
    if skip:
        exists = [row['name'] for row in mr.qa_reduced.find() if row['skyB'] is not None] 
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
                tx[mr.tables['qa_reduced']].upsert(row, ['name'])

def qa_sparta(mr, dates=None, skip=True, dry_run=False):
    rows = mr.raw.find(name=dates)
    if skip:
        exists = [row['name'] for row in mr.qa_raw.find() if row['SP_See'] is not None] 
    qarows = []
    for row in rows:
        if skip and row['name'] in exists:
            continue
        rawname = row['path'] 
        tab =  Table.read(rawname, hdu='SPARTA_ATM_DATA')
        sparta_dict = _sparta(tab)
        logger.debug('Name %s SPARTA %s', row['name'], sparta_dict)
        qarows.append({'name':row['name'], **sparta_dict})
    if dry_run:
        pprint.pprint(qarows)
    else:
        with mr.db as tx:
            for row in qarows:
                tx['qa_raw'].upsert(row, ['name'])

def qa_psfrec(mr, recipe_name=None, dates=None, skip=True, dry_run=False):
    rows = mr.raw.find(name=dates)
    if skip:
        exists = [row['name'] for row in mr.qa_raw.find() if row['PR_vers'] is not None] 
    qarows = []
    for row in rows:
        if skip and row['name'] in exists:
            continue
        rawname = row['path'] 
        psfrec_dict = _psfrec(rawname)
        logger.debug('Name %s PSFRec %s', row['name'], psfrec_dict)
        if not dry_run:
            mr.qa_raw.upsert({'name':row['name'], **psfrec_dict}, ['name'])

def _psfrec(filename):
    lbda,fwhm,beta = psfrec.reconstruct_psf(filename)
    lbref = [500,700,900]
    fwhmref = np.interp(lbref, lbda, fwhm)
    betaref = np.interp(lbref, lbda, beta)
    psfdict = {'PR_vers':psfrec.__version__, 'PR_fwhmB':fwhmref[0], 'PR_fwhmV':fwhmref[1], 'PR_fwhmR':fwhmref[2],
               'PR_betaB':betaref[0], 'PR_betaV':betaref[1], 'PR_betaR':betaref[2]}
    return psfdict


def _sky(s):
    skyflux = {}
    for band,l1,l2 in [['skyB',4850,6000],['skyV',6000,8000],['skyR',8000,9300]]:
        flux = float(s['data'][(s['lambda']>=l1) & (s['lambda']<=l2)].mean())
        skyflux[band] = flux
    return skyflux

def _sparta(tab):
    res = {}
    klist = [k for k in range(1,5) if tab[f'LGS{k}_TUR_GND'][0] > 0]
    if len(klist) < 4:
         logger.warning('Mode %d lasers detected', len(klist))
    s = [tab[f'LGS{k}_SEEING'].mean() for k in klist]
    res['SP_See'] = float(np.mean(s))
    res['SP_SeeStd'] = float(np.std(s))
    g = [tab[f'LGS{k}_TUR_GND'].mean() for k in klist]
    res['SP_Gl'] = float(np.mean(g))
    res['SP_GlStd'] = float(np.std(g))
    return res
