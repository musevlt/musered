from astropy.units import UnitsWarning
from mpdaf.log import setup_logging
import warnings

from .flags import QAFlags  # noqa
from .musered import MuseRed  # noqa
from .recipes import *  # noqa
from .settings import RAW_FITS_KEYWORDS  # noqa
from .version import __version__, __description__  # noqa

warnings.simplefilter('ignore', category=UnitsWarning)

setup_logging(name='musered', level='INFO', color=True,
              fmt='%(levelname)s %(message)s')
# fmt='%(levelname)s - %(name)s: %(message)s')
# fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')

del UnitsWarning, setup_logging
