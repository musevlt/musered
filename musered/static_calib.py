import datetime
import logging
import os
from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import defaultdict

from .utils import parse_date


class StaticCalib:
    """Manage static calibrations.

    It must be instantiated with a directory containing the default static
    calibration files, and a settings dict that can be used to define time
    periods where a given calibration file is valid.

    Parameters
    ----------
    path : str
        Path of the static calibration files.
    conf : dict
        Settings dictionary.

    """
    def __init__(self, path, conf):
        self.path = path
        self.conf = conf

    @lazyproperty
    def files(self):
        """List of files in the static calibration path."""
        return os.listdir(self.path)

    @lazyproperty
    def catg_list(self):
        """Dict of static files indexed by PRO.CATG."""
        cat = defaultdict(list)
        for f in self.files:
            key = fits.getval(os.path.join(self.path, f),
                              'ESO PRO CATG', ext=0)
            cat[key].append(f)
        return cat

    def get(self, key, date=None):
        """Return a static calib file.

        Parameters
        ----------
        key : str
            The requested category (PRO.CATG).
        date : str, optional
            A date for which the file must be valid. This requires that
            validity dates are defined in the settings file.

        """
        file = None
        if key in self.conf:
            # if key is defined in the conf file, try to find a static calib
            # file that matched the date requirement
            for item, val in self.conf[key].items():
                if date is None:
                    file = item
                    break
                date = parse_date(date)
                start_date = val.get('start_date', datetime.date.min)
                end_date = val.get('end_date', datetime.date.max)
                if start_date < date < end_date:
                    file = item
                    break

        if file is None:
            # found nothing, use default from the static calib directory
            if len(self.catg_list[key]) > 1:
                logger = logging.getLogger(__name__)
                logger.warning('multiple options for %s, using the first '
                               'one: %r', key, self.catg_list[key])
            file = self.catg_list[key][0]

        if file not in self.files:
            raise ValueError(f'could not find {file}')
        return os.path.join(self.path, file)
