import datetime
import glob
import logging
import os
from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from itertools import product

from .settings import STATIC_FRAMES
from .utils import parse_date

SPECIAL_FRAMES = ('OUTPUT_WCS', 'OFFSET_LIST', 'SKY_MASK', 'AUTOCAL_FACTORS')
"""Frames that can be set manually (to a file path) in the settings."""


def get_file_from_date(files_dict: dict, date: str) -> str:
    """Find a file that match a date requirement.

    Examples
    --------

    >>> import datetime
    >>> astrometry = {
    ...     'astrometry_wcs_wfm_gto26.fits': {
    ...         'start_date': datetime.date(2018, 8, 11),
    ...         'end_date': datetime.date(2018, 8, 26) },
    ...     'astrometry_wcs_wfm_gto27.fits': {
    ...         'start_date': datetime.date(2018, 9, 4),
    ...         'end_date': datetime.date(2018, 9, 15) },
    ... }
    >>> get_file_from_date(astrometry, '2018-08-13')
    'astrometry_wcs_wfm_gto26.fits'
    >>> get_file_from_date(astrometry, '2018-09-10')
    'astrometry_wcs_wfm_gto27.fits'
    >>> get_file_from_date(astrometry, '2018-01-01')

    """
    file = None
    dateobj = parse_date(date)
    for item, val in files_dict.items():
        start_date = val.get('start_date', datetime.date.min)
        end_date = val.get('end_date', datetime.date.max)
        if start_date <= dateobj <= end_date:
            file = item
            break
    return file


class FramesFinder:
    """Handles calibration frames.

    Parameters
    ----------
    mr : musered.MuseRed
        MuseRed object.

    """

    STATIC_FRAMES = STATIC_FRAMES

    def __init__(self, mr):
        self.mr = mr
        self.conf = mr.conf
        self.logger = logging.getLogger(__name__)
        self.static_path = self.conf['muse_calib_path']
        self.static_conf = self.conf['static_calib']

        # frames settings
        self.frames = self.conf.get('frames', {})
        self._excludes = {}

    @lazyproperty
    def static_files(self):
        """List of files in the static calibration path."""
        return os.listdir(self.static_path)

    @lazyproperty
    def static_by_catg(self):
        """Dict of static files indexed by PRO.CATG."""
        cat = defaultdict(list)
        for f in self.static_files:
            if f.endswith(('.fits', '.fits.fz', '.fits.gz')):
                key = fits.getval(os.path.join(self.static_path, f),
                                  'ESO PRO CATG', ext=0)
            cat[key].append(f)
        return cat

    def get_excludes(self, DPR_TYPE=None):
        """List of excluded files for each DPR_TYPE."""

        # the global list of excluded files is stored with the __all__ key
        key = '__all__' if DPR_TYPE is None else DPR_TYPE
        # check if the list is already computed
        if key in self._excludes:
            return self._excludes[key]

        conf = self.frames.get('exclude', {})
        if DPR_TYPE and DPR_TYPE not in conf:
            self._excludes[key] = []
            return []

        # use the exclude setting to build the list of excluded files
        exc = []
        raw_types = self.mr.select_column('DPR_TYPE', distinct=True)
        for dpr, items in conf.items():
            if DPR_TYPE and dpr != DPR_TYPE:
                pass
            table = self.mr.get_table('raw' if dpr in raw_types else 'reduced')
            for item in items:
                if isinstance(item, str):
                    exc.append(item)
                elif isinstance(item, dict):
                    # if the item is a dict use the keys/values to query the db
                    exc += [o['name'] for o in table.find(**item)]
                else:
                    raise ValueError(f'wrong format for {DPR_TYPE} excludes')

        self._excludes[key] = sorted(set(exc))
        return self._excludes[key]

    def is_valid(self, name, DPR_TYPE=None):
        """Check if an exposure is valid (i.e. not excluded)."""
        return name not in self.get_excludes(DPR_TYPE)

    def filter_valid(self, names, DPR_TYPE=None):
        exc = self.get_excludes(DPR_TYPE)
        return [name for name in names if name not in exc]

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
            if date is None:
                # no date: take the first item
                file = list(self.static_conf[catg].keys())[0]
            else:
                file = get_file_from_date(self.static_conf[catg], date)

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
        info = self.logger.info
        excludes = self.get_excludes(dpr_type)

        # Find calib for the given night, mode and type
        res = {o['name']: o for o in self.mr.reduced.find(
            night=night, INS_MODE=ins_mode, DPR_TYPE=dpr_type)}

        # Check if some calib must be excluded
        if res and excludes:
            for name in excludes:
                if name in res:
                    info('%s for night %s is excluded', dpr_type, night)
                    del res[name]

        # If no calib was found, iterate on the days before/after
        if not res and day_off is not None:
            if isinstance(night, str):
                night = parse_date(night)
            for off, direction in product(range(1, day_off + 1), (1, -1)):
                off = datetime.timedelta(days=off * direction)
                res = {o['name']: o for o in self.mr.reduced.find(
                    night=(night + off).isoformat(), INS_MODE=ins_mode,
                    DPR_TYPE=dpr_type)}
                if res and excludes:
                    for name in excludes:
                        if name in res:
                            info('%s for night %s is excluded', dpr_type,
                                 night)
                            del res[name]
                if res:
                    info('Using %s from night %s', dpr_type, night + off)
                    break

        if not res:
            raise ValueError(f'could not find {dpr_type} for night {night}')
        if len(res) == 1:
            # only one result, use it
            res = res.popitem()[1]
        elif len(res) > 1:
            # several results, need to choose
            raise NotImplementedError

        flist = sorted(glob.glob(f"{res['path']}/{dpr_type}*.fits"))
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

            elif frame in SPECIAL_FRAMES:
                if frame in frames_conf:
                    # Special handling for these optional frames :
                    # use directly the value from settings
                    if isinstance(frames_conf[frame], str):
                        framedict[frame] = frames_conf[frame]
                    elif isinstance(frames_conf[frame], dict):
                        file = get_file_from_date(frames_conf[frame], night)
                        if file is not None:
                            framedict[frame] = file
                    else:
                        raise ValueError(f'unknown format for frame {frame}, '
                                         f'it should be a str or dict')

                    # except for OFFSET_LIST, that can be set to a name that
                    # can be found in the database
                    if frame == 'OFFSET_LIST' and \
                            not os.path.isfile(framedict[frame]):
                        off = self.mr.reduced.find_one(
                            DPR_TYPE='OFFSET_LIST', OBJECT=OBJECT,
                            name=framedict[frame])
                        if off is None:
                            raise Exception(f'OFFSET_LIST "{framedict[frame]}"'
                                            ' not found')
                        framedict[frame] = f"{off['path']}/OFFSET_LIST.fits"

                    debug('- %s: %s', frame, framedict[frame])

            elif frame in frames_conf:
                # If path or glob pattern is specified in settings
                val = frames_conf[frame]
                if '*' in val:
                    framedict[frame] = sorted(glob.glob(val))
                else:
                    framedict[frame] = sorted(
                        glob.glob(f"{val}/{frame}*.fits"))
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
        for key, val in sorted(framedict.items()):
            if isinstance(val, str):
                info('- %-18s : %s', key, val)
            elif len(val) == 1:
                info('- %-18s : %s', key, val[0])
            else:
                info('- %-18s :', key)
                for v in val:
                    info('  - %s', v)
