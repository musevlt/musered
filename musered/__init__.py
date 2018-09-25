from astropy.units import UnitsWarning
from mpdaf.log import setup_logging
import warnings

from .musered import MuseRed  # noqa
from .recipes import *  # noqa

warnings.simplefilter('ignore', category=UnitsWarning)

setup_logging(name='musered', level='INFO', color=True,
              fmt='%(levelname)s %(message)s')
# fmt='%(levelname)s - %(name)s: %(message)s')
# fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')

del UnitsWarning, setup_logging
