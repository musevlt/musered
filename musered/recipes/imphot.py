# -*- coding: utf-8 -*-
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
# import re

from astropy.io import fits
from astropy.table import Table
from mpdaf.obj import Image, Cube
from os.path import join, exists
# from textwrap import dedent

from .recipe import PythonRecipe
from ..utils import get_exp_name

# List the subset of the HST WFC filters that both significantly
# overlap with the wavelength range of MUSE, and that were used
# for the published HST UDF images.
HST_FILTERS = ["F606W", "F775W", "F814W", "F850LP"]

HST_FILTERS_DIR = join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'data', 'hst_filters')

HST_BASENAME = "hlsp_xdf_hst_acswfc-30mas_hudf_%s_v1_sci.fits"

# Create the equivalent of a ds9 region file as a list of lines.
# EXCLUDE_UDF_STARS = dedent(
#     """# DS9 region file for excluding bright stars and QSOs in the UDF
# fk5
# -circle(53.162822, -27.767150, 2.0")  # QSO in UDF01
# -circle(53.157969, -27.769193, 2.0")  # Star in UDF01
# -circle(53.148540, -27.770139, 2.0")  # Star in UDF04
# -circle(53.158344, -27.794921, 2.5")  # Star in UDF05
# -circle(53.176896, -27.799861, 3.0")  # Star in UDF06 PM:25mas/year
# -circle(53.132266, -27.782855, 2.5")  # Star in UDF07
# -circle(53.183461, -27.806763, 2.5")  # Star outside UDF01 to UDF10
# """).split("\n")
EXCLUDE_UDF_STARS = None


def fit_cube_offsets(cubename, hst_filters_dir=None, hst_filters=None,
                     muse_outdir=".", hst_outdir=".", hst_img_dir=None,
                     hst_basename=None, extramask=None, nprocess=8,
                     fix_beta=2.8, force_muse_image=False,
                     force_hst_image=False):
    """Fit pointing offsets to the MUSE observation in a specified cube.

    Parameters
    ----------
    cubename : str
       The full path name of the MUSE cube.
    hst_filters_dir : str
        The name of the directory where the filter files are required.
    muse_outdir : str
       Default = ".". The directory in which to place cached MUSE images.
    hst_outdir : str
       Default = ".". The directory in which to place cached HST images.
    hst_filters: list of str
        Names of the filters to use.
    hst_img_dir : str
       Default = "/muse/UDF/public/HST/XUDF". The directory in which the 30mas
       HST images of the UDF field can be found.
    extramask : str or None
       FITS file, mask image to be combined with the mask of the MUSE image.
       0 used to denote unmasked pixels, and 1 used to denote masked pixels.

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
    expname = get_exp_name(cube.filename)
    # if expname is None:
    #     # Maybe a field name ?
    #     try:
    #         expname = re.findall(r'(UDF-.*)\.fits', cube.filename)[0]
    #     except IndexError:
    #         raise Exception('Could not find exposure or field name')

    if extramask:
        logger.info('Using extra mask: %s', extramask)
    if hst_img_dir is None:
        raise ValueError('hst_img_dir is not specified')

    for filter_name in hst_filters:
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
            muse = imphot.bandpass_image(cube, curve[:, 0], curve[:, 1],
                                         unit_wave=u.angstrom,
                                         nprocess=nprocess,
                                         truncation_warning=False)
            muse.write(fname, savemask="nan")

        # Get an HST image resampled onto the same spatial coordinate
        # grid as the MUSE cube.
        field = muse.primary_header['OBJECT']
        drot = muse.primary_header['ESO INS DROT POSANG']
        logger.info(" Getting resampled HST image for %s (%s)", field, drot)
        hst_filename = join(hst_img_dir, hst_basename % filter_name.lower())
        resampled_filename = join(hst_outdir,
                                  f"hst_{filter_name}_for_{field}_{drot}.fits")
        if not force_hst_image and exists(resampled_filename):
            hst = Image(resampled_filename)
        else:
            logger.info(" Creating %s", resampled_filename)
            hst = Image(hst_filename)
            imphot.regrid_hst_like_muse(hst, muse, inplace=True)
            imphot.rescale_hst_like_muse(hst, muse, inplace=True)
            hst.write(resampled_filename, savemask="nan")

        logger.info(" Fitting for photometric parameters")
        imfit = imphot.fit_image_photometry(hst, muse, fix_beta=fix_beta,
                                            save=True, extramask=extramask,
                                            regions=EXCLUDE_UDF_STARS)
        logger.info('\n' + imfit.summary())
        imfits[filter_name] = imfit

    # average of the offsets that were fitted to all of the filters.
    dra = np.array([i.dra.value for i in imfits.values()]).mean().item()
    ddec = np.array([i.ddec.value for i in imfits.values()]).mean().item()
    ddec /= 3600.
    dra /= 3600.
    return ddec, dra, imfits


class IMPHOT(PythonRecipe):

    recipe_name = 'imphot'
    DPR_TYPE = 'DATACUBE_FINAL'
    output_dir = 'exp_align'
    output_frames = ['OFFSET_LIST']

    default_params = dict(
        extramask=None,
        fix_beta=None,
        force_hst_image=False,
        force_muse_image=False,
        hst_filters_dir=None,
        hst_filters=None,
        hst_img_dir=None,
        hst_outdir=None,
        muse_outdir=None,
    )

    def _run(self, flist, *args, **kwargs):
        nproc = int(os.getenv('OMP_NUM_THREADS', 8))
        full_res = []
        offset_rows = []
        nfiles = len(flist)

        if self.param['muse_outdir'] is None:
            self.param['muse_outdir'] = join(self.output_dir, 'muse')
        if self.param['hst_outdir'] is None:
            self.param['hst_outdir'] = join(self.output_dir, 'hst')

        os.makedirs(self.param['muse_outdir'], exist_ok=True)
        os.makedirs(self.param['hst_outdir'], exist_ok=True)

        for i, filename in enumerate(flist):
            self.logger.info("%d/%d Processing %s", i, nfiles, filename)
            ddec, dra, imfits = fit_cube_offsets(filename, nprocess=nproc,
                                                 **self.param)

            hdr = fits.getheader(filename)
            offset_rows.append((hdr['DATE-OBS'], hdr['MJD-OBS'], dra, ddec))

            for filter_name, fit in imfits.items():
                full_res.append(dict([
                    ('filename', filename),
                    ('filter', filter_name),
                    ('dx', fit.dx.value),
                    ('dy', fit.dy.value),
                    ('dra', fit.dra.value.item()),
                    ('ddec', fit.ddec.value.item()),
                    ('scale', fit.scale.value),
                    ('fwhm', fit.fwhm.value),
                    ('beta', fit.beta.value),
                    ('bg', fit.bg.value),
                    ('rms', fit.rms_error)
                ]))

        outname = join(self.output_dir, 'OFFSET_LIST.fits')
        if os.path.exists(outname):
            self.logger.info('Overwriting OFFSET_LIST')

        t = Table(rows=offset_rows,
                  names=('DATE_OBS', 'MJD_OBS', 'RA_OFFSET', 'DEC_OFFSET'),
                  dtype=('S23', float, float, float))
        self.logger.info('Save OFFSET_LIST file: %s', outname)
        t.write(outname)

        t = Table(rows=full_res)
        t.write(join(self.output_dir, 'imphot_results.fits'))

        return outname
