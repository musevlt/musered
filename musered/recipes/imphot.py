# Usage:
#  fit_cube_pointing cube aux_dir [hst_dir]
#
#  Arguments:
#   cube     : The cube that contains the MUSE exposure to be processed.
#   aux_dir  : A directory in which to cache auxiliary files for
#              future runs of this script, and to record the
#              final output files. This directory should already exist.
#   hst_dir  : The directory in which to find the following UDF HST
#              files:
#                 hlsp_xdf_hst_acswfc-30mas_hudf_f606w_v1_sci.fits
#                 hlsp_xdf_hst_acswfc-30mas_hudf_f775w_v1_sci.fits
#                 hlsp_xdf_hst_acswfc-30mas_hudf_f814w_v1_sci.fits
#                 hlsp_xdf_hst_acswfc-30mas_hudf_f850lp_v1_sci.fits
# .             If this directory is not specified, it will be assumed
#              to be "/muse/UDF/public/HST/XUDF"

import astropy.units as u
import logging
import numpy as np
import os

from astropy.io import fits
from astropy.table import Table, vstack
from joblib import Parallel, delayed
from mpdaf.obj import Image, Cube
from os.path import join, exists

from .recipe import PythonRecipe
from ..utils import get_exp_name

# List the subset of the HST WFC filters that both significantly
# overlap with the wavelength range of MUSE, and that were used
# for the published HST UDF images.
HST_FILTERS = ["F606W", "F775W", "F814W", "F850LP"]

HST_FILTERS_DIR = join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "hst_filters"
)

HST_BASENAME = "hlsp_xdf_hst_acswfc-30mas_hudf_%s_v1_sci.fits"


def fit_cube_offsets(
    cubename,
    hst_filters_dir=None,
    hst_filters=None,
    muse_outdir=".",
    hst_outdir=".",
    hst_img_dir=None,
    hst_basename=None,
    hst_resample_each=False,
    extramask=None,
    nprocess=8,
    fix_beta=None,
    expname=None,
    force_muse_image=False,
    force_hst_image=False,
    exclude_regions=None,
    fix_bg=None,
    min_scale=None,
):
    """Fit pointing offsets to the MUSE observation in a specified cube.

    Parameters
    ----------
    cubename : str
        The full path name of the MUSE cube.
    hst_filters_dir : str
        The name of the directory where the filter files are required.
    hst_filters: list of str
        Names of the filters to use.
    muse_outdir : str
        Default = ".". The directory in which to place cached MUSE images.
    hst_outdir : str
        Default = ".". The directory in which to place cached HST images.
    hst_img_dir : str
        Default = "/muse/UDF/public/HST/XUDF". The directory in which the 30mas
        HST images of the UDF field can be found.
    hst_basename : str
        Filename of the HST images, defaults to
        'hlsp_xdf_hst_acswfc-30mas_hudf_%s_v1_sci.fits'.
    hst_resample_each : bool
        Force the resampling of the HST image for each MUSE image, needed when
        MUSE images are not on the same grid.
    extramask : str or None
        FITS file, mask image to be combined with the mask of the MUSE image.
        0 used to denote unmasked pixels, and 1 used to denote masked pixels.
    nprocess : 8
        Number of processes to use to create bandpass images.
    fix_beta : float or list of float
        The beta exponent of the Moffat PSF is fixed to the specified value
        while fitting, unless the value is None. Can be a list of values for
        each filter.
    fix_bg : float or list of float
       The calibration zero-offset, (MUSE_flux - HST_flux) is fixed
       to the specified value while fitting, unless the value is None. Can
       be a list of values for each filter.
    exclude_regions : str
        DS9 regions that can be used to exclude problematic areas of an
        image or sources that would degrade the global PSF fit, such as
        saturated stars, stars with significant proper motion, and
        variable sources. Passed to imphot.fit_image_photometry.

    Returns
    -------
    out : (float, float)
       The fitted Y-axis and X-axis pointing errors (arcseconds).
       To correct the MUSE image, shift it by -dy, -dx arcseconds
       along the Y and X axes of the cube.

    """
    import imphot

    logger = logging.getLogger(__name__)
    cube = Cube(cubename)

    hst_filters = hst_filters or HST_FILTERS
    hst_filters_dir = hst_filters_dir or HST_FILTERS_DIR
    hst_basename = hst_basename or HST_BASENAME

    filter_curves = {}
    for name in hst_filters:
        filter_pathname = join(hst_filters_dir, "wfc_%s.dat.gz" % name)
        filter_curves[name] = np.loadtxt(filter_pathname, usecols=(0, 1))

    imfits = {}

    if extramask:
        logger.info("Using extra mask: %s", extramask)
    if hst_img_dir is None:
        raise ValueError("hst_img_dir is not specified")

    if not isinstance(fix_beta, (list, tuple)):
        fix_beta = [fix_beta] * len(hst_filters)
    if not isinstance(fix_bg, (list, tuple)):
        fix_bg = [fix_bg] * len(hst_filters)

    for i, filter_name in enumerate(hst_filters):
        # Extract an image from the cube with the spectral characteristics
        # of the filter.
        if expname:
            fname = f"{muse_outdir}/IMAGE-MUSE-{filter_name}-{expname}.fits"
        else:
            fname = f"{muse_outdir}/IMAGE-MUSE-{filter_name}.fits"

        if not force_muse_image and exists(fname):
            logger.info(" Getting MUSE image for %s", filter_name)
            muse = Image(fname)
        else:
            logger.info(" Computing MUSE image for %s", filter_name)
            curve = filter_curves[filter_name]
            muse = imphot.bandpass_image(
                cube,
                curve[:, 0],
                curve[:, 1],
                unit_wave=u.angstrom,
                nprocess=nprocess,
                truncation_warning=False,
            )
            muse.write(fname, savemask="nan")

        # Get an HST image resampled onto the same spatial coordinate
        # grid as the MUSE cube.
        field = muse.primary_header["OBJECT"]
        hst_filename = join(hst_img_dir, hst_basename % filter_name.lower())

        if hst_resample_each:
            # useful if MUSE images are not (yet) on the same grid, when
            # OUTPUT_WCS is not used. So we need to resample the HST image for
            # each MUSE exposures.
            if expname:
                resamp_name = join(hst_outdir, f"hst_{filter_name}_for_{expname}.fits")
            else:
                resamp_name = join(hst_outdir, f"hst_{filter_name}.fits")
        else:
            resamp_name = join(hst_outdir, f"hst_{filter_name}_for_{field}.fits")

        if not force_hst_image and exists(resamp_name):
            logger.info(" Getting resampled HST image for %s", field)
            hst = Image(resamp_name)
        else:
            logger.info(" Computing resampled HST image %s", resamp_name)
            hst = Image(hst_filename)
            imphot.regrid_hst_like_muse(hst, muse, inplace=True)
            imphot.rescale_hst_like_muse(hst, muse, inplace=True)
            hst.write(resamp_name, savemask="nan")

        logger.info(" Fitting for photometric parameters")
        imfit = imphot.fit_image_photometry(
            hst,
            muse,
            extramask=extramask,
            fix_beta=fix_beta[i],
            fix_bg=fix_bg[i],
            min_scale=min_scale,
            regions=exclude_regions,
            save=True,
        )
        imfits[filter_name] = imfit

    for i, imfit in enumerate(imfits.values()):
        if i == 0:
            for line in imfit.summary(header=True).splitlines():
                logger.info(line)
        else:
            logger.info(imfit.summary(header=False))

    # average of the offsets that were fitted to all of the filters.
    dra = np.array([i.dra.value for i in imfits.values()]).mean().item()
    ddec = np.array([i.ddec.value for i in imfits.values()]).mean().item()
    ddec /= 3600.0
    dra /= 3600.0
    return ddec, dra, imfits


def _process_exp(i, nfiles, filename, output_dir, param):
    logger = logging.getLogger(__name__)
    expname = get_exp_name(filename)
    logger.info("%d/%d Processing %s", i, nfiles, filename)
    outdir = join(output_dir, expname)
    os.makedirs(outdir, exist_ok=True)

    hst_outdir = outdir if param["hst_resample_each"] else output_dir
    nproc = int(os.getenv("OMP_NUM_THREADS", 8))
    ddec, dra, imfits = fit_cube_offsets(
        filename, nprocess=nproc, muse_outdir=outdir, hst_outdir=hst_outdir, **param
    )

    hdr = fits.getheader(filename)

    rows = []
    for filter_name, fit in imfits.items():
        rows.append(
            {
                "filename": filename,
                "filter": filter_name,
                "dx": fit.dx.value,
                "dy": fit.dy.value,
                "dra": fit.dra.value.item(),
                "ddec": fit.ddec.value.item(),
                "scale": fit.scale.value,
                "fwhm": fit.fwhm.value,
                "beta": fit.beta.value,
                "bg": fit.bg.value,
                "rms": fit.rms_error,
            }
        )
    t = Table(rows=rows)
    t.meta["EXPNAME"] = expname
    t.meta["RA_OFF"] = dra
    t.meta["DEC_OFF"] = ddec
    t.meta["DATE-OBS"] = hdr["DATE-OBS"]
    t.meta["MJD-OBS"] = hdr["MJD-OBS"]
    t.write(join(outdir, "IMPHOT.fits"), overwrite=True)

    return hdr["DATE-OBS"], hdr["MJD-OBS"], dra, ddec


class IMPHOT(PythonRecipe):
    """Recipe to compute offsets with Imphot."""

    recipe_name = "imphot"
    DPR_TYPE = "DATACUBE_FINAL"
    output_dir = "exp_align"
    output_frames = ["OFFSET_LIST"]

    default_params = dict(
        exclude_regions=None,
        extramask=None,
        fix_beta=None,
        fix_bg=None,
        force_hst_image=False,
        force_muse_image=False,
        hst_filters_dir=None,
        hst_filters=None,
        hst_img_dir=None,
        hst_resample_each=False,
        min_scale=0,
    )

    @property
    def version(self):
        """Return the recipe version"""
        import imphot

        try:
            return f"imphot-{imphot.__version__}"
        except AttributeError:
            return f"imphot-unknown"

    def _run(self, flist, *args, processed=None, n_jobs=1, force=False, **kwargs):

        if force:
            self.param["force_hst_image"] = True
            self.param["force_muse_image"] = True

        nfiles = len(flist)
        processed = processed or set()
        to_compute = []
        for i, filename in enumerate(flist, start=1):
            expname = get_exp_name(filename)
            if expname in processed:
                self.logger.info("%d/%d Skipping %s", i, nfiles, filename)
            else:
                to_compute.append((i, nfiles, filename, self.output_dir, self.param))

        offset_rows = Parallel(n_jobs=n_jobs)(
            delayed(_process_exp)(*args) for args in to_compute
        )

        outname = join(self.output_dir, "OFFSET_LIST.fits")

        if len(offset_rows) == 0:
            self.logger.info("Already up-to-date")
            return outname

        t = Table(
            rows=offset_rows,
            names=("DATE_OBS", "MJD_OBS", "RA_OFFSET", "DEC_OFFSET"),
            dtype=("S23", float, float, float),
        )

        if os.path.exists(outname):
            self.logger.info("Updating OFFSET_LIST")
            off = Table.read(outname)
            # find matches with the existing table
            match = np.in1d(off["DATE_OBS"], t["DATE_OBS"])
            if np.any(match):
                # Remove rows have been recomputed
                self.logger.info("Updating %d rows", np.count_nonzero(match))
                off = off[~match]
            # combine the new and old values
            t = vstack([off, t])

        self.logger.info("Save OFFSET_LIST file: %s", outname)
        t.write(outname, overwrite=True)

        return outname
