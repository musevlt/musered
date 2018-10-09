import datetime
import fnmatch
import inspect
import json
import logging
import numpy as np
import operator
import os
import shutil

from astropy.io import fits
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from glob import glob, iglob
from os.path import join
from sqlalchemy import sql

from .calib import CalibFinder
from .recipes import recipe_classes, init_cpl_params
from .reporter import Reporter
from .utils import (load_yaml_config, load_db, load_table, parse_raw_keywords,
                    parse_qc_keywords, ProgressBar, normalize_recipe_name,
                    parse_gto_db, upsert_many, parse_weather_conditions)
from .version import __version__

__all__ = ('MuseRed', )


class MuseRed(Reporter):
    """The main class handling all MuseRed's logic.

    This class manages the database, and use the settings file, to provide all
    the methods to operate on the datasets.

    """

    def __init__(self, settings_file='settings.yml', report_format='txt',
                 version=None):
        super().__init__(report_format=report_format)

        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file

        self.conf = load_yaml_config(settings_file)
        self.set_loglevel(self.conf.get('loglevel', 'info'))

        self.version = version or self.conf.get('version', '0.1')
        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.reduced_path = self.conf['reduced_path']

        self.db = load_db(self.conf['db'])

        version = self.version.replace('.', '_')
        self.tables = {'raw': 'raw',
                       'reduced': f'reduced_{version}',
                       'qa_raw': 'qa_raw',
                       'qa_reduced': f'qa_reduced_{version}', }
        for attrname, tablename in self.tables.items():
            setattr(self, attrname, self.db.create_table(tablename))

        self.rawc = self.raw.table.c
        self.execute = self.db.executable.execute

        self.calib = CalibFinder(self.reduced, self.conf)

        # configure cpl
        cpl_conf = self.conf['cpl']
        cpl_conf.setdefault('log_dir', join(self.reduced_path, 'logs'))
        init_cpl_params(**cpl_conf)

        # default params for recipes
        params = self.conf['recipes'].setdefault('common', {})
        params.setdefault('log_dir', cpl_conf['log_dir'])
        # params.setdefault('temp_dir', join(self.reduced_path, 'tmp'))

    @lazyproperty
    def nights(self):
        """Return the list of nights for which data is available."""
        if 'night' not in self.raw.columns:
            return []
        return self.select_column('night', distinct=True)

    @lazyproperty
    def runs(self):
        """Return the list of runs for which data is available."""
        if 'run' not in self.raw.columns:
            return []
        return self.select_column('run', distinct=True)

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

    def set_loglevel(self, level, cpl=False):
        logger = logging.getLogger('cpl' if cpl else 'musered')
        level = level.upper()
        logger.setLevel(level)
        logger.handlers[0].setLevel(level)

    def get_table(self, name):
        name = self.tables.get(name, name)
        if name not in self.db:
            raise ValueError('unknown table')
        return load_table(self.db, name)

    def select_column(self, name, notnull=True, distinct=False,
                      where=None, table='raw'):
        """Select values from a column of the database."""
        table = self.tables.get(table, table)
        col = self.db[table].table.c[name]
        wc = col.isnot(None) if notnull else None
        if where is not None:
            wc = sql.and_(where, wc)
        select = sql.select([col], whereclause=wc)
        if distinct:
            select = select.distinct(col)
        return [x[0] for x in self.execute(select)]

    def select_dates(self, dpr_type, table='raw', column='name', **kwargs):
        """Select the list of dates to process."""
        tbl = self.db[self.tables.get(table, table)]
        wc = (tbl.table.c.DPR_TYPE == dpr_type)
        dates = self.select_column(column, where=wc, table=table, **kwargs)
        return list(sorted(dates))

    def update_db(self, force=False):
        """Create or update the database containing FITS keywords."""

        # Get the list of FITS files in the raw directory
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

        # Get the list of files already in the database
        try:
            arcf = self.select_column('ARCFILE')
        except Exception:
            arcf = []

        # Parse FITS headers to get the keyword values
        rows, nskip = parse_raw_keywords(flist, force=force, processed=arcf,
                                         runs=self.conf.get('runs'))

        with self.db as tx:
            raw = tx['raw']
            reduced = tx[self.reduced.name]

            # Insert or update lines in the raw table
            if force:
                raw.delete()
                raw.insert_many(rows)
                self.logger.info('updated %d rows', len(rows))
            else:
                raw.insert_many(rows)
                self.logger.info('inserted %d rows, skipped %d',
                                 len(rows), nskip)

            # Create indexes if needed
            for name in ('night', 'name', 'DATE_OBS', 'DPR_TYPE'):
                if not raw.has_index([name]):
                    raw.create_index([name])

            for name in ('recipe_name', 'name', 'DATE_OBS', 'DPR_TYPE'):
                if name not in reduced.columns:
                    reduced.create_column_by_example(name, '')
                if len(reduced) and not reduced.has_index([name]):
                    reduced.create_index([name])

        # Update cached attributes (needed if the table was created)
        self.rawc = self.raw.table.c

        # weather conditions
        parse_weather_conditions(self)

        # GTO logs
        if 'GTO_logs' in self.conf:
            self.logger.info('Importing GTO logs')
            parse_gto_db(self.db, self.conf['GTO_logs']['db'])

        # Cleanup cached attributes
        del self.nights, self.runs, self.exposures

    def update_qc(self, dpr_types=None, recipe_name=None):
        """Create or update the tables containing QC keywords."""
        if recipe_name is not None:
            recipe_name = normalize_recipe_name(recipe_name)
            # select all types for a given recipe
            dpr_types = self.select_column(
                'DPR_TYPE', table='reduced', distinct=True,
                where=(self.reduced.table.c.recipe_name == recipe_name))
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

            if dpr_type in self.db:
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
        kwargs = dict(recipe_name=normalize_recipe_name(recipe_name))
        if date_list:
            if isinstance(date_list, str):
                date_list = [date_list]
            elif isinstance(date_list, (list, tuple)):
                if len(date_list) > 1:
                    raise ValueError('FIXME: this method works only with '
                                     'one date')
                else:
                    date_list = date_list[0]
            kwargs['name'] = date_list

        count = len(list(self.reduced.distinct('name', **kwargs)))

        if remove_files:
            for item in self.reduced.distinct('path', **kwargs):
                if os.path.exists(item['path']):
                    self.logger.info('Removing %s', item['path'])
                    shutil.rmtree(item['path'])

        if self.reduced.delete(**kwargs):
            self.logger.info('Removed %d exposures/nights from the database',
                             count)

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

    def _run_recipe_loop(self, recipe_cls, date_list, skip=False, calib=False,
                         params_name=None, recipe_kwargs=None, dry_run=False,
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
        ndates = len(date_list)
        log.info('Running %s for %d %ss', recipe_name, ndates, label)

        if skip and len(self.reduced) > 0:
            date_set = set(date_list)
            processed = [o['name'] for o in
                         self.reduced.find(recipe_name=recipe_name)]
            processed = set(processed) & date_set
            log.debug('processed:\n%s', '\n'.join(processed))

            if processed == date_set:
                log.info('Already processed, nothing to do')
                return
            elif len(processed) > 0:
                log.info('%d %ss already processed', len(processed), label)
        else:
            processed = set()

        # Instantiate the recipe object
        recipe_conf = self._get_recipe_conf(recipe_name)
        recipe = self._instantiate_recipe(recipe_cls, recipe_name,
                                          kwargs=recipe_kwargs)
        # save recipe's output dir as we will modify it later
        output_dir = recipe.output_dir

        table = self.reduced if use_reduced else self.raw
        for i, date in enumerate(date_list, start=1):
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
            log.info('%d/%d - %s %s : %d %s file(s), mode=%s', i,
                     ndates, label.capitalize(), date, len(flist),
                     DPR_TYPE, ins_mode)

            if recipe.use_drs_output:
                out = f'{date}.{ins_mode}' if calib else date
                kwargs['output_dir'] = join(self.reduced_path, output_dir, out)
            else:
                kwargs['output_dir'] = join(self.reduced_path, output_dir)

            kwargs.update(self.calib.get_frames(
                recipe, night=night, ins_mode=ins_mode,
                recipe_conf=recipe_conf, OBJECT=res[0]['OBJECT']))

            if recipe.use_illum:
                ref_temp = np.mean([o['INS_TEMP7_VAL'] for o in res])
                ref_date = np.mean([o['MJD_OBS'] for o in res])
                kwargs['illum'] = self.find_illum(night, ref_temp, ref_date)

            if dry_run:
                continue

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

            if ndates > 1:
                log.info('===================================================')

    def _run_recipe_simple(self, recipe_cls, name, OBJECT, flist,
                           params_name=None, **kwargs):
        """Run a recipe once, simpler than _run_recipe_loop.

        This is to run recipes like exp_align, exp_combine. Takes a list of
        files and process them.
        """
        self.logger.info('Running %s', recipe_cls.recipe_name)
        self.logger.info('%d files', len(flist))
        self.logger.debug('- ' + '\n- '.join(flist))

        # Instantiate the recipe object
        recipe_name = params_name or recipe_cls.recipe_name
        recipe_conf = self._get_recipe_conf(recipe_name)
        recipe = self._instantiate_recipe(recipe_cls, recipe_name)
        kwargs['output_dir'] = join(self.reduced_path, recipe.output_dir, name)
        kwargs.update(self.calib.get_frames(recipe, recipe_conf=recipe_conf,
                                            OBJECT=OBJECT))

        recipe.run(flist, params=recipe_conf.get('params'), **kwargs)
        self._save_reduced(recipe, keys=('name', 'recipe_name', 'DPR_TYPE'),
                           name=name, OBJECT=OBJECT, recipe_name=recipe_name)

    def _prepare_dates(self, dates, DPR_TYPE, datecol):
        """Compute the list of dates (nights, exposures) to process."""

        alldates = self.select_dates(DPR_TYPE, column=datecol, distinct=True)

        if dates is None:
            date_list = alldates
        else:
            if isinstance(dates, str):
                dates = [dates]

            date_list = []
            for date in dates:
                if date in self.runs:
                    d = self.select_column(
                        datecol, distinct=True,
                        where=sql.and_(self.rawc.run == date,
                                       self.rawc.DPR_TYPE == DPR_TYPE)
                    )
                    if d:
                        date_list += d
                elif date in alldates:
                    date_list.append(date)
                elif '*' in date:
                    date_list += fnmatch.filter(alldates, date)
                else:
                    self.logger.warning('Date %s not found', date)

        if date_list:
            date_list.sort()
            self.logger.debug('Selected dates:\n%s', '\n'.join(date_list))
        else:
            self.logger.warning('No valid date found')

        return date_list

    def process_calib(self, recipe_name, dates=None, skip=False,
                      **kwargs):
        """Run a calibration recipe."""

        recipe_cls = recipe_classes[normalize_recipe_name(recipe_name)]

        # get the list of nights to process
        dates = self._prepare_dates(dates, recipe_cls.DPR_TYPE, 'night')

        self._run_recipe_loop(recipe_cls, dates, calib=True, skip=skip,
                              **kwargs)

    def process_exp(self, recipe_name, dates=None, dataset=None, skip=False,
                    **kwargs):
        """Run a science recipe."""

        # get the list of dates to process
        if dates is None and dataset:
            dates = self.exposures[dataset]
        else:
            dates = self._prepare_dates(dates, 'OBJECT', 'name')

        recipe_name = normalize_recipe_name(recipe_name)
        recipe_cls = recipe_classes[recipe_name]
        use_reduced = recipe_name not in ('muse_scibasic', )
        self._run_recipe_loop(recipe_cls, dates, skip=skip,
                              use_reduced=use_reduced, **kwargs)

    def process_standard(self, dates=None, skip=False, **kwargs):
        """Reduce a standard exposure, running both muse_scibasic and
        muse_standard.
        """
        recipe_sci = recipe_classes['muse_scibasic']
        recipe_std = recipe_classes['muse_standard']

        # get the list of dates to process
        dates = self._prepare_dates(dates, 'STD', 'name')

        # run muse_scibasic with specific parameters (tag: STD)
        recipe = self._instantiate_recipe(recipe_std, 'muse_standard',
                                          verbose=False)
        recipe_kw = {'tag': 'STD', 'output_dir': recipe.output_dir}
        self._run_recipe_loop(recipe_sci, dates, skip=skip,
                              recipe_kwargs=recipe_kw, **kwargs)

        # run muse_standard
        self._run_recipe_loop(recipe_std, dates, skip=skip, use_reduced=True,
                              **kwargs)

    def compute_offsets(self, dataset, method='drs', filt='white',
                        name=None, exps=None, **kwargs):
        """Compute offsets between exposures."""

        recipe_name = kwargs.get('params_name') or 'muse_exp_align'
        recipe_conf = self._get_recipe_conf(recipe_name)
        from_recipe = recipe_conf.get('from_recipe', 'muse_scipost')
        method = recipe_conf.get('method', method)
        filt = recipe_conf.get('filt', filt)

        if method == 'drs':
            recipe_cls = recipe_classes['muse_exp_align']
        elif method == 'imphot':
            recipe_cls = recipe_classes['imphot']
            # by default use params from the muse_exp_align block
            if not kwargs.get('params_name'):
                kwargs['params_name'] = 'muse_exp_align'
        else:
            raise ValueError(f'unknown method {method}')

        DPR_TYPE = recipe_cls.DPR_TYPE
        name = name or recipe_conf.get('name') or f'OFFSET_LIST_{method}'

        # get the list of dates to process
        if exps:
            query = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                           recipe_name=from_recipe, name=exps))
        else:
            query = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                           recipe_name=from_recipe))

        flist = [f
                 for r in query
                 for f in iglob(f"{r['path']}/{DPR_TYPE}*.fits")]

        if filt and method == 'drs':
            flist = [f for f in flist
                     if fits.getval(f, 'ESO DRS MUSE FILTER NAME') == filt]

        self._run_recipe_simple(recipe_cls, name, dataset, flist, **kwargs)

        if method == 'imphot':
            # Special case to insert IMPHOT result files in the table
            info = self.reduced.find_one(name=name)
            del info['id']
            rows = [{**info, 'name': item['name'], 'DPR_TYPE': 'IMPHOT',
                     'path': join(info['path'], item['name'])}
                    for item in query]
            upsert_many(self.db, self.reduced.name, rows,
                        keys=('name', 'recipe_name', 'DPR_TYPE'))

    def exp_combine(self, dataset, method='drs', name=None, **kwargs):
        """Combine exposures."""

        recipe_name = kwargs.get('params_name') or 'muse_exp_combine'
        recipe_conf = self._get_recipe_conf(recipe_name)
        from_recipe = recipe_conf.get('from_recipe', 'muse_scipost')
        method = recipe_conf.get('method', method)

        if method == 'drs':
            recipe_cls = recipe_classes['muse_exp_combine']
        elif method == 'mpdaf':
            recipe_cls = recipe_classes['mpdaf_combine']
            kwargs.setdefault('params_name', 'muse_exp_combine')
        else:
            raise ValueError(f'unknown method {method}')

        DPR_TYPE = recipe_cls.DPR_TYPE
        name = name or method

        # get the list of dates to process
        flist = [next(iglob(f"{r['path']}/{DPR_TYPE}*.fits"))
                 for r in self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                            recipe_name=from_recipe)]

        self._run_recipe_simple(recipe_cls, name, dataset, flist, **kwargs)

    def _get_recipe_conf(self, recipe_name, item=None):
        """Get config dict foldr a recipe."""
        recipe_conf = self.conf['recipes'].get(recipe_name, {})
        if item is not None:
            return recipe_conf.get(item, {})
        else:
            return recipe_conf

    def _instantiate_recipe(self, recipe_cls, recipe_name, kwargs=None,
                            verbose=True):
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

        return recipe_cls(**recipe_kw, verbose=verbose)

    def _save_reduced(self, recipe, keys, DPR_CATG='SCIENCE',
                      recipe_name=None, **kwargs):
        """Save info about reduced data.

        - A JSON file is saved in the output directory, with all information
          including the complete list of calibration and input files.
        - For each output frame, the same information are saved except the
          calibration and input files, and after checking that files were
          created for each frame (some are optional).

        """
        date_run = datetime.datetime.now().isoformat()
        recipe_name = recipe_name or recipe.recipe_name
        info = {
            'date_run': date_run,
            'recipe_name': recipe_name,
            'path': recipe.output_dir,
            'DPR_CATG': DPR_CATG,
            'musered_version': __version__,
            **kwargs,
        }

        recipe_file = f'{recipe.output_dir}/{recipe_name}.json'
        with open(recipe_file, mode='w') as f:
            json.dump({**info, **recipe.dump(include_files=True)}, f, indent=4)

        rows = [{'DPR_TYPE': out_frame, **info, 'recipe_file': recipe_file,
                 **recipe.dump(json_col=True)}
                for out_frame in recipe.output_frames
                if any(iglob(f'{recipe.output_dir}/{out_frame}*.fits'))]
        upsert_many(self.db, self.reduced.name, rows, keys=keys)

        if len(rows) == 0:
            raise RuntimeError('could not find output files')
        self.logger.info('Processed data (%s) available in %s',
                         ', '.join(row['DPR_TYPE'] for row in rows),
                         recipe.output_dir)
