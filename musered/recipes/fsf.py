# Usage:
#  fsf_exposure raw imphot
#  compute full fsf from psfrec and optionaly rescale values using imphot
#
import logging
import os
import sys
from os.path import join

from mpdaf.MUSE import MoffatModel2

import numpy as np
from astropy.table import Table, Column

from ..utils import get_exp_name
from .recipe import PythonRecipe

try:
    import muse_psfr
except ImportError:
    PSFR_VERSION = "unknown"
    muse_psfr = None
else:
    PSFR_VERSION = muse_psfr.__version__


def do_fsf(expname, inputfile, outputfile, imphot_table=None):
    logger = logging.getLogger(__name__)

    if muse_psfr is None:
        logger.error("muse_psfr is not installed")
        sys.exit(1)
    
    # Change log  level (NOT WORKING)
    logpsfrec = logging.getLogger('muse_psfr')
    logpsfrec.setLevel(logger.level)
    
    # run psfrec
    fsfmodel = MoffatModel2.from_psfrec(inputfile)
    
    fwhm = fsfmodel.get_fwhm(np.array(fsfmodel.lbrange))
    beta = fsfmodel.get_beta(np.array(fsfmodel.lbrange))
    logger.debug('FSF PsfRec model FWHM %.2f-%.2f BETA %.2f-%.2f',fwhm[0],fwhm[1],beta[0],beta[1])
    
    
    
    tab = Table(names=['NAME','LBDA0','LBDA1','FWHM_B','FWHM_R','BETA_B','BETA_R','NCFWHM','NCBETA'], 
                dtype=['S25']+6*['f8']+2*['i4'])
    row = [expname,fsfmodel.lbrange[0],fsfmodel.lbrange[1],fwhm[0],fwhm[1],beta[0],beta[1],
           len(fsfmodel.fwhm_pol),len(fsfmodel.beta_pol)]
    for k,val in enumerate(fsfmodel.fwhm_pol):
        tab.add_column(Column(name=f"FWHM_P{k}", dtype='f8'))
        row.append(val)
    for k,val in enumerate(fsfmodel.beta_pol):
        tab.add_column(Column(name=f"BETA_P{k}", dtype='f8'))
        row.append(val)          
    tab.add_row(row)
    
    tab.write(outputfile, overwrite=True)


class FSF(PythonRecipe):
    """Recipe to compute FSF for individual exposures"""

    recipe_name = "fsf"
    DPR_TYPE = "OBJECT"
    output_dir = "fsf"
    output_frames = ["FSF"]
    version = f"muse_psfr-{PSFR_VERSION}"
    n_inputs_rec = 1

    default_params = dict()

    def _run(self, flist, *args, imphot_tables=None, **kwargs):
        expname = get_exp_name(flist[0])
        out = join(self.output_dir, f"FSF.fits")
        if imphot_tables is not None:
            self.imphot_table = imphot_tables.get(expname)
        else:
            self.imphot_table = None
        do_fsf(expname, flist[0], out, imphot_table=self.imphot_table, **self.param)
        return out

    def dump(self, include_files=False, json_col=False):
        info = super().dump(include_files=include_files, json_col=json_col)
        if include_files:
            # Add the imphot table only in the json file
            info.update({"imphot_table": self.imphot_table})
        return info
