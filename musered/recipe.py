import cpl
import logging
import os
import shutil
import time
from astropy.io import fits
from collections import defaultdict

from .version import __version__


class Recipe:
    """Base class for the DRS Recipes.

    Parameters
    ----------
    indir : str
        Name of input directory.
    outdir : str
        Name of output directory.
    use_drs_output : bool
        If True, output files are saved by the DRS, else files are saved by
        mydrs with custom names.
    temp_dir : str
        Base directory for temporary directories where the recipe is executed.
        The working dir is created as a subdir with a random file name. If set
        to None (default), the system temp dir is used.

    """

    recipe_name = None
    # indir = None
    outdir = None
    default_params = None

    def __init__(self,
                 # indir=None,
                 outdir=None,
                 use_drs_output=True,
                 temp_dir=None,
                 nifu=-1):
        # self.qc = {}
        self.nbwarn = 0
        self.logger = logging.getLogger(__name__)
        self.outfiles = defaultdict(list)

        # if indir is not None:
        #     self.indir = indir
        if outdir is not None:
            self.outdir = outdir

        if self.outdir is not None:
            os.makedirs(self.outdir, exist_ok=True)

        self._recipe = cpl.Recipe(self.recipe_name, version=cpl.drs_version)
        self._recipe.output_dir = self.outdir if use_drs_output else None
        self._recipe.temp_dir = temp_dir
        self.param = self._recipe.param

        if 'nifu' in self.param:
            self.param['nifu'] = nifu

        if self.default_params is not None:
            for name, value in self.default_params.items():
                self.param[name] = value

        # self.param['saveimage'] = saveimage
        # self._recipe.env['MUSE_PIXTABLE_SAVE_AS_IMAGE'] = 1

    def info(self):
        info = self.logger.info
        info('Musered version %s', __version__)
        info('- DRS version        : %s', cpl.drs_version)
        info('- Recipe path        : %s', cpl.Recipe.path)
        # info('- Reference File dir : %s', cpl.ref_dir)
        info('- Log Level          : %s', cpl.esorex.msg.level)
        info('- Log filename       : %s', cpl.esorex.log.filename)
        info('- Recipe             : %s version %s',
             self.recipe_name, self._recipe.version[1])

        # if self.indir is not None:
        #     info('- Input directory    : %s', self.indir)

        if self.outdir is not None:
            info('- Output directory   : %s', self.outdir)

        if self._recipe is not None:
            for p in self.param:
                print(p.name, p.value, p.default)
            for f in self._recipe.calib:
                print(f.tag, f.min, f.max, f.frames)

    def write_fits(self, name_or_hdulist, filetype, filename):
        if type(name_or_hdulist) is list:
            # Not isinstance because HDUList inherits from list
            self.logger.error('Got a list of frames: %s', name_or_hdulist)
            name_or_hdulist = name_or_hdulist[0]

        self.logger.info('Saving %s', filename)
        if isinstance(name_or_hdulist, str):
            shutil.move(name_or_hdulist, filename)
        elif isinstance(name_or_hdulist, fits.HDUList):
            name_or_hdulist.writeto(filename, overwrite=True)
        else:
            raise ValueError('unknown output type: %r', name_or_hdulist)

        self.outfiles[filetype].append(filename)

    def run(self, flist, *args, params=None, **kwargs):
        t0 = time.time()

        if isinstance(flist, str):
            flist = [flist]

        if len(flist) == 0:
            self.logger.error('No exposure found -- stopped')
            return

        if params is not None:
            for name, value in params.items():
                self.param[name] = value

        results = self._run(flist, *args, **kwargs)

        self.warn = results.log.warning
        self.timeit = (time.time() - t0) // 60
        self.logger.info('%s successfully run with %d warnings',
                         self.recipe_name, len(self.warn))
        self.logger.info('Execution time %g minutes', self.timeit)
        self.logger.info('DRS user time: %s, sys: %s', results.stat.user_time,
                         results.stat.sys_time)
        return results
