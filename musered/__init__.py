def _setup_logging():
    import warnings
    from astropy.units import UnitsWarning
    from mpdaf.log import setup_logging, clear_loggers

    # fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')
    setup_logging(name="", level="INFO", color=True, fmt="%(levelname)s %(message)s")
    clear_loggers("mpdaf")
    warnings.simplefilter("ignore", category=UnitsWarning)


_setup_logging()

from .flags import FLAGS, QAFlags  # noqa
from .musered import MuseRed  # noqa
from .recipes import *  # noqa
from .settings import RAW_FITS_KEYWORDS  # noqa
from .version import version as __version__  # noqa
