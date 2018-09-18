import cpl
import datetime
import json
import logging
import os
import shutil
import time
from astropy.io import fits
from mpdaf.log import setup_logging

__all__ = ('init_cpl_params', 'Recipe', 'PythonRecipe')


def init_cpl_params(recipe_path=None, esorex_msg=None, esorex_msg_format=None,
                    log_dir='.', msg='info',
                    msg_format='%(levelname)s - %(name)s: %(message)s'):
    """Load esorex.rc settings and override with the settings file."""
    cpl.esorex.init()

    if recipe_path is not None:
        cpl.Recipe.path = recipe_path
    if esorex_msg is not None:
        cpl.esorex.log.level = esorex_msg  # file logging
    if esorex_msg_format is not None:
        cpl.esorex.log.format = esorex_msg_format

    os.makedirs(log_dir, exist_ok=True)

    # terminal logging: disable cpl's logger as it uses the root logger.
    cpl.esorex.msg.level = 'off'
    setup_logging(name='cpl', level=msg.upper(), color=True, fmt=msg_format)


class Recipe:
    """Base class for the DRS Recipes.

    Parameters
    ----------
    output_dir : str
        Name of output directory.
    use_drs_output : bool
        If True, output files are saved by the DRS, else files are saved by
        musered with custom names (experimental!).
    temp_dir : str
        Base directory for temporary directories where the recipe is executed.
        The working dir is created as a subdir with a random file name. If set
        to None (default), the system temp dir is used.
    log_dir : str
        Directory for log files.
    version : str
        Version of the recipe. By default the latest version is used.
    nifu : int
        IFU to handle. If set to 0, all IFUs are processed serially. If set
        to -1 (default), all IFUs are processed in parallel.
    tag : str
        Tag used by the recipe, default to cpl.Recipe.tag. Can be used to
        change the type of processed input for e.g. muse_scibasic.

    """

    recipe_name = None
    """Name of the recipe."""

    recipe_name_drs = None
    """Real name of the recipe for the DRS, in case it is renamed in musex."""

    DPR_TYPE = None
    """Type of data to process (DPR.TYPE). If None, cpl.Recipe.tag is used."""

    DPR_TYPES = {}
    """Same as DPR_TYPE but when a recipe can process multiples types, e.g.
    muse_scibasic. If None, cpl.Recipe.tag is used."""

    output_dir = None
    """Default output directory."""

    default_params = None
    """Default parameters."""

    n_inputs_min = 1
    """Minimum number of input files, as required by the DRS."""

    n_inputs_rec = None
    """Recommended number of input files, typically for calibration files."""

    use_illum = None
    """If True, the recipe should use an ILLUM exposure."""

    env = None
    """Default environment variables."""

    exclude_frames = ('MASTER_DARK', 'NONLINEARITY_GAIN')
    """Frames that must be excluded by default."""

    QC_keywords = {}
    """QC keywords to show, for each frame."""

    def __init__(self, output_dir=None, use_drs_output=True, temp_dir='.',
                 log_dir='.', version=None, nifu=-1, tag=None):
        self.nbwarn = 0
        self.logger = logging.getLogger(__name__)
        self.outfiles = []
        self.log_dir = log_dir
        self.log_file = None
        self.use_drs_output = use_drs_output

        recipe_name = self.recipe_name_drs or self.recipe_name
        self._recipe = cpl.Recipe(recipe_name, version=version)

        if tag is not None:
            if tag not in self._recipe.tags:
                raise ValueError(f'invalid tag {tag} for {recipe_name}, '
                                 'should be in {self._recipe.tags}')
            self._recipe.tag = tag

        if self.DPR_TYPE is None:
            self.DPR_TYPE = self.DPR_TYPES.get(self._recipe.tag,
                                               self._recipe.tag)

        if output_dir is not None:
            self.output_dir = output_dir
        elif self.output_dir is None:
            self.output_dir = self.output_frames[0]

        self._recipe.output_dir = self.output_dir if use_drs_output else None
        if temp_dir is not None:
            self._recipe.temp_dir = temp_dir
            os.makedirs(temp_dir, exist_ok=True)

        self.param = self._recipe.param
        self.calib = self._recipe.calib
        self.raw = {}

        if self.env is not None:
            self._recipe.env.update(self.env)

        if 'nifu' in self.param:
            self.param['nifu'] = nifu

        if self.default_params is not None:
            for name, value in self.default_params.items():
                self.param[name] = value

        self.logger.info('%s recipe (DRS v%s from %s)', recipe_name,
                         self._recipe.version[1], cpl.Recipe.path)

    @property
    def calib_frames(self):
        """Return the list of calibration frames."""
        return list(dict(self.calib).keys())

    @property
    def output_frames(self):
        """Return the list of output frames."""
        frames = self._recipe.output[self._recipe.tag]
        if self.recipe_name == 'muse_scipost':
            # special case for scipost, for which some output frames are
            # missing from cpl's generated list. This was fixed in the DRS and
            # should appear in version > v2.5.2
            if 'DATACUBE_FINAL' not in frames:
                frames = ['DATACUBE_FINAL', 'IMAGE_FOV', 'OBJECT_RESAMPLED',
                          'PIXTABLE_REDUCED', 'PIXTABLE_POSITIONED',
                          'PIXTABLE_COMBINED'] + frames
        return frames

    def dump_params(self, json_col=False):
        """Dump non-default parameters to a JSON string."""
        params = {p.name: p.value for p in self.param if p.value is not None}
        return json.dumps(params) if json_col else params

    def dump(self, include_files=False, json_col=False):
        """Dump recipe results, stats, parameters in a dict."""
        info = {
            'tottime': self.timeit,
            'user_time': self.results.stat.user_time,
            'sys_time': self.results.stat.sys_time,
            'nbwarn': self.nbwarn,
            'log_file': self.log_file,
            'params': self.dump_params(json_col=json_col),
        }
        if include_files:
            calib = dict(self.calib)
            info['raw'] = json.dumps(self.raw) if json_col else self.raw
            info['calib'] = json.dumps(calib) if json_col else calib
        return info

    def _write_fits(self, name_or_hdulist, filename):
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

        self.outfiles.append(filename)

    def save_results(self, results, name=None):
        ifukey = 'ESO DRS MUSE PIXTABLE LIMITS IFU LOW'
        for frame in self.output_frames:
            if isinstance(results[frame], list):
                for p in results[frame]:
                    chan = p[0].header.get(ifukey)
                    outn = (f'{frame}-{name}-{chan:02d}.fits'
                            if (name and chan) else p[0].header['PIPEFILE'])
                    self._write_fits(p, os.path.join(self.output_dir, outn))
            else:
                p = results[frame]
                outn = f'{frame}-{name}.fits' if name else p.header['PIPEFILE']
                self._write_fits(p, os.path.join(self.output_dir, outn))

    def _run(self, raw, **kwargs):
        return self._recipe(raw=raw, **kwargs)

    def run(self, flist, *args, name=None, params=None, **kwargs):
        """Run the recipe.

        Subclasses should implement ._run in they need to customize this.

        """
        t0 = time.time()
        info = self.logger.info
        self.results = None

        if isinstance(flist, str):
            flist = [flist]

        if len(flist) == 0:
            raise ValueError('no exposure found')

        if len(flist) < self.n_inputs_min:
            raise ValueError(f'need at least {self.n_inputs_min} exposures')

        if self.n_inputs_rec and len(flist) != self.n_inputs_rec:
            self.logger.warning('Got %d files though the recommended number '
                                'is %d', len(flist), self.n_inputs_rec)

        if params is not None:
            for key, value in params.items():
                self.param[key] = value

        date = datetime.datetime.now().isoformat()
        cpl.esorex.log.filename = self.log_file = os.path.join(
            self.log_dir, f"{self.recipe_name}-{date}.log")

        if 'output_dir' in kwargs:
            self.output_dir = kwargs['output_dir']

        info('- Log file           : %s', self.log_file)
        info('- Output directory   : %s', self.output_dir)
        info('- Non-default params :')
        for p in self.param:
            # FIXME: check params passed in kwargs
            if p.value is not None:
                info('%15s = %s (%s)', p.name, p.value, p.default)

        for frame in self.calib_frames:
            try:
                self.calib[frame] = kwargs.pop(frame)
            except KeyError:
                pass

        self.raw = {self._recipe.tag: flist}
        if self.use_illum and kwargs.get('illum'):
            self.raw['ILLUM'] = kwargs.pop('illum')

        results = self._run(self.raw, *args, **kwargs)

        if self._recipe.output_dir is None:
            self.save_results(results, name=name)

        self.results = results
        self.nbwarn = len(results.log.warning)
        self.timeit = (time.time() - t0) / 60
        info('%s successfully run, %d warnings', self.recipe_name, self.nbwarn)
        info('Execution time %.2f minutes', self.timeit)
        info('DRS user time: %s, sys: %s', results.stat.user_time,
             results.stat.sys_time)
        return results


class PythonRecipe:

    recipe_name = None
    """Name of the recipe."""

    DPR_TYPE = None
    """Type of data to process (DPR.TYPE). If None, cpl.Recipe.tag is used."""

    output_dir = None
    """Default output directory."""

    default_params = None
    """Default parameters."""

    output_frames = None
    """Output frames."""

    def __init__(self, output_dir=None, log_dir='.'):
        self.nbwarn = 0
        self.logger = logging.getLogger(__name__)
        self.outfiles = []
        self.log_dir = log_dir
        self.log_file = None
        self.calib = {}
        self.param = {}

        if output_dir is not None:
            self.output_dir = output_dir
        elif self.output_dir is None:
            self.output_dir = self.output_frames[0]

    def dump(self, include_files=False):
        """Dump recipe results, stats, parameters in a dict."""
        return {
            'tottime': self.timeit,
            # 'user_time': self.results.stat.user_time,
            # 'sys_time': self.results.stat.sys_time,
            'nbwarn': self.nbwarn,
            'log_file': self.log_file,
            'params': json.dumps(self.param),
        }

    def _run(self, *args, **kwargs):
        raise NotImplementedError

    def run(self, flist, *args, params=None, **kwargs):
        """Run the recipe.

        Subclasses should implement ._run in they need to customize this.

        """
        t0 = time.time()
        info = self.logger.info
        self.results = None

        if isinstance(flist, str):
            flist = [flist]

        if len(flist) == 0:
            raise ValueError('no exposure found')

        date = datetime.datetime.now().isoformat()
        self.log_file = os.path.join(
            self.log_dir, f"{self.recipe_name}-{date}.log")

        if 'output_dir' in kwargs:
            self.output_dir = kwargs['output_dir']

        os.makedirs(self.output_dir, exist_ok=True)

        info('- Log file           : %s', self.log_file)
        info('- Output directory   : %s', self.output_dir)
        info('- Non-default params :')
        self.param = self.default_params.copy()
        for key in self.param:
            if key in params:
                info('%15s = %s (%s)', key, params[key], self.param[key])
                self.param[key] = params[key]

        results = self._run(flist, *args, **kwargs)
        self.results = results
        # self.nbwarn = len(results.log.warning)
        self.timeit = (time.time() - t0) / 60
        info('%s successfully run, %d warnings', self.recipe_name, self.nbwarn)
        info('Execution time %.2f minutes', self.timeit)
        return results
