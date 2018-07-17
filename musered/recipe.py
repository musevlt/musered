import cpl
import datetime
import json
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
    output_dir : str
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
    OBJECT = None
    OBJECT_out = None
    # indir = None
    default_params = None

    def __init__(self, output_dir=None, use_drs_output=True, temp_dir=None,
                 log_dir='.', version=None, nifu=-1):
        self.nbwarn = 0
        self.logger = logging.getLogger(__name__)
        self.outfiles = defaultdict(list)
        self.log_dir = log_dir
        self.log_file = None

        if output_dir is not None:
            self.output_dir = output_dir
        else:
            self.output_dir = self.OBJECT_out

        self._recipe = cpl.Recipe(self.recipe_name, version=version)
        self._recipe.output_dir = self.output_dir if use_drs_output else None
        if temp_dir is not None:
            self._recipe.temp_dir = temp_dir
        self.param = self._recipe.param
        self.calib = self._recipe.calib

        if 'nifu' in self.param:
            self.param['nifu'] = nifu

        if self.default_params is not None:
            for name, value in self.default_params.items():
                self.param[name] = value

        info = self.logger.info
        info('Musered version %s', __version__)
        info('- DRS version        : %s', self._recipe.version[1])
        info('- Recipe path        : %s', cpl.Recipe.path)
        info('- Recipe             : %s', self.recipe_name)
        # self.param['saveimage'] = saveimage
        # self._recipe.env['MUSE_PIXTABLE_SAVE_AS_IMAGE'] = 1

    def dump_params(self):
        params = {p.name: p.value for p in self.param if p.value is not None}
        return json.dumps(params)

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

    def run(self, flist, *args, params=None, verbose=False, **kwargs):
        t0 = time.time()
        info = self.logger.info

        if isinstance(flist, str):
            flist = [flist]

        if len(flist) == 0:
            raise ValueError('No exposure found -- stopped')

        if params is not None:
            for name, value in params.items():
                self.param[name] = value

        date = datetime.datetime.now().isoformat()
        cpl.esorex.log.filename = self.log_file = os.path.join(
            self.log_dir, f"{self.recipe_name}-{date}.log")

        info('- Log file           : %s', self.log_file)
        info('- Output directory   : %s', kwargs.get('output_dir',
                                                     self.output_dir))
        info('- Non-default params :')
        for p in self.param:
            # FIXME: check params passed in kwargs
            if p.value is not None:
                info('%10s : %s (%s)', p.name, p.value, p.default)

        results = self._run(flist, *args, **kwargs)

        self.nbwarn = len(results.log.warning)
        self.timeit = (time.time() - t0) // 60
        info('%s successfully run, %d warnings', self.recipe_name, self.nbwarn)
        info('Execution time %g minutes', self.timeit)
        info('DRS user time: %s, sys: %s', results.stat.user_time,
             results.stat.sys_time)
        return results
