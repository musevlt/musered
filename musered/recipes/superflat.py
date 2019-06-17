import logging
import os
import pathlib
import platform
import shutil
from glob import glob
from os.path import join
from tempfile import TemporaryDirectory
from time import time

import numpy as np
from astropy.io import fits
from astropy.table import Table
from joblib import Parallel, delayed
from mpdaf.obj import Cube, CubeList

from ..masking import mask_sources
from ..utils import make_band_images
from .recipe import PythonRecipe
from .science import SCIPOST


class SUPERFLAT(PythonRecipe):
    """Recipe to compute and subtract a superflat."""

    recipe_name = "superflat"
    DPR_TYPE = "DATACUBE_FINAL"
    output_dir = "superflat"
    output_frames = [
        "DATACUBE_FINAL",
        "IMAGE_FOV",
        "DATACUBE_SUPERFLAT",
        "IMAGE_SUPERFLAT",
        "DATACUBE_EXPMAP",
        "IMAGE_EXPMAP",
        "STATPIX",
    ]
    version = "0.1"
    # Save the V,R,I images
    default_params = {
        "cache_pixtables": False,
        "filter": "white,Johnson_V,Cousins_R,Cousins_I",
        "keep_cubes": False,
        "method": "sigclip",
        "scipost": {"filter": "white", "save": "cube", "skymethod": "none"},
        "temp_dir": None,
    }

    @property
    def calib_frames(self):
        # We suppose that most of the scipost steps were already run (flux
        # calibration, sky subtraction, autocalib), so we exclude all these
        # frames to speedup the frame association.
        exclude = (
            "RAMAN_LINES",
            "STD_RESPONSE",
            "STD_TELLURIC",
            "LSF_PROFILE",
            "SKY_CONTINUUM",
            "SKY_LINES",
        )
        return [f for f in SCIPOST(verbose=False).calib_frames if f not in exclude]

    def get_pixtables(self, name, path):
        """Return pixtables path, after optionally caching them."""
        cachedir = self.param["cache_pixtables"]
        if isinstance(cachedir, dict):
            # get cachedir specific to a given hostname
            cachedir = cachedir.get(platform.node())

        if cachedir:
            cachedir = pathlib.Path(cachedir) / name
            if not cachedir.exists():
                cachedir.mkdir(parents=True)
                for f in glob(f"{path}/PIXTABLE_REDUCED*.fits"):
                    self.logger.debug("copy %s to %s", f, cachedir)
                    shutil.copy(f, cachedir)
            return glob(f"{cachedir}/PIXTABLE_REDUCED*.fits")
        else:
            return glob(f"{path}/PIXTABLE_REDUCED*.fits")

    def _run(self, flist, *args, exposures=None, name=None, **kwargs):
        hdr = fits.getheader(flist[0])
        ra, dec = hdr["RA"], hdr["DEC"]
        info = self.logger.info

        # 1. Run scipost for all exposures used to build the superflat
        run = exposures[exposures["name"] == name]["run"][0]
        exps = exposures[
            (exposures["run"] == run)
            & (~exposures["excluded"])
            & (exposures["name"] != name)
        ]
        nexps = len(exps)
        info("Found %d exposures for run %s", nexps, run)

        # Fix the RA/DEC/DROT values for all exposures to the values of the
        # reference exp. Take into account the offset of the exposure, as we
        # need the superflat to be aligned with the exposure. The offset is
        # applied them directly to the RA/DEC values, otherwise the DRS checks
        # the exposure name.
        if "OFFSET_LIST" in kwargs:
            offsets = Table.read(kwargs["OFFSET_LIST"])
            offsets = offsets[offsets["DATE_OBS"] == hdr["DATE-OBS"]]
            ra -= offsets["RA_OFFSET"][0]
            dec -= offsets["DEC_OFFSET"][0]

        os.environ["MUSE_SUPERFLAT_POS"] = ",".join(
            map(str, (ra, dec, hdr["ESO INS DROT POSANG"]))
        )

        # Prepare scipost recipe and args, and remove OFFSET_LIST as offsets
        # are applied manually above
        recipe = SCIPOST(log_dir=self.log_dir)
        recipe_kw = {
            key: kwargs[key]
            for key in self.calib_frames
            if key in kwargs and key != "OFFSET_LIST"
        }

        cubelist = []
        self.raw["SUPERFLAT_EXPS"] = []

        # cubes directory: either inside tmpdir or inside output_dir if the
        # keep_cubes option is True
        if self.param["keep_cubes"]:
            cubesdir = join(self.output_dir, "cubes")
        else:
            temp_dir = self.param["temp_dir"] or self.temp_dir
            if isinstance(temp_dir, dict):
                # get temp_dir specific to a given hostname
                temp_dir = temp_dir.get(platform.node())
            os.makedirs(temp_dir, exist_ok=True)
            temp_dir = TemporaryDirectory(dir=temp_dir)
            cubesdir = temp_dir.name

        t0 = time()
        for i, exp in enumerate(exps, start=1):
            outdir = join(cubesdir, exp["name"])
            outname = f"{outdir}/DATACUBE_FINAL.fits"

            if os.path.exists(outname):
                info("%d/%d : %s already processed", i, nexps, exp["name"])
            else:
                info("%d/%d : %s processing", i, nexps, exp["name"])
                explist = self.get_pixtables(exp["name"], exp["path"])
                self.raw["SUPERFLAT_EXPS"] += explist
                recipe.run(
                    explist,
                    output_dir=outdir,
                    params=self.param["scipost"],
                    **recipe_kw,
                )

            # Mask sources
            mask_cube(outname)
            cubelist.append(outname)

        info("Scipost and masking done, took %.2f sec.", time() - t0)

        # 2. Combine exposures to obtain the superflat
        t0 = time()
        method = self.param["method"]
        info("Combining cubes with method %s", method)
        cubes = CubeList(cubelist)
        if method == "median":
            supercube, expmap, stat = cubes.median()
        elif method == "sigclip":
            supercube, expmap, stat = cubes.combine(var="propagate", mad=True)
            # Mask values where the variance is NaN
            supercube.mask |= np.isnan(supercube._var)
        else:
            raise ValueError(f"unknown method {method}")
        info("Combine done, took %.2f sec.", time() - t0)

        # remove temp directory
        if not self.param["keep_cubes"]:
            info("Removing temporary files")
            temp_dir.cleanup()

        info("Saving superflat cube and images")
        superim = supercube.mean(axis=0)
        expim = expmap.mean(axis=0)
        outdir = self.output_dir
        supercube.write(join(outdir, "DATACUBE_SUPERFLAT.fits.gz"), savemask="nan")
        expmap.write(join(outdir, "DATACUBE_EXPMAP.fits.gz"), savemask="nan")
        expim.write(join(outdir, "IMAGE_EXPMAP.fits"), savemask="nan")
        stat.write(join(outdir, "STATPIX.fits"), overwrite=True)
        superim.write(join(outdir, "IMAGE_SUPERFLAT.fits"), savemask="nan")

        # 3. Subtract superflat
        info("Applying superflat to %s", flist[0])
        expcube = Cube(flist[0])
        assert expcube.shape == supercube.shape

        # Do nothing for masked values
        mask = supercube.mask.copy()
        supercube.data[mask] = 0
        if supercube.var is not None:
            supercube.var[mask] = 0
        expcube -= supercube
        im = expcube.mean(axis=0)

        expcube.write(join(outdir, "DATACUBE_FINAL.fits"), savemask="nan")
        im.write(join(outdir, "IMAGE_FOV.fits"), savemask="nan")

        filt = self.param["filter"]
        if filt:
            info("Making band images")
            make_band_images(expcube, join(outdir, "IMAGE_FOV_{filt}.fits"), filt)
            make_band_images(
                supercube, join(outdir, "IMAGE_SUPERFLAT_{filt}.fits"), filt
            )


def mask_cube(cubef):
    logger = logging.getLogger(__name__)
    t0 = time()
    cubedir = os.path.dirname(cubef)

    try:
        fits.getval(cubef, "MASKED", extname="DATA")
    except KeyError:
        pass
    else:
        logger.info("%s is already masked", cubef)
        return

    mask = mask_sources(
        join(cubedir, "IMAGE_FOV_0001.fits"),
        sigma=5.0,
        iterations=2,
        opening_iterations=1,
        return_image=False,
    )

    with fits.open(cubef) as hdul:
        hdul["DATA"].header["MASKED"] = True
        hdul["DATA"].data[:, mask] = np.nan
        # for some reason this is much faster than updating the
        # cube in-place with mode='update'
        hdul.writeto(cubef, overwrite=True)

    logger.info("Masking done, took %.2f sec.", time() - t0)
