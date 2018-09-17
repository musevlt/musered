import datetime
import itertools
import logging
import os
from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from glob import glob

from .settings import STATIC_FRAMES
from .utils import parse_date


class CalibFinder:
    """Manage calibrations.

    It must be instantiated with a directory containing the default static
    calibration files, and a settings dict that can be used to define time
    periods where a given calibration file is valid.

    Parameters
    ----------
    static_path : str
        Path of the static calibration files.
    static_conf : dict
        Settings dictionary.

    """

    STATIC_FRAMES = STATIC_FRAMES

    def __init__(self, table, static_path, static_conf):
        self.table = table
        self.static_path = static_path
        self.static_conf = static_conf
        self.logger = logging.getLogger(__name__)

    @lazyproperty
    def static_files(self):
        """List of files in the static calibration path."""
        return os.listdir(self.static_path)

    @lazyproperty
    def static_by_catg(self):
        """Dict of static files indexed by PRO.CATG."""
        cat = defaultdict(list)
        for f in self.static_files:
            key = fits.getval(os.path.join(self.static_path, f),
                              'ESO PRO CATG', ext=0)
            cat[key].append(f)
        return cat

    def get_static(self, catg, date=None):
        """Return a static calib file.

        Parameters
        ----------
        catg : str
            The requested category (PRO.CATG).
        date : str, optional
            A date for which the file must be valid. This requires that
            validity dates are defined in the settings file.

        """
        file = None
        if catg in self.static_conf:
            # if catg is defined in the conf file, try to find a static calib
            # file that matched the date requirement
            for item, val in self.static_conf[catg].items():
                if date is None:
                    file = item
                    break
                dateobj = parse_date(date)
                start_date = val.get('start_date', datetime.date.min)
                end_date = val.get('end_date', datetime.date.max)
                if start_date < dateobj < end_date:
                    file = item
                    break

        if file is None:
            # found nothing, use default from the static calib directory
            if len(self.static_by_catg[catg]) > 1:
                self.logger.warning('multiple options for %s, using the first '
                                    'one: %r', catg, self.static_by_catg[catg])
            file = self.static_by_catg[catg][0]

        if file not in self.static_files:
            raise ValueError(f'could not find {file}')
        return os.path.join(self.static_path, file)

    def find_calib(self, night, dpr_type, ins_mode, day_off=None):
        """Return calibration files for a given night, type, and mode."""
        res = self.table.find_one(night=night, INS_MODE=ins_mode,
                                  DPR_TYPE=dpr_type)

        if res is None and day_off is not None:
            if isinstance(night, str):
                night = parse_date(night)
            for off, direction in itertools.product(range(1, day_off + 1),
                                                    (1, -1)):
                off = datetime.timedelta(days=off * direction)
                res = self.table.find_one(night=(night + off).isoformat(),
                                          INS_MODE=ins_mode,
                                          DPR_TYPE=dpr_type)
                if res is not None:
                    self.logger.warning('Using %s from night %s',
                                        dpr_type, night + off)
                    break

        if res is None:
            raise ValueError(f'could not find {dpr_type} for night {night}')

        flist = sorted(glob(f"{res['path']}/{dpr_type}*.fits"))
        if len(flist) not in (1, 24):
            raise ValueError(f'found {len(flist)} {dpr_type} files '
                             f'instead of (1, 24)')
        return flist

    def get_frames(self, recipe, night, ins_mode, frames=None):
        """Return a dict with all calibration frames for a recipe."""

        framedict = {}

        # Build the list of frames that must be found for the recipe
        frameset = set(recipe.calib_frames)
        # Remove frames excluded by default
        frameset.difference_update(recipe.exclude_frames)
        if frames is not None:
            for key, val in frames.items():
                if key == 'exclude':  # Remove frames to exclude
                    frameset.difference_update(val)
                elif key == 'include':  # Add frames to include
                    frameset.update(val)
                else:  # Otherwise add frame directly to the framedict
                    framedict[key] = val

        self.logger.info('Using frames: %s', frameset)

        # FIXME: find better way to manage day_offsets ?
        day_offsets = {'STD_TELLURIC': 5, 'STD_RESPONSE': 5,
                       'TWILIGHT_CUBE': 3}

        for frame in frameset:
            if frame in self.STATIC_FRAMES:
                framedict[frame] = self.get_static(frame, date=night)
            else:
                day_off = day_offsets.get(frame, 1)
                framedict[frame] = self.find_calib(night, frame, ins_mode,
                                                   day_off=day_off)

        return framedict
