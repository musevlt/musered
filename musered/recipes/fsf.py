# Usage:
#  fsf_exposure raw imphot
#  compute full fsf from psfrec and optionaly rescale values using imphot 
#
import logging
import os
import sys
from os.path import join

import numpy as np
from astropy.io import fits

from ..utils import get_exp_name
from .recipe import PythonRecipe

try:
    import muse_psfr
except ImportError:
    PSFR_VERSION = "unknown"
    muse_psfr = None
else:
    PSFR_VERSION = muse_psfr.__version__


def do_fsf(
    inputfile,
    outputfile,
    imphot_table=None,
):
    logger = logging.getLogger(__name__)

    if muse_psfr is None:
        logger.error("muse_psfr is not installed")
        sys.exit(1)
        
    logger.info(inputfile)
    logger.info(outputfile)
    logger.info(imphot_table)
    fits.writeto(outputfile, data=np.arange(10), overwrite=True)




class FSF(PythonRecipe):
    """Recipe to compute FSF for individual exposures"""

    recipe_name = "fsf"
    DPR_TYPE = "OBJECT"
    output_dir = "fsf"
    output_frames = ["FSF"]
    version = f"muse_psfr-{PSFR_VERSION}"
    n_inputs_rec = 1

    default_params = dict(
    )

    def _run(self, flist, *args, imphot_tables=None, **kwargs):
        expname = get_exp_name(flist[0])        
        out = join(self.output_dir, f"FSF.fits")
        self.imphot_table = imphot_tables.get(expname)
        do_fsf(
            flist[0],
            out,
            imphot_table=self.imphot_table,
            **self.param,
        )
        return out

    def dump(self, include_files=False, json_col=False):
        info = super().dump(include_files=include_files, json_col=json_col)
        if include_files:
            # Add the imphot table only in the json file
            info.update(
                {
                    "imphot_table": self.imphot_table,
                }
            )
        return info