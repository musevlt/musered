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
    """Handles calibration frames.

    It must be instantiated with a settings dict containing the directory with
    the default static calibration files ('muse_calib_path'), and a settings
    dict that can be used to define time periods where a given calibration file
    is valid ('static_calib').

    Parameters
    ----------
    table : dataset.Table
        Table with reduced calibrations.
    conf : dict
        Settings dictionary.

    """

    STATIC_FRAMES = STATIC_FRAMES

    def __init__(self, table, conf):
        self.table = table
        self.conf = conf
        self.static_path = self.conf['muse_calib_path']
        self.static_conf = self.conf['static_calib']
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

    def get_frames(self, recipe, night=None, ins_mode=None, recipe_conf=None,
                   OBJECT=None):
        """Return a dict with all calibration frames for a recipe.

        Parameters
        ----------
        recipe : musered.Recipe
            The recipe for which calibration frames are needed.
        night : str
            The night for which calibrations are needed.
        ins_mode : str
            Instrument mode.
        recipe_conf : dict
            Settings for the recipe.
        OBJECT : str
            OBJECT name, use for frames specific to a given OBJECT
            (OFFSET_LIST, OUTPUT_WCS).

        """
        debug = self.logger.debug
        debug('Building the calibration frames dict')

        # Build the list of frames that must be found for the recipe
        frameset = set(recipe.calib_frames)
        debug('- calib frames: %s', frameset)

        # Remove frames excluded by default
        frameset.difference_update(recipe.exclude_frames)
        debug('- excluded frames: %s', recipe.exclude_frames)

        frames_conf = recipe_conf.get('frames', {}) if recipe_conf else {}
        for key, val in frames_conf.items():
            if isinstance(val, str):
                val = [val]
            if key == 'exclude':  # Remove frames to exclude
                debug('- exclude: %s', val)
                frameset.difference_update(val)
            elif key == 'include':  # Add frames to include
                debug('- include: %s', val)
                frameset.update(val)

        # Define day offsets, with default values that can be overloaded in
        # the settings
        day_offsets = {'STD_TELLURIC': 5, 'STD_RESPONSE': 5,
                       'TWILIGHT_CUBE': 3, **frames_conf.get('offsets', {})}

        framedict = {}
        for frame in frameset:
            if frame in self.STATIC_FRAMES:
                # Static frames
                framedict[frame] = self.get_static(frame, date=night)
                debug('- static: %s', framedict[frame])

            elif frame in ('OUTPUT_WCS', 'OFFSET_LIST'):
                # Special handling for these optional frames
                if 'OFFSET_LIST' in frames_conf:
                    offset_list = frames_conf['OFFSET_LIST']
                    if not os.path.isfile(offset_list):
                        off = self.table.find_one(DPR_TYPE='OFFSET_LIST',
                                                  OBJECT=OBJECT,
                                                  name=offset_list)
                        offset_list = f"{off['path']}/OFFSET_LIST.fits"

                    debug('- OFFSET_LIST: %s', offset_list)
                    framedict['OFFSET_LIST'] = offset_list

                if 'OUTPUT_WCS' in frames_conf:
                    framedict['OUTPUT_WCS'] = frames_conf['OUTPUT_WCS']
                    debug('- OUTPUT_WCS: %s', framedict['OUTPUT_WCS'])

            elif frame in frames_conf:
                # If path or glob pattern is specified in settings
                val = frames_conf[frame]
                if '*' in val:
                    framedict[frame] = sorted(glob(val))
                else:
                    framedict[frame] = sorted(glob(f"{val}/{frame}*.fits"))
                debug('- from conf: %s', framedict[frame])

            else:
                # Find frames in the database, for the given night, or using
                # offsets
                if ins_mode is None:
                    raise ValueError('ins_mode must be specified')
                day_off = day_offsets.get(frame, 1)
                framedict[frame] = self.find_calib(night, frame, ins_mode,
                                                   day_off=day_off)
                debug('- from db: %s', framedict[frame])

        self.pprint_framedict(framedict)
        return framedict

    def pprint_framedict(self, framedict):
        info = self.logger.info
        for key, val in framedict.items():
            if isinstance(val, str):
                info('- %12s : %s', key, val)
            else:
                info('- %12s :', key)
                for v in val:
                    info('  - %s', v)
