from mpdaf.log import setup_logging
from .musered import MuseRed

setup_logging(name='musered', level='INFO', color=True,
              fmt='%(levelname)s %(message)s')
# fmt='%(levelname)s - %(name)s: %(message)s')
# fmt='[%(process)s] %(levelname)s - %(name)s: %(message)s')
