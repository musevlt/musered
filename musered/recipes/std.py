import numpy as np
from astropy.io import fits
from astropy.table import Table
from os.path import join

from .recipe import PythonRecipe

__version__ = "0.1"


def combine_std_median(
    flist, DPR_TYPE, outf=None, lmin=4500, lmax=9500, nl=3700, **kwargs
):
    lb = np.linspace(lmin, lmax, nl)
    if DPR_TYPE == "STD_RESPONSE":
        colname, errname = "response", "resperr"
    elif DPR_TYPE == "STD_TELLURIC":
        colname, errname = "ftelluric", "ftellerr"
    else:
        raise ValueError("unsupported file type")

    resp, err = [], []
    for stdf in flist:
        std = Table.read(stdf)
        resp.append(np.interp(lb, std["lambda"], std[colname]))
        err.append(np.interp(lb, std["lambda"], std[errname]))

    med = np.median(resp, axis=0)
    errmean = np.mean(err, axis=0)
    stdcomb = Table([lb, med, errmean], names=("lambda", colname, errname))

    with fits.open(flist[0]) as inhdul:
        hdul = fits.HDUList([inhdul[0].copy(), fits.table_to_hdu(stdcomb)])
    if outf is not None:
        hdul.writeto(outf, overwrite=True)
    return hdul


class STDCOMBINE(PythonRecipe):
    """Recipe to combine standard for a run."""

    recipe_name = "muse_std_combine"
    DPR_TYPE = "STD_RESPONSE"
    # FIXME: Manage this in PythonRecipe
    DPR_TYPES = ("STD_RESPONSE", "STD_TELLURIC")
    output_dir = "std_combine"
    output_frames = ["STD_RESPONSE"]
    version = __version__

    default_params = dict(method="median")

    def _run(self, flist, *args, **kwargs):
        if not isinstance(flist, dict):
            raise ValueError(
                "flist muse be a dict with the list of files "
                "for STD_RESPONSE and STD_TELLURIC"
            )
        method = self.param["method"]
        self.logger.info("Combining standard stars with %s", method)

        for dpr_type in self.DPR_TYPES:
            outf = join(self.output_dir, f"{dpr_type}_{method}.fits")
            if method == "median":
                combine_std_median(flist[dpr_type], dpr_type, outf=outf, **self.param)
            else:
                raise ValueError(f"unknown method {method}")
