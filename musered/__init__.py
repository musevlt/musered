# isort:skip_file

import warnings

from astropy.units import UnitsWarning
from mpdaf.log import clear_loggers, setup_logging

setup_logging(name="", level="INFO", color=True, fmt="%(levelname)s %(message)s")
clear_loggers("mpdaf")

from .flags import QAFlags, FLAGS  # noqa
from .musered import MuseRed  # noqa
from .recipes import *  # noqa
from .settings import RAW_FITS_KEYWORDS  # noqa
from .version import __version__  # noqa

warnings.simplefilter("ignore", category=UnitsWarning)

# fmt='%(levelname)s - %(name)s: %(message)s')
# fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')

del UnitsWarning, setup_logging, clear_loggers
