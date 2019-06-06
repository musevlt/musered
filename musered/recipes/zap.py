import logging
import os
import sys
from os.path import join

import numpy as np
from astropy.io import fits
from mpdaf.scripts.make_white_image import make_white_image

from ..utils import make_band_images
from .recipe import PythonRecipe

try:
    import zap
except ImportError:
    ZAP_VERSION = "unknown"
    zap = None
else:
    ZAP_VERSION = zap.__version__


def do_zap(
    inputfile,
    outputfile,
    skyfile=None,
    imgfile=None,
    cfwidthSVD=100,
    cfwidthSP=100,
    cftype="fit",
    zlevel="median",
    mask=None,
    compute_mask=False,
    additional_mask=None,
    mask_edges=False,
    n_components=None,
    ncpu=None,
    varcurvefile=None,
    filter=None,
):
    logger = logging.getLogger(__name__)

    if zap is None:
        logger.error("zap is not installed")
        sys.exit(1)

    if compute_mask:
        from mpdaf.obj import mask_sources

        logger.info("Computing mask ...")
        img = inputfile.replace("DATACUBE", "IMAGE")
        mask = outputfile.replace("DATACUBE", "MASK")
        if not os.path.exists(img):
            make_white_image(inputfile, img)
        im_mask = mask_sources(img, iterations=1, sigma=3.0)
        if additional_mask is not None:
            logger.info("Combining mask with %s ...", additional_mask)
            addmask = fits.getdata(additional_mask)
            im_mask.data |= addmask
        im_mask.write(mask, savemask="none")
        logger.info("Saved mask to %s", mask)

    logger.info("Zapping %s", inputfile)
    zap.process(
        inputfile,
        outcubefits=outputfile,
        clean=True,
        zlevel=zlevel,
        cftype=cftype,
        cfwidthSVD=cfwidthSVD,
        cfwidthSP=cfwidthSP,
        skycubefits=skyfile,
        mask=mask,
        ncpu=ncpu,
        overwrite=True,
        n_components=n_components,
        varcurvefits=varcurvefile,
    )

    if imgfile is not None:
        make_white_image(outputfile, imgfile)

    if mask_edges:
        if imgfile is None:
            raise ValueError("White light image must be computed")

        logger.info("Masking NaN edges from %s", imgfile)
        maskfile = imgfile.replace("IMAGE", "MASK-EDGES")
        mask, cube = zap.mask_nan_edges(imgfile, outputfile, threshold=10.0)
        mask = mask.astype(np.uint8)
        im = cube.mean(axis=0)
        im.write(imgfile, savemask="nan")
        cube.write(outputfile, savemask="nan")
        fits.writeto(maskfile, mask, header=im.get_wcs_header(), clobber=True)
    else:
        cube = None

    if filter:
        bandname = imgfile.replace(".fits", "_{filt}.fits")
        make_band_images(cube or outputfile, bandname, filter)


class ZAP(PythonRecipe):
    """Recipe to subtract sky with ZAP."""

    recipe_name = "zap"
    DPR_TYPE = "DATACUBE_FINAL"
    output_dir = "zap"
    output_frames = ["DATACUBE_ZAP", "IMAGE_ZAP", "SKYCUBE_ZAP", "VARCURVE_ZAP"]
    version = f"zap-{ZAP_VERSION}"
    n_inputs_rec = 1

    default_params = dict(
        cftype="median",
        cfwidthSVD=300,
        cfwidthSP=300,
        compute_mask=False,
        mask_edges=False,
        n_components=None,
        ncpu=None,
        zlevel="median",
        filter="white,Johnson_V,Cousins_R,Cousins_I",
    )

    @property
    def calib_frames(self):
        """Return the list of calibration frames."""
        return set(["SOURCE_MASK", "ADDITIONAL_MASK"])

    def _run(self, flist, *args, **kwargs):
        out = dict(
            cube=join(self.output_dir, f"DATACUBE_ZAP.fits"),
            image=join(self.output_dir, f"IMAGE_ZAP.fits"),
            skycube=join(self.output_dir, f"SKYCUBE_ZAP.fits"),
            varcurve=join(self.output_dir, f"VARCURVE_ZAP.fits"),
        )
        do_zap(
            flist[0],
            out["cube"],
            skyfile=out["skycube"],
            imgfile=out["image"],
            varcurvefile=out["varcurve"],
            additional_mask=kwargs.get("ADDITIONAL_MASK"),
            mask=kwargs.get("SOURCE_MASK"),
            **self.param,
        )
        return out
