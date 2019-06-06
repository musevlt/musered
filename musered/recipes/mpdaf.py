import logging
from os.path import join

import mpdaf
import numpy as np
from astropy.io import fits
from mpdaf.obj import CubeList, CubeMosaic

from ..utils import get_exp_name, make_band_images
from .recipe import PythonRecipe


def do_combine(
    flist,
    cube_name,
    expmap_name,
    stat_name,
    img_name,
    expimg_name,
    method="sigclip",
    nmax=2,
    nclip=5.0,
    nstop=2,
    mosaic=False,
    output_wcs=None,
    version=None,
    var="propagate",
    mad=False,
    scale_table=None,
    filter=None,
):
    logger = logging.getLogger("musered")
    logger.info("Combining %d datacubes", len(flist))

    scales = offsets = None
    if scale_table is not None:
        if not np.all([get_exp_name(f) for f in flist] == scale_table["name"]):
            raise ValueError("scales do not match exposures")
        scales = scale_table["scale"]
        offsets = scale_table["offset"]

    if mosaic:
        if method != "pysigclip":
            method = "pysigclip"
            logger.warning("mosaic combine can only be done with pysigclip")
        if output_wcs is None:
            raise ValueError("output_wcs is required for mosaic")
        logger.info("Output WCS: %s", output_wcs)
        cubes = CubeMosaic(flist, output_wcs, scalelist=scales, offsetlist=offsets)
    else:
        cubes = CubeList(flist, scalelist=scales, offsetlist=offsets)

    field = fits.getval(flist[0], "OBJECT")
    logger.info("method: %s", method)
    logger.info("field name: %s", field)
    cubes.info()

    rej = None
    header = dict(OBJECT=field, CUBE_V=version)
    if method == "median":
        cube, expmap, stat = cubes.median(header=header)
    elif method == "pymedian":
        cube, expmap, stat = cubes.pymedian(header=header)
    elif method == "sigclip":
        cube, expmap, stat = cubes.combine(
            nmax=nmax, nclip=nclip, nstop=nstop, var=var, header=header, mad=mad
        )
    elif method == "pysigclip":
        cube, expmap, stat, rej = cubes.pycombine(
            nmax=nmax, nclip=nclip, var=var, header=header, mad=mad
        )
    else:
        raise ValueError(f"unknown method {method}")

    logger.info("Saving cube: %s", cube_name)
    cube.write(cube_name, savemask="nan")
    logger.info("Saving img: %s", img_name)
    im = cube.mean(axis=0)
    im.write(img_name, savemask="nan")

    if filter:
        bandname = img_name.replace(".fits", "_{filt}.fits")
        make_band_images(cube, bandname, filter)

    cube = None

    if all([expmap, expmap_name]):
        logger.info("Saving expmap: %s", expmap_name)
        expmap.write(expmap_name)
        logger.info("Saving expmap img: %s", expimg_name)
        expim = expmap.mean(axis=0)
        expim.write(expimg_name, savemask="nan")
    if all([rej, expmap_name]):
        rejmap_name = expmap_name.replace("EXPMAP", "REJMAP")
        logger.info("Saving rejmap: %s", rejmap_name)
        rej.write(rejmap_name)
    if all([stat, stat_name]):
        logger.info("Saving stats: %s", stat_name)
        stat.write(stat_name, format="fits", overwrite=True)


class MPDAFCOMBINE(PythonRecipe):
    """Recipe to combine data cubes with MPDAF."""

    recipe_name = "mpdaf_combine"
    DPR_TYPE = "DATACUBE_FINAL"
    output_dir = "exp_combine"
    output_frames = [
        "DATACUBE_FINAL",
        "IMAGE_FOV",
        "STATPIX",
        "EXPMAP_CUBE",
        "EXPMAP_IMAGE",
    ]
    version = f"mpdaf-{mpdaf.__version__}"

    default_params = dict(
        method="sigclip",
        output_wcs=None,
        nmax=2,
        nclip=5.0,
        nstop=2,
        mosaic=False,
        version=None,
        var="propagate",
        mad=False,
        filter="white,Johnson_V,Cousins_R,Cousins_I",
    )

    def _run(self, flist, *args, scale_table=None, **kwargs):
        field = fits.getval(flist[0], "OBJECT")
        out = dict(
            cube=join(self.output_dir, f"DATACUBE_FINAL_{field}.fits"),
            image=join(self.output_dir, f"IMAGE_FOV_{field}.fits"),
            stat=join(self.output_dir, f"STATPIX_{field}.fits"),
            expmap=join(self.output_dir, f"EXPMAP_CUBE_{field}.fits"),
            expimg=join(self.output_dir, f"EXPMAP_IMAGE_{field}.fits"),
        )
        do_combine(
            flist,
            out["cube"],
            out["expmap"],
            out["stat"],
            out["image"],
            out["expimg"],
            scale_table=scale_table,
            **self.param,
        )
        return out
