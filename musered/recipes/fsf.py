# Usage:
#  fsf_exposure raw imphot
#  compute full fsf from psfrec and optionaly rescale values using imphot
#
import logging
import os
import sys
from os.path import join

from mpdaf.MUSE import MoffatModel2
from mpdaf.log import clear_loggers

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


def do_fsf(expname, inputfile, outputfile1, outputfile2, imphot_table=None, filters=None):
    logger = logging.getLogger(__name__)

    if muse_psfr is None:
        logger.error("muse_psfr is not installed")
        sys.exit(1)
    
    # clear muse_psfr logger and set to WARNING if not in DEBUG
    clear_loggers("muse_psfr")
    if logging.getLogger('').handlers[0].level > logging.DEBUG:
        logging.getLogger("muse_psfr").setLevel("WARNING")
    
    # run psfrec
    fsfmodel = MoffatModel2.from_psfrec(inputfile, verbose=False)
    
    fwhm = fsfmodel.get_fwhm(np.array(fsfmodel.lbrange))
    beta = fsfmodel.get_beta(np.array(fsfmodel.lbrange))
    logger.info('FSF PsfRec model FWHM %.2f-%.2f BETA %.2f-%.2f',fwhm[0],fwhm[1],beta[0],beta[1])
    
    kernel = 0
    if imphot_table is not None:
        tab = Table.read(imphot_table)
        if outputfile2 is not None:          
            # create output table with FWHM and BETA difference
            vtab = Table(names=['BAND','LBDA','PSREC_FWHM','PSFREC_BETA','IMPHOT_FWHM','IMPHOT_BETA','ERR_FWHM','ERR_BETA'],
                         dtype=['S25']+7*['f8'])
            for b,lb in zip(*filters):
                irow = tab[tab['filter']==b]
                ifwhm = irow['fwhm']
                ibeta = irow['beta']
                pfwhm = fsfmodel.get_fwhm(lb)
                pbeta = fsfmodel.get_beta(lb)
                vtab.add_row([b,lb,pfwhm,pbeta,ifwhm,ibeta,ifwhm-pfwhm,ibeta-pbeta])
            vtab.write(outputfile2, overwrite=True)
        # computing convolution kernel
        imphot_fwhms = tab[[e['filter'] in filters[0] for e in tab]]['fwhm']
        psfrec_fwhms = fsfmodel.get_fwhm(np.array(filters[1]))
        kernels = np.sqrt(np.clip(imphot_fwhms**2 - psfrec_fwhms**2,0,np.nan))
        for band,wave,f1,f2,kernel in zip(filters[0],filters[1],imphot_fwhms,
                                          psfrec_fwhms,kernels):
            logger.debug('Filter %s Wave: %.1f IMPHOT FWHM %.2f PSFREC FWHM %.2f Kernel %.2f',
                         band,wave,f1,f2,kernel)
        kernel_max = np.mean(kernels)
        if kernel_max == 0:
            logger.debug('IMPHOT FSF is smaller than PSFREC FSF, no convolution')
        else:
            kernels = [0.6*kernel_max, 0.7*kernel_max, 0.8*kernel_max, 0.9*kernel_max, kernel_max]
            diffs = []
            for kernel in kernels:
                logger.debug('Convolution of FSFmodel with a Gaussian Kernel FWHM: %.2f', kernel)
                cfsfmodel = fsfmodel.convolve(kernel)
                final_fwhms = cfsfmodel.get_fwhm(np.array(filters[1]))
                diff = []
                for band,wave,f1,f2,f3 in zip(filters[0],filters[1],imphot_fwhms,
                                                  psfrec_fwhms,final_fwhms):
                    logger.debug('Filter %s Wave: %.1f IMPHOT FWHM %.2f PSFREC FWHM %.2f COMPUTED %.2f DIFF %.2f',
                                 band,wave,f1,f2,f3,f3-f1)
                    diff.append(f3-f1)
                diffs.append(np.mean(diff))
            kernel = np.interp(0, diffs, kernels)
            logger.debug('Final Gaussian Kernel FWHM: %.2f', kernel)
            cfsfmodel = fsfmodel.convolve(kernel)
            final_fwhms = cfsfmodel.get_fwhm(np.array(filters[1]))
            for band,wave,f1,f2,f3 in zip(filters[0],filters[1],imphot_fwhms,
                                                  psfrec_fwhms,final_fwhms):
                logger.debug('Filter %s Wave: %.1f IMPHOT FWHM %.2f PSFREC FWHM %.2f FINAL %.2f DIFF %.2f',
                                     band,wave,f1,f2,f3,f3-f1) 
            fwhm = cfsfmodel.get_fwhm(np.array(fsfmodel.lbrange))
            beta = cfsfmodel.get_beta(np.array(fsfmodel.lbrange))
            logger.info('FSF Final model FWHM %.2f-%.2f BETA %.2f-%.2f',fwhm[0],fwhm[1],beta[0],beta[1])
            fsfmodel = cfsfmodel      
    
    tab = Table(names=['NAME','LBDA0','LBDA1','FWHM_B','FWHM_R','BETA_B','BETA_R','KERNEL','NCFWHM','NCBETA'], 
                dtype=['S25']+7*['f8']+2*['i4'])
    row = [expname,fsfmodel.lbrange[0],fsfmodel.lbrange[1],fwhm[0],fwhm[1],beta[0],beta[1],kernel,
           len(fsfmodel.fwhm_pol),len(fsfmodel.beta_pol)]
    for k,val in enumerate(fsfmodel.fwhm_pol):
        tab.add_column(Column(name=f"FWHM_P{k}", dtype='f8'))
        row.append(val)
    for k,val in enumerate(fsfmodel.beta_pol):
        tab.add_column(Column(name=f"BETA_P{k}", dtype='f8'))
        row.append(val)          
    tab.add_row(row)
    
    tab.write(outputfile1, overwrite=True)


class FSF(PythonRecipe):
    """Recipe to compute FSF for individual exposures"""

    recipe_name = "fsf"
    DPR_TYPE = "OBJECT"
    output_dir = "fsf"
    output_frames = ["FSF"]
    version = f"muse_psfr-{PSFR_VERSION}"
    n_inputs_rec = 1

    default_params = dict()

    def _run(self, flist, *args, imphot_tables=None, filters=None, **kwargs):
        expname = get_exp_name(flist[0])
        out1 = join(self.output_dir, f"FSF.fits")
        if imphot_tables is not None:
            out2 = join(self.output_dir, f"FSF_PSFREC_IMPHOT.fits")
            self.imphot_table = imphot_tables.get(expname)
        else:
            out2 = None
            self.imphot_table = None
        do_fsf(expname, flist[0], out1, out2, imphot_table=self.imphot_table, 
               filters=filters, **self.param)
        return out1,out2

    def dump(self, include_files=False, json_col=False):
        info = super().dump(include_files=include_files, json_col=json_col)
        if include_files:
            # Add the imphot table only in the json file
            info.update({"imphot_table": self.imphot_table})
        return info
