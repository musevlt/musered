from astropy.units import UnitsWarning
from mpdaf.log import setup_logging, clear_loggers
import warnings

setup_logging(name='', level='INFO', color=True,
              fmt='%(levelname)s %(message)s')
clear_loggers('mpdaf')

from .flags import QAFlags  # noqa
from .musered import MuseRed  # noqa
from .recipes import *  # noqa
from .settings import RAW_FITS_KEYWORDS  # noqa
from .version import __version__  # noqa

warnings.simplefilter('ignore', category=UnitsWarning)

# fmt='%(levelname)s - %(name)s: %(message)s')
# fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')

del UnitsWarning, setup_logging, clear_loggers
