import numpy as np
from astropy.io import fits
from astropy.table import Table
from os.path import join

from .recipe import PythonRecipe

__version__ = '0.1'


def combine_std_median(flist, outf=None, lmin=4500, lmax=9500, nl=3700,
                       **kwargs):
    lb = np.linspace(lmin, lmax, nl)

    resp = []
    for stdf in flist:
        std = Table.read(stdf)
        resp.append(np.interp(lb, std['lambda'], std['response']))

    med = np.median(resp, axis=0)
    stdcomb = Table([lb, med], names=('lambda', 'response'))

    with fits.open(flist[0]) as inhdul:
        hdul = fits.HDUList([inhdul[0].copy(), fits.table_to_hdu(stdcomb)])
    if outf is not None:
        hdul.writeto(outf, overwrite=True)
    return hdul


class STDCOMBINE(PythonRecipe):

    recipe_name = 'muse_std_combine'
    DPR_TYPE = 'STD_RESPONSE'
    output_dir = 'std_combine'
    output_frames = ['STD_RESPONSE']
    version = __version__

    default_params = dict(
        method='median'
    )

    def _run(self, flist, *args, **kwargs):
        method = self.param['method']
        self.logger.info('Combining standard stars with %s', method)
        outf = join(self.output_dir, f'STD_RESPONSE_{method}.fits')
        if method == 'median':
            combine_std_median(flist, outf=outf, **self.param)
        else:
            raise ValueError(f'unknown method {method}')
