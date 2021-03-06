import datetime
import itertools
import json
import logging
import os
import re
import time

import cpl
from cpl.param import ParameterList
from mpdaf.log import setup_logfile, setup_logging

__all__ = ("init_cpl_params", "BaseRecipe", "Recipe", "PythonRecipe")


def init_cpl_params(
    recipe_path=None,
    esorex_msg=None,
    esorex_msg_format=None,
    log_dir=".",
    msg="info",
    msg_format="%(levelname)s - %(name)s: %(message)s",
):
    """Load esorex.rc settings and override with the settings file."""

    try:
        cpl.esorex.init()
    except FileNotFoundError as e:
        print(e)

    if recipe_path is not None:
        cpl.Recipe.path = recipe_path
    if esorex_msg is not None:
        cpl.esorex.log.level = esorex_msg  # file logging
    if esorex_msg_format is not None:
        cpl.esorex.log.format = esorex_msg_format

    os.makedirs(log_dir, exist_ok=True)

    # terminal logging: disable cpl's logger as it uses the root logger.
    cpl.esorex.msg.level = "off"
    try:
        setup_logging(name="cpl", level=msg.upper(), color=True, fmt=msg_format)
    except Exception:
        # This fails for some reason when running unit tests on Gitlab CI when
        # using Click's runner...
        pass
    logging.getLogger("cpl").setLevel("DEBUG")


class BaseRecipe:
    """Base class for the recipes."""

    recipe_name = None
    """Name of the recipe."""

    DPR_TYPE = None
    """Type of data to process (DPR.TYPE). If None, cpl.Recipe.tag is used."""

    output_dir = None
    """Default output directory."""

    default_params = {}
    """Default parameters."""

    output_frames = []
    """Output frames."""

    exclude_frames = set()
    """Frames that must be excluded by default."""

    version = None
    """Recipe version."""

    n_inputs_min = None
    """Minimum number of input files, as required by the DRS."""

    def __init__(self, output_dir=None, log_dir=".", temp_dir=None, **kwargs):
        self.nbwarn = 0
        self.timeit = 0
        self.logger = logging.getLogger(__name__)
        self.outfiles = []
        self.log_dir = log_dir
        self.log_file = None
        self.param = {}  # recipe parameters
        self.calib = {}  # calib frames
        self.raw = {}  # raw frames

        self.temp_dir = temp_dir
        if temp_dir is not None:
            os.makedirs(temp_dir, exist_ok=True)

        if output_dir is not None:
            self.output_dir = output_dir

    @property
    def calib_frames(self):
        """Return the list of calibration frames."""
        return set()

    def dump_params(self, json_col=False):
        """Dump non-default parameters to a JSON string."""
        return json.dumps(self.param) if json_col else self.param

    def dump(self, include_files=False, json_col=False):
        """Dump recipe results, stats, parameters in a dict."""
        info = {
            "tottime": self.timeit,
            "nbwarn": self.nbwarn,
            "log_file": self.log_file,
            "params": self.dump_params(json_col=json_col),
            "recipe_version": self.version,
        }
        if include_files:
            calib = dict(iter(self.calib))
            info["raw"] = json.dumps(self.raw) if json_col else self.raw
            info["calib"] = json.dumps(calib) if json_col else calib
        return info

    def activate_file_logger(self):
        """Activate the logging to a file."""
        raise NotImplementedError

    def deactivate_file_logger(self):
        """Deactivate the logging to a file."""
        raise NotImplementedError

    def _run(self, *args, **kwargs):
        raise NotImplementedError

    def run(self, flist, *args, params=None, **kwargs):
        """Run the recipe.

        Subclasses must implement `BaseRecipe._run` to customize this.

        Parameters
        ----------
        flist : str, list of str, or dict
            List of input raw files. Can be a file, list of files, or a dict
            with DPR_TYPE as key and list of files as value.
        params : dict
            Parameters for the recipe.
        *args, **kwargs
            Additional arguments are passed to `BaseRecipe._run`.

        """
        t0 = time.time()
        info = self.logger.info
        self.results = None

        if isinstance(flist, str):
            flist = [flist]

        if isinstance(flist, (list, tuple)):
            nfiles = len(flist)
        elif isinstance(flist, dict):
            nfiles = len(list(itertools.chain(*flist.values())))
        else:
            raise ValueError("flist should be a list or dict")

        if nfiles == 0:
            raise ValueError("no exposure found")

        if self.n_inputs_min is not None and nfiles < self.n_inputs_min:
            raise ValueError(f"need at least {self.n_inputs_min} exposures")

        if "output_dir" in kwargs:
            self.output_dir = kwargs["output_dir"]

        os.makedirs(self.output_dir, exist_ok=True)

        info("- Log file           : %s", self.log_file)
        info("- Output directory   : %s", self.output_dir)
        info("- Non-default params :")

        for key, value in self.default_params.items():
            self.param[key] = value

        if params is not None:
            for key, value in params.items():
                self.param[key] = value

        param = (
            dict(iter(self.param)) if not isinstance(self.param, dict) else self.param
        )
        for key, value in param.items():
            default = (
                self.param[key].default
                if isinstance(self.param, ParameterList)
                else self.default_params.get(key, "")
            )
            if value != default:
                info("%15s = %s (%s)", key, value, default)

        if isinstance(flist, dict):
            assert self.DPR_TYPE in flist
            self.raw = flist
        else:
            self.raw = {self.DPR_TYPE: flist}
        results = self._run(flist, *args, **kwargs)

        self.results = results
        self.timeit = (time.time() - t0) / 60
        info("%s successfully run", self.recipe_name)
        info("Execution time %.2f minutes", self.timeit)
        return results


class PythonRecipe(BaseRecipe):
    """Class for Python recipes."""

    def activate_file_logger(self):
        # setup a root logger, with a format similar to the DRS one
        date = datetime.datetime.now().isoformat()
        self.log_file = os.path.join(self.log_dir, f"{self.recipe_name}-{date}.log")
        fmt = "%(asctime)s [%(levelname)07s] %(name)s: %(message)s"
        kw = dict(
            name="", level="DEBUG", logfile=self.log_file, fmt=fmt, rotating=False
        )
        try:
            setup_logfile(datefmt="%H:%M:%S", **kw)
        except TypeError:
            # mpdaf<=3.2 does not support the datefmt parameter
            setup_logfile(**kw)
        self.logger.info("starting at %s", date)

    def deactivate_file_logger(self):
        # count the number of warnings/errors
        with open(self.log_file) as f:
            self.nbwarn = len(re.findall(r"\[WARNING\]|\[  ERROR\]", f.read()))

        self.logger.info("%d warnings", self.nbwarn)

        # remove the file logger
        logger = logging.getLogger("")
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)


class Recipe(BaseRecipe):
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

    recipe_name_drs = None
    """Name of the recipe for the DRS, in case it is renamed in musered."""

    DPR_TYPES = {}
    """Same as DPR_TYPE but when a recipe can process multiples types, e.g.
    muse_scibasic. If None, cpl.Recipe.tag is used."""

    n_inputs_min = 1
    """Minimum number of input files, as required by the DRS."""

    n_inputs_rec = None
    """Recommended number of input files, typically for calibration files."""

    env = None
    """Default environment variables."""

    exclude_frames = ("MASTER_DARK", "NONLINEARITY_GAIN")
    """Frames that must be excluded by default."""

    use_illum = None
    """If True, the recipe should use an ILLUM exposure."""

    QC_keywords = {}
    """QC keywords to show, for each frame."""

    def __init__(
        self,
        output_dir=None,
        use_drs_output=True,
        temp_dir=".",
        log_dir=".",
        version=None,
        nifu=-1,
        tag=None,
        verbose=True,
    ):
        super().__init__(output_dir=output_dir, log_dir=log_dir, temp_dir=temp_dir)
        self.use_drs_output = use_drs_output

        recipe_name = self.recipe_name_drs or self.recipe_name
        self._recipe = cpl.Recipe(recipe_name, version=version)

        if tag is not None:
            if tag not in self._recipe.tags:
                raise ValueError(
                    f"invalid tag {tag} for {recipe_name}, "
                    "should be in {self._recipe.tags}"
                )
            self._recipe.tag = tag

        if self.DPR_TYPE is None:
            self.DPR_TYPE = self.DPR_TYPES.get(self._recipe.tag, self._recipe.tag)

        elif self.output_dir is None:
            self.output_dir = self.output_frames[0]

        self._recipe.output_dir = self.output_dir if use_drs_output else None
        self._recipe.temp_dir = temp_dir

        self.calib = self._recipe.calib
        self.param = self._recipe.param

        if self.env is not None:
            self._recipe.env.update(self.env)

        if "nifu" in self.param:
            self.param["nifu"] = nifu

        if verbose:
            msg = "%s recipe (DRS v%s from %s)"
            self.logger.info(msg, recipe_name, self._recipe.version[1], cpl.Recipe.path)

    @property
    def calib_frames(self):
        return set(dict(iter(self.calib)).keys())

    @property
    def output_frames(self):
        """Return the list of output frames."""
        frames = self._recipe.output[self._recipe.tag]
        if self.recipe_name == "muse_scipost":
            # special case for scipost, for which some output frames are
            # missing from cpl's generated list. This was fixed in the DRS and
            # should appear in version > v2.5.2
            if "DATACUBE_FINAL" not in frames:
                frames = [
                    "DATACUBE_FINAL",
                    "IMAGE_FOV",
                    "OBJECT_RESAMPLED",
                    "PIXTABLE_REDUCED",
                    "PIXTABLE_POSITIONED",
                    "PIXTABLE_COMBINED",
                ] + frames
        return frames

    @property
    def version(self):
        """Return the recipe version"""
        return f"DRS-{self._recipe.version[1]}"

    def dump_params(self, json_col=False):
        params = {p.name: p.value for p in self.param if p.value is not None}
        return json.dumps(params) if json_col else params

    def dump(self, include_files=False, json_col=False):
        info = super().dump(include_files=include_files, json_col=json_col)
        info.update(
            {
                "user_time": self.results.stat.user_time,
                "sys_time": self.results.stat.sys_time,
            }
        )
        return info

    def activate_file_logger(self):
        date = datetime.datetime.now().isoformat()
        self.log_file = os.path.join(self.log_dir, f"{self.recipe_name}-{date}.log")
        cpl.esorex.log.filename = self.log_file
        self.logger.info("starting at %s", date)

    def deactivate_file_logger(self):
        cpl.esorex.log.filename = None

    def _run(self, flist, *args, **kwargs):
        if self.n_inputs_rec and len(flist) != self.n_inputs_rec:
            msg = "Got %d files though the recommended number is %d"
            self.logger.warning(msg, len(flist), self.n_inputs_rec)

        if self._recipe.output_dir is None:
            raise NotImplementedError
            # self.save_results(results, name=name)

        for frame in self.calib_frames:
            try:
                self.calib[frame] = kwargs.pop(frame)
            except KeyError:
                pass

        self.raw = {self._recipe.tag: flist}
        if self.use_illum and kwargs.get("illum"):
            self.raw["ILLUM"] = kwargs.pop("illum")

        results = self._recipe(raw=self.raw, **kwargs)

        self.nbwarn = len(results.log.warning)
        msg = "DRS user time: %s, sys: %s"
        self.logger.info(msg, results.stat.user_time, results.stat.sys_time)
        self.logger.info("%d warnings", self.nbwarn)
        return results
