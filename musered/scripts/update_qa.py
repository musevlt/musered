import click
import itertools
import logging
import numpy as np
import pprint
from astropy.table import Table

from musered.recipes import normalize_recipe_name
from musered.utils import upsert_many

logger = logging.getLogger(__name__)


@click.argument("date", nargs=-1)
@click.option(
    "--sky", is_flag=True, help="update qa_reduced table with sky flux in B,V,R"
)
@click.option(
    "--sparta",
    is_flag=True,
    help="update qa_raw table with average sparta seeing and GL",
)
@click.option(
    "--imphot", is_flag=True, help="update qa_reduced table with imphot values"
)
@click.option(
    "--psfrec", is_flag=True, help="run PSF reconstruction and update qa_raw table"
)
@click.option("--recipe", help="recipe name")
@click.option(
    "--band", default="F775W", help="band to use for --imphot, default to F775W"
)
@click.option("--force", is_flag=True, help="force update of database")
@click.option("--dry-run", is_flag=True, help="don't update the database")
@click.pass_obj
def update_qa(mr, date, sky, sparta, imphot, psfrec, recipe, band, force, dry_run):
    """Update QA databases (qa_raw and qa_reduced)."""

    if len(date) == 0:
        dates = list(itertools.chain.from_iterable(mr.exposures.values()))
    else:
        dates = mr.prepare_dates(date, "OBJECT", "name")

    kwargs = dict(dates=dates, skip=not force, dry_run=dry_run)

    if sky:
        qa_sky(mr, recipe_name=recipe, **kwargs)
    if sparta:
        qa_sparta(mr, **kwargs)
    if psfrec:
        qa_psfrec(mr, **kwargs)
    if imphot:
        qa_imphot(mr, recipe_name=recipe, band=band, **kwargs)


def qa_imphot(mr, recipe_name=None, dates=None, skip=True, dry_run=False, band="F775W"):
    if recipe_name is None:
        recipe_name = "imphot"

    rows = list(mr.reduced.find(recipe_name=recipe_name, DPR_TYPE="IMPHOT", name=dates))
    if skip:
        exists = _find_existing_exp(mr.qa_reduced, "IM_vers")
        rows = [row for row in rows if row["name"] not in exists]
    logger.info(f"imphot: found {len(rows)} exposures in database to process")
    qarows = []
    for row in rows:
        imphot = _imphot(f"{row['path']}/IMPHOT.fits", band=band)
        imphot["IM_vers"] = row["recipe_version"]
        logger.debug("Name %s Imphot %s", row["name"], imphot)
        qarows.append({"name": row["name"], **imphot})
    if dry_run:
        pprint.pprint(qarows)
    else:
        upsert_many(mr.db, mr.qa_reduced.name, qarows, ["name"])


def qa_sky(mr, recipe_name=None, dates=None, skip=True, dry_run=False):
    if recipe_name is None:
        recipe_name = "muse_scipost"

    recipe_name = normalize_recipe_name(recipe_name)
    rows = list(
        mr.reduced.find(recipe_name=recipe_name, DPR_TYPE="SKY_SPECTRUM", name=dates)
    )
    if skip:
        exists = _find_existing_exp(mr.qa_reduced, "skyB")
        rows = [row for row in rows if row["name"] not in exists]
    logger.info(f"sky: found {len(rows)} exposures in database to process")
    qarows = []
    for row in rows:
        skyflux = _sky(f"{row['path']}/SKY_SPECTRUM_0001.fits")
        logger.debug("Name %s Sky %s", row["name"], skyflux)
        qarows.append({"name": row["name"], **skyflux})
    if dry_run:
        pprint.pprint(qarows)
    else:
        upsert_many(mr.db, mr.qa_reduced.name, qarows, ["name"])


def qa_sparta(mr, dates=None, skip=True, dry_run=False):
    rows = list(mr.raw.find(name=dates))
    if skip:
        exists = _find_existing_exp(mr.qa_raw, "SP_See")
        rows = [row for row in rows if row["name"] not in exists]
    logger.info(f"sparta: found {len(rows)} exposures in database to process")
    qarows = []
    for row in rows:
        sparta_dict = _sparta(row["path"])
        if sparta_dict is None:
            continue
        logger.debug("Name %s SPARTA %s", row["name"], sparta_dict)
        qarows.append({"name": row["name"], **sparta_dict})
    if dry_run:
        pprint.pprint(qarows)
    else:
        upsert_many(mr.db, mr.qa_raw.name, qarows, ["name"])


def qa_psfrec(mr, dates=None, skip=True, dry_run=False):
    try:
        import muse_psfr  # noqa
    except ImportError:
        logger.error("psfrec: could not find the muse-psfr package")
        return

    rows = list(mr.raw.find(name=dates))
    if skip:
        exists = _find_existing_exp(mr.qa_raw, "PR_vers")
        rows = [row for row in rows if row["name"] not in exists]
    logger.info(f"psfrec: found {len(rows)} exposures in database to process")
    for row in rows:
        psfrec_dict = _psfrec(row["path"])
        logger.debug("Name %s PSFRec %s", row["name"], psfrec_dict)
        if not dry_run:
            mr.qa_raw.upsert({"name": row["name"], **psfrec_dict}, ["name"])


def _find_existing_exp(table, key):
    if key not in table.columns:
        return []
    exists = [row["name"] for row in table.find() if row[key] is not None]
    return exists


def _psfrec(filename):
    from muse_psfr import compute_psf_from_sparta, __version__

    res = compute_psf_from_sparta(filename, lmin=500, lmax=900, nl=3)
    data = res["FIT_MEAN"].data
    fwhm, beta = data["fwhm"][:, 0], data["n"]
    return {
        "PR_vers": __version__,
        "PR_fwhmB": fwhm[0],
        "PR_fwhmV": fwhm[1],
        "PR_fwhmR": fwhm[2],
        "PR_betaB": beta[0],
        "PR_betaV": beta[1],
        "PR_betaR": beta[2],
    }


def _sky(filename):
    s = Table.read(filename)
    bands = [["skyB", 4850, 6000], ["skyV", 6000, 8000], ["skyR", 8000, 9300]]
    return {
        band: float(np.mean(s["data"][(s["lambda"] >= l1) & (s["lambda"] <= l2)]))
        for band, l1, l2 in bands
    }


def _sparta(rawname):
    try:
        tab = Table.read(rawname, hdu="SPARTA_ATM_DATA")
    except KeyError:
        logger.error(f"no SPARTA_ATM_DATA table in {rawname}")
        return

    klist = [k for k in range(1, 5) if tab[f"LGS{k}_TUR_GND"][0] > 0]
    if len(klist) < 4:
        logger.warning("Mode %d lasers detected", len(klist))

    res = {}

    s = [tab[f"LGS{k}_SEEING"].mean() for k in klist]
    res["SP_See"] = float(np.mean(s))
    res["SP_SeeStd"] = float(np.std(s))
    res["SP_SeeMin"] = float(np.min([tab[f"LGS{k}_SEEING"].min() for k in klist]))
    res["SP_SeeMax"] = float(np.max([tab[f"LGS{k}_SEEING"].max() for k in klist]))

    g = [tab[f"LGS{k}_TUR_GND"].mean() for k in klist]
    res["SP_Gl"] = float(np.mean(g))
    res["SP_GlStd"] = float(np.std(g))
    res["SP_GLMin"] = float(np.min([tab[f"LGS{k}_TUR_GND"].min() for k in klist]))
    res["SP_GLMax"] = float(np.max([tab[f"LGS{k}_TUR_GND"].max() for k in klist]))

    l = [tab[f"LGS{k}_L0"].mean() for k in klist]
    res["SP_L0"] = float(np.mean(l))
    res["SP_L0Std"] = float(np.std(l))
    res["SP_L0Min"] = float(np.min([tab[f"LGS{k}_L0"].min() for k in klist]))
    res["SP_L0Max"] = float(np.max([tab[f"LGS{k}_L0"].max() for k in klist]))
    return res


def _imphot(tabname, band="F775W"):
    tab = Table.read(tabname)
    if band not in tab["filter"]:
        raise ValueError("band {band} not found")
    row = tab[tab["filter"] == band][0]
    return {
        f"IM_{key}": row[key]
        for key in ["fwhm", "beta", "bg", "scale", "dx", "dy", "rms"]
    }
