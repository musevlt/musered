import logging
import mpdaf
from astropy.io import fits
from mpdaf.obj import CubeList, CubeMosaic
from os.path import join

from .recipe import PythonRecipe

__version__ = '0.1'


def do_combine(run)
    logger = logging.getLogger('musered')
    logger.info('Combining standard stars for run %s', run)
    #if run not in mr.runs

    logger.info('Saving std: %s', std_resp)


class STDCOMBINE(PythonRecipe):

    recipe_name = 'muse_std_combine'
    DPR_TYPE = 'STD_RESPONSE'
    output_dir = 'std_combine'
    output_frames = ['STD_RESPONSE']
    version = __version__

    default_params = dict(
        version=None,
            )

    def _run(self, run, *args, **kwargs):
        out = dict(
            std_resp =join(self.output_dir, f'STD_RESPONSE_{run}.fits'),
        )
        do_combine(run, out['std_resp'], **self.param)
        return out
