import cpl
import datetime
import inspect
import itertools
import logging
import numpy as np
import operator
import os
import shutil

from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from glob import glob, iglob
from mpdaf.log import setup_logging
from os.path import join
from sqlalchemy import sql

from .recipes import recipe_classes
from .reporter import Reporter
from .static_calib import StaticCalib
from .utils import (load_yaml_config, load_db, load_table, parse_date,
                    parse_raw_keywords, parse_qc_keywords, ProgressBar)


class MuseRed(Reporter):
    """The main class handling all MuseRed's logic.

    This class manages the database, and use the settings file, to provide all
    the methods to operate on the datasets.

    """

    def __init__(self, settings_file='settings.yml', report_format='txt'):
        super().__init__(report_format=report_format)

        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file

        self.conf = load_yaml_config(settings_file)
        self.set_loglevel(self.conf.get('loglevel', 'info'))

        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.reduced_path = self.conf['reduced_path']

        self.db = load_db(self.conf['db'])
        self.raw = self.db.create_table('raw')
        self.reduced = self.db.create_table('reduced')

        self.rawc = self.raw.table.c
        self.redc = self.reduced.table.c
        self.execute = self.db.executable.execute

        self.static_calib = StaticCalib(self.conf['muse_calib_path'],
                                        self.conf['static_calib'])
        self.init_cpl_params()

    @lazyproperty
    def nights(self):
        """Return the list of nights for which data is available."""
        if 'night' not in self.raw.columns:
            return []
        return self.select_column('night', distinct=True)

    @lazyproperty
    def exposures(self):
        """Return a dict of science exposure per target."""
        if 'night' not in self.raw.columns:
            return {}
        out = defaultdict(list)
        for obj, name in self.execute(
                sql.select([self.rawc.OBJECT, self.rawc.name])
                .where(self.rawc.DPR_TYPE == 'OBJECT')):
            out[obj].append(name)
        return out

    def set_loglevel(self, level):
        logger = logging.getLogger('musered')
        level = level.upper()
        logger.setLevel(level)
        logger.handlers[0].setLevel(level)

    def get_table(self, name):
        if name not in self.db.tables:
            raise ValueError('unknown table')
        return load_table(self.db, name)

    def select_column(self, name, notnull=True, distinct=False,
                      whereclause=None, table='raw'):
        """Select values from a column of the database."""
        col = self.db[table].table.c[name]
        wc = col.isnot(None) if notnull else None
        if whereclause is not None:
            wc = sql.and_(whereclause, wc)
        select = sql.select([col], whereclause=wc)
        if distinct:
            select = select.distinct(col)
        return [x[0] for x in self.execute(select)]

    def select_dates(self, dpr_type, table='raw', column='name', **kwargs):
        """Select the list of dates to process."""
        tbl = self.raw if table == 'raw' else self.reduced
        wc = (tbl.table.c.DPR_TYPE == dpr_type)
        explist = self.select_column(column, whereclause=wc, table=table,
                                     **kwargs)
        return list(sorted(explist))

    def update_db(self, force=False):
        """Create or update the database containing FITS keywords."""
        flist = []
        for root, dirs, files in os.walk(self.raw_path):
            if root.endswith('.cache'):
                # skip the cache directory
                self.logger.debug('skipping %s', root)
                continue
            for f in files:
                if f.endswith(('.fits', '.fits.fz')):
                    flist.append(join(root, f))
        self.logger.info('found %d FITS files', len(flist))

        # get the list of files already in the database
        try:
            arcf = self.select_column('ARCFILE')
        except Exception:
            arcf = []

        rows, nskip = parse_raw_keywords(flist, force=force, processed=arcf)
        if force:
            self.raw.delete()
            self.raw.insert_many(rows)
            self.logger.info('updated %d rows', len(rows))
        else:
            self.raw.insert_many(rows)
            self.logger.info('inserted %d rows, skipped %d', len(rows), nskip)

        # cleanup cached attributes
        del self.nights

        for name in ('night', 'name', 'DATE_OBS', 'DPR_TYPE'):
            if not self.raw.has_index([name]):
                self.raw.create_index([name])

        if 'DATE_OBS' in self.reduced.columns:
            for name in ('name', 'DATE_OBS', 'DPR_TYPE'):
                if not self.reduced.has_index([name]):
                    self.reduced.create_index([name])

    def update_qc(self, dpr_types=None, recipe_name=None):
        """Create or update the tables containing QC keywords."""
        if recipe_name is not None:
            if not recipe_name.startswith('muse_'):
                recipe_name = 'muse_' + recipe_name
            # select all types for a given recipe
            dpr_types = self.select_column(
                'DPR_TYPE', table='reduced', distinct=True,
                whereclause=(self.redc.recipe_name == recipe_name))
        elif not dpr_types:
            # select all types
            dpr_types = self.select_column('DPR_TYPE', table='reduced',
                                           distinct=True)

        # Remove types for which there is no QC params
        excludes = ('TWILIGHT_CUBE', 'TRACE_SAMPLES', 'STD_FLUXES',
                    'STD_TELLURIC')
        for exc in excludes:
            if exc in dpr_types:
                dpr_types.remove(exc)

        now = datetime.datetime.now()
        for dpr_type in dpr_types:
            self.logger.info('Parsing %s files', dpr_type)

            if dpr_type in self.db.tables:
                self.logger.info('Dropping existing table')
                self.db[dpr_type].drop()
            table = self.db.create_table(dpr_type)
            # TODO: skip already parsed files

            rows = []
            items = list(self.reduced.find(DPR_TYPE=dpr_type))
            for item in ProgressBar(items):
                keys = {k: item[k] for k in ('name', 'DATE_OBS', 'INS_MODE')}
                keys['reduced_id'] = item['id']
                keys['recipe_name'] = item['recipe_name']
                keys['date_parsed'] = now
                flist = sorted(iglob(f"{item['path']}/{dpr_type}*.fits"))
                for row in parse_qc_keywords(flist):
                    rows.append({**keys, **row})

            if len(rows) == 0:
                self.logger.info('found no QC params')
                continue

            table.insert_many(rows)
            self.logger.info('inserted %d rows', len(rows))

    def clean(self, recipe_name, date_list=None, remove_files=True):
        if not recipe_name.startswith('muse_'):
            recipe_name = 'muse_' + recipe_name
        kwargs = dict(recipe_name=recipe_name)
        if date_list:
            if isinstance(date_list, str):
                date_list = [date_list]
            kwargs['name'] = date_list

        count = len(list(self.reduced.distinct('name', **kwargs)))

        if remove_files:
            for item in self.reduced.distinct('path', **kwargs):
                self.logger.info('Removing %s', item['path'])
                shutil.rmtree(item['path'])

        if self.reduced.delete(**kwargs):
            self.logger.info('Deleted %d exposures/nights', count)
        else:
            self.logger.info('Nothing to delete')

    def init_cpl_params(self):
        """Load esorex.rc settings and override with the settings file."""
        conf = self.conf['cpl']
        cpl.esorex.init()

        if conf['recipe_path'] is not None:
            cpl.Recipe.path = conf['recipe_path']
        if conf['esorex_msg'] is not None:
            cpl.esorex.log.level = conf['esorex_msg']  # file logging
        if conf['esorex_msg_format'] is not None:
            cpl.esorex.log.format = conf['esorex_msg_format']

        conf.setdefault('log_dir', join(self.reduced_path, 'logs'))
        os.makedirs(conf['log_dir'], exist_ok=True)

        # terminal logging: disable cpl's logger as it uses the root logger.
        cpl.esorex.msg.level = 'off'
        default_fmt = '%(levelname)s - %(name)s: %(message)s'
        setup_logging(name='cpl', level=conf.get('msg', 'info').upper(),
                      color=True, fmt=conf.get('msg_format', default_fmt))

        # default params for recipes
        params = self.conf['recipes'].setdefault('common', {})
        params.setdefault('log_dir', conf['log_dir'])
        params.setdefault('temp_dir', join(self.reduced_path, 'tmp'))

    def find_calib(self, night, dpr_type, ins_mode, day_off=None):
        """Return calibration files for a given night, type, and mode."""
        res = self.reduced.find_one(night=night, INS_MODE=ins_mode,
                                    DPR_TYPE=dpr_type)

        if res is None and day_off is not None:
            if isinstance(night, str):
                night = parse_date(night)
            for off, direction in itertools.product(range(1, day_off + 1),
                                                    (1, -1)):
                off = datetime.timedelta(days=off * direction)
                res = self.reduced.find_one(night=(night + off).isoformat(),
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

    def get_calib_frames(self, recipe, night, ins_mode, frames=None):
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
            if frame in self.static_calib.STATIC_FRAMES:
                framedict[frame] = self.static_calib.get(frame, date=night)
            else:
                day_off = day_offsets.get(frame, 1)
                framedict[frame] = self.find_calib(night, frame, ins_mode,
                                                   day_off=day_off)

        return framedict

    def get_additional_frames(self, recipe, recipe_name, OBJECT=None):
        """Return a dict with additional frames."""

        frames = {}
        recipe_conf = self._get_recipe_conf(recipe_name)

        if 'OFFSET_LIST' in recipe.calib and 'OFFSET_LIST' in recipe_conf:
            if os.path.isfile(recipe_conf['OFFSET_LIST']):
                frames['OFFSET_LIST'] = recipe_conf['OFFSET_LIST']
            else:
                off = self.reduced.find_one(DPR_TYPE='OFFSET_LIST',
                                            OBJECT=OBJECT,
                                            name=recipe_conf['OFFSET_LIST'])
                frames['OFFSET_LIST'] = f"{off['path']}/OFFSET_LIST.fits"
            self.logger.info('Using OFFSET_LIST: %s', frames['OFFSET_LIST'])

        if 'OUTPUT_WCS' in recipe.calib and 'OUTPUT_WCS' in recipe_conf:
            frames['OUTPUT_WCS'] = recipe_conf['OUTPUT_WCS']
            self.logger.info('Using OUTPUT_WCS: %s', frames['OUTPUT_WCS'])

        if 'FILTER_LIST' in recipe.calib:
            frames['FILTER_LIST'] = self.static_calib.get('FILTER_LIST')

        return frames

    def find_illum(self, night, ref_temp, ref_mjd_date):
        """Find the best ILLUM exposure for the night.

        First, illums are sorted by date to find the closest one in time, then
        if there are multiple illums within 2 hours, the one with the closest
        temperature is used.

        """
        illums = sorted(
            (o['DATE_OBS'],                       # Date
             abs(o['INS_TEMP7_VAL'] - ref_temp),  # Temperature difference
             abs(o['MJD_OBS'] - ref_mjd_date),    # Date difference
             o['path'])                           # File path
            for o in self.raw.find(DPR_TYPE='FLAT,LAMP,ILLUM', night=night))

        if len(illums) == 0:
            self.logger.warning('No ILLUM found')
            return

        # Filter illums to keep the ones within 2 hours
        close_illums = [illum for illum in illums if illum[2] < 2/24.]

        if len(close_illums) == 0:
            self.logger.warning('No ILLUM in less than 2h')
            res = illums[0]
        elif len(close_illums) == 1:
            self.logger.debug('Only one ILLUM in less than 2h')
            res = illums[0]
        else:
            self.logger.debug('More than one ILLUM in less than 2h')
            # Sort by temperature difference
            illums.sort(key=operator.itemgetter(1))
            res = illums[0]
            for illum in illums:
                self.logger.debug('%s Temp diff=%.2f Time diff=%.2f',
                                  illum[0], illum[1], illum[2] * 24 * 60)

        self.logger.info('Found ILLUM : %s (Temp diff: %.3f, Time diff: '
                         '%.2f min.)', res[0], res[1], res[2] * 24 * 60)
        if res[1] > 1:
            self.logger.warning('ILLUM with Temp difference > 1°, '
                                'not using it')
            return None

        return res[3]

    def run_recipe_loop(self, recipe_cls, date_list, skip=False, calib=False,
                        params_name=None, recipe_kwargs=None,
                        use_reduced=False, **kwargs):
        """Main method used to run a recipe on a list of exposures/nights.

        Parameters
        ----------
        recipe_cls : cls
            Must be a subclass of `musered.Recipe`.
        date_list : list of str
            List of dates (nights or exposure names) to process.
        skip : bool
            If True, dates already processed are skipped (default: False).
        calib : bool
            If True, process Calibration data, grouped by "night" (though this
            is also for day calibration !). This changes the columns used for
            queries.
        params_name : str
            By default the recipe name is obtained from the recipe class, but
            this parameter allows to change the name, which can be useful to
            have different parameters, and outputs stored under a different
            name.
        recipe_kwargs : dict
            Additional arguments passed to the `musered.Recipe` instantiation.
        use_reduced : bool
            If True, find data in the reduced table, otherwise on raw.
        **kwargs
            Additional arguments passed to `musered.Recipe.run`.

        """
        recipe_name = params_name or recipe_cls.recipe_name
        if calib:
            label = datecol = namecol = 'night'
        else:
            label = 'exposure'
            datecol = 'DATE_OBS'
            namecol = 'name'

        log = self.logger
        log.info('Running %s for %d %ss', recipe_name, len(date_list), label)
        log.debug(f'{label}s: ' + ', '.join(map(str, date_list)))

        if skip:
            processed = self.select_column(
                'name', table='reduced', distinct=True,
                whereclause=(self.redc.recipe_name == recipe_name))
            log.debug('processed: ' + ', '.join(map(str, sorted(processed))))
            if len(processed) == len(date_list):
                log.info('Already processed, nothing to do')
                return
            elif len(processed) > 0:
                log.info('%d %ss already processed', len(processed), label)

        # Instantiate the recipe object
        recipe_conf = self.conf['recipes'].get(recipe_name, {})
        recipe = self._instantiate_recipe(recipe_cls, recipe_name,
                                          kwargs=recipe_kwargs)
        # save recipe's output dir as we will modify it later
        output_dir = recipe.output_dir

        table = self.reduced if use_reduced else self.raw
        for date in date_list:
            if skip and date in processed:
                log.debug('%s already processed', date)
                continue

            DPR_TYPE = recipe_conf.get('DPR_TYPE', recipe.DPR_TYPE)
            select_args = {namecol: date, 'DPR_TYPE': DPR_TYPE}
            if recipe_conf.get('from_recipe'):
                select_args['recipe_name'] = recipe_conf.get('from_recipe')

            res = list(table.find(**select_args))

            if use_reduced:
                if len(res) != 1:
                    raise RuntimeError('could not find exposures')
                flist = sorted(glob(f"{res[0]['path']}/{DPR_TYPE}*.fits"))
                ins_mode = res[0]['INS_MODE']
            else:
                flist = [o['path'] for o in res]
                ins_mode = set(o['INS_MODE'] for o in res)
                if len(ins_mode) > 1:
                    raise ValueError(f'{label} with multiple INS.MODE, '
                                     'not supported yet')
                ins_mode = ins_mode.pop()

            night = res[0]['night']
            log.info('%s %s : %d %s files, mode=%s',
                     label, date, len(flist), DPR_TYPE, ins_mode)

            if recipe.use_drs_output:
                out = f'{date}.{ins_mode}' if calib else date
                kwargs['output_dir'] = join(self.reduced_path, output_dir, out)
            else:
                kwargs['output_dir'] = join(self.reduced_path, output_dir)

            kwargs.update(self.get_calib_frames(
                recipe, night, ins_mode, frames=recipe_conf.get('frames')))
            kwargs.update(self.get_additional_frames(recipe, recipe_name,
                                                     OBJECT=res[0]['OBJECT']))

            if recipe.use_illum:
                ref_temp = np.mean([o['INS_TEMP7_VAL'] for o in res])
                ref_date = np.mean([o['MJD_OBS'] for o in res])
                kwargs['illum'] = self.find_illum(night, ref_temp, ref_date)

            params = recipe_conf.get('params')
            recipe.run(flist, name=date, params=params, **kwargs)
            self._save_reduced(
                recipe, keys=('name', 'recipe_name', 'DPR_TYPE'), **{
                    'night': night,
                    'name': res[0][namecol],
                    'recipe_name': recipe_name,
                    'DATE_OBS': res[0][datecol],
                    'DPR_CATG': res[0]['DPR_CATG'],
                    'OBJECT': res[0]['OBJECT'],
                    'INS_MODE': ins_mode,
                })

    def run_recipe_simple(self, recipe_cls, name, OBJECT, flist,
                          params_name=None, **kwargs):
        """Run a recipe once, simpler than run_recipe_loop.

        This is to run recipes like exp_align, exp_combine. Takes a list of
        files and process them.
        """
        self.logger.info('Running %s', recipe_cls.recipe_name)
        self.logger.info('%d files', len(flist))
        self.logger.debug('- ' + '\n- '.join(flist))

        # Instantiate the recipe object
        recipe_name = params_name or recipe_cls.recipe_name
        recipe = self._instantiate_recipe(recipe_cls, recipe_name)
        kwargs['output_dir'] = join(self.reduced_path, recipe.output_dir, name)
        kwargs.update(self.get_additional_frames(recipe, recipe_name,
                                                 OBJECT=OBJECT))
        recipe_conf = self._get_recipe_conf(recipe_name)

        recipe.run(flist, params=recipe_conf.get('params'), **kwargs)
        self._save_reduced(recipe, keys=('name', 'recipe_name', 'DPR_TYPE'),
                           name=name, OBJECT=OBJECT, recipe_name=recipe_name)

    def process_calib(self, recipe_name, night_list=None, skip=False,
                      **kwargs):
        """Run a calibration recipe."""

        recipe_cls = recipe_classes['muse_' + recipe_name]

        # get the list of nights to process
        if night_list is None:
            night_list = self.select_dates(recipe_cls.DPR_TYPE, column='night',
                                           distinct=True)

        self.run_recipe_loop(recipe_cls, night_list, calib=True, skip=skip,
                             **kwargs)

    def process_exp(self, recipe_name, explist=None, dataset=None, skip=False,
                    **kwargs):
        """Run a science recipe."""

        # get the list of dates to process
        if explist is None:
            if dataset:
                explist = self.exposures[dataset]
            else:
                explist = list(itertools.chain(*self.exposures.values()))

        recipe_cls = recipe_classes['muse_' + recipe_name]
        use_reduced = recipe_name not in ('scibasic', )
        self.run_recipe_loop(recipe_cls, explist, skip=skip,
                             use_reduced=use_reduced, **kwargs)

    def process_standard(self, explist=None, skip=False, **kwargs):
        """Reduce a standard exposure, running both muse_scibasic and
        muse_standard.
        """
        recipe_sci = recipe_classes['muse_scibasic']
        recipe_std = recipe_classes['muse_standard']

        # get the list of dates to process
        if explist is None:
            explist = self.select_dates('STD', column='name')

        # run muse_scibasic with specific parameters (tag: STD)
        recipe_kw = {'tag': 'STD', 'output_dir': recipe_std.output_dir}
        self.run_recipe_loop(recipe_sci, explist, skip=skip,
                             recipe_kwargs=recipe_kw, **kwargs)

        # run muse_standard
        self.run_recipe_loop(recipe_std, explist, skip=skip, use_reduced=True,
                             **kwargs)

    def compute_offsets(self, dataset, method='drs', filt='white',
                        name=None, **kwargs):
        """Compute offsets between exposures."""

        recipe_conf = self._get_recipe_conf('muse_exp_align')
        from_recipe = recipe_conf.get('from_recipe', 'muse_scipost')
        method = recipe_conf.get('method', method)
        filt = recipe_conf.get('filt', filt)

        if method == 'drs':
            recipe_cls = recipe_classes['muse_exp_align']
        elif method == 'imphot':
            recipe_cls = recipe_classes['imphot']
            # by default use params from the muse_exp_align block
            kwargs.setdefault('params_name', 'muse_exp_align')
        else:
            raise ValueError(f'unknown method {method}')

        DPR_TYPE = recipe_cls.DPR_TYPE
        name = name or f'OFFSET_LIST_{method}'

        # get the list of dates to process
        flist = [f
                 for r in self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                            recipe_name=from_recipe)
                 for f in iglob(f"{r['path']}/{DPR_TYPE}*.fits")]

        if filt and method == 'drs':
            flist = [f for f in flist
                     if fits.getval(f, 'ESO DRS MUSE FILTER NAME') == filt]

        self.run_recipe_simple(recipe_cls, name, dataset, flist, **kwargs)

    def exp_combine(self, dataset, method='drs', name=None, **kwargs):
        """Combine exposures."""

        if method == 'drs':
            recipe_cls = recipe_classes['muse_exp_combine']
        elif method == 'mpdaf':
            raise NotImplementedError
        else:
            raise ValueError(f'unknown method {method}')

        DPR_TYPE = recipe_cls.DPR_TYPE
        name = name or method

        # get the list of dates to process
        flist = [next(iglob(f"{r['path']}/{DPR_TYPE}*.fits"))
                 for r in self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE)]

        self.run_recipe_simple(recipe_cls, name, dataset, flist, **kwargs)

    def _get_recipe_conf(self, recipe_name, item=None):
        """Get config dict foldr a recipe."""
        recipe_conf = self.conf['recipes'].get(recipe_name, {})
        if item is not None:
            return recipe_conf.get(item, {})
        else:
            return recipe_conf

    def _instantiate_recipe(self, recipe_cls, recipe_name, kwargs=None):
        """Instantiate the recipe object.  Use parameters from the settings,
        common first, and then from recipe_name.init, and from kwargs.
        """
        recipe_kw = {**self.conf['recipes']['common'],
                     **self._get_recipe_conf(recipe_name, 'init')}
        if kwargs is not None:
            recipe_kw.update(kwargs)

        # filter kwargs to match the signature
        sig = inspect.signature(recipe_cls)
        recipe_kw = {k: v for k, v in recipe_kw.items() if k in sig.parameters}

        return recipe_cls(**recipe_kw)

    def _save_reduced(self, recipe, keys, DPR_CATG='SCIENCE',
                      recipe_name=None, **kwargs):
        """Save info in database for each output frame, but check before that
        files were created for each frame (some are optional).
        """
        date_run = datetime.datetime.now().isoformat()
        recipe_name = recipe_name or recipe.recipe_name
        out_frames = []
        for out_frame in recipe.output_frames:
            if any(iglob(f"{recipe.output_dir}/{out_frame}*.fits")):
                out_frames.append(out_frame)
                self.reduced.upsert({
                    'date_run': date_run,
                    'recipe_name': recipe_name,
                    'path': recipe.output_dir,
                    'DPR_TYPE': out_frame,
                    'DPR_CATG': DPR_CATG,
                    **kwargs,
                    **recipe.dump()
                }, keys)

        if len(out_frames) == 0:
            raise RuntimeError('could not find output files')
        self.logger.info('Processed data (%s) available in %s',
                         ', '.join(out_frames), recipe.output_dir)
