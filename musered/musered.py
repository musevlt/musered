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
from astropy.table import Table, vstack
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from glob import glob, iglob
from os.path import join
from sqlalchemy import sql, column as sql_column, text as sql_text

from .flags import QAFlags
from .frames import FramesFinder
from .recipes import get_recipe_cls, normalize_recipe_name, init_cpl_params
from .reporter import Reporter
from .utils import (load_yaml_config, load_db, load_table, parse_raw_keywords,
                    parse_qc_keywords, ProgressBar, parse_gto_db, upsert_many,
                    parse_weather_conditions, dict_values)
from .version import __version__

__all__ = ('MuseRed', )


class MuseRed(Reporter):
    """The main class handling all MuseRed's logic.

    This class manages the database, and use the settings file, to provide all
    the methods to operate on the datasets.

    """

    def __init__(self, settings_file='settings.yml', report_format='txt',
                 version=None, settings_kw=None, loglevel=None):
        super().__init__(report_format=report_format)

        self.logger = logging.getLogger(__name__)
        self.logger.debug('loading settings from %s', settings_file)
        self.settings_file = settings_file

        self.conf = load_yaml_config(settings_file)
        if settings_kw:
            self.conf.update(settings_kw)

        self.set_loglevel(loglevel or self.conf.get('loglevel', 'INFO'))
        self.version = version or self.conf.get('version', '0.1')
        self.datasets = self.conf['datasets']
        self.raw_path = self.conf['raw_path']
        self.reduced_path = self.conf['reduced_path']

        self.db = load_db(filename=self.conf.get('db'),
                          db_env=self.conf.get('db_env'))

        version = self.version.replace('.', '_')
        self.tables = {
            'gto_logs': 'gto_logs',
            'qa_raw': 'qa_raw',
            'qa_reduced': f'qa_reduced_{version}',
            'qc_info': 'qc_info',
            'raw': 'raw',
            'reduced': f'reduced_{version}',
            'weather_conditions': 'weather_conditions',
        }
        for attrname, tablename in self.tables.items():
            setattr(self, attrname, self.db.create_table(tablename))

        # we defined it here as we don't want to create the table and attribute
        # yet, this will be done by the property
        self.tables['flags'] = f'flags_{version}'

        self.execute = self.db.executable.execute
        self.frames = FramesFinder(self)

        # configure cpl
        cpl_conf = self.conf['cpl']
        cpl_conf.setdefault('log_dir', join(self.reduced_path, 'logs'))
        init_cpl_params(**cpl_conf)

        # default params for recipes
        params = self.conf['recipes'].setdefault('common', {})
        params.setdefault('log_dir', cpl_conf['log_dir'])
        # params.setdefault('temp_dir', join(self.reduced_path, 'tmp'))

    @property
    def rawc(self):
        """The SQLAlchemy columns object for the raw table."""
        return self.raw.table.c

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
        return sorted(self.select_column('run', distinct=True))

    @lazyproperty
    def calib_exposures(self):
        """Return the calibration sequences (TPL.START) for each DPR_TYPE."""
        out = defaultdict(list)
        if 'night' not in self.raw.columns:
            return out
        for dpr_type, tpl_start in self.execute(
                sql.select([self.rawc.DPR_TYPE, self.rawc.TPL_START])
                .where(self.rawc.DPR_TYPE.isnot(None))
                .group_by(self.rawc.DPR_TYPE, self.rawc.TPL_START)):
            if self.frames.is_valid(tpl_start, dpr_type, column='TPL_START'):
                out[dpr_type].append(tpl_start)
        return out

    @lazyproperty
    def exposures(self):
        """Return a dict of science exposure per target."""
        out = defaultdict(list)
        if 'night' not in self.raw.columns:
            return out
        for obj, name in self.execute(
                sql.select([self.rawc.OBJECT, self.rawc.name])
                .order_by(self.rawc.name)
                .where(self.rawc.DPR_TYPE == 'OBJECT')):
            if self.frames.is_valid(name, 'OBJECT'):
                out[obj].append(name)
        return out

    @lazyproperty
    def flags(self):
        """Return the `QAFlags` object to manage flags."""
        version = self.version.replace('.', '_')
        flags_tbl = self.db.create_table(f'flags_{version}')
        return QAFlags(flags_tbl, additional_flags=self.conf.get('flags'))

    def set_loglevel(self, level, cpl=False):
        """Set the logging level for the root logger or the cpl logger."""
        logger = logging.getLogger('cpl' if cpl else '')
        level = level.upper()
        logger.setLevel(level)
        logger.handlers[0].setLevel(level)

    def get_table(self, name):
        """Return the dataset.Table from the database."""
        name = self.tables.get(name, name)
        if name not in self.db:
            raise ValueError(f'unknown table {name}')
        return self.db[name]

    def get_astropy_table(self, name, indexes=None):
        """Return a table from the database as an astropy Table."""
        name = self.tables.get(name, name)
        if name not in self.db:
            raise ValueError('unknown table')
        return load_table(self.db, name, indexes=indexes)

    def copy_reduced(self, version, recipes):
        """Copy reduced rows from another version.

        This is needed to start a new version without reprocessing from the
        start. It allows to copy the database records from the previous version
        to the reduced table of the current version.

        Parameters
        ----------
        version : str
            The version to copy from.
        recipes : list of str
            List of recipe names to copy.

        """
        version = version.replace('.', '_')
        if f'reduced_{version}' not in self.db.tables:
            raise ValueError

        tbl = self.db[f'reduced_{version}']
        keys = ('name', 'recipe_name', 'DPR_TYPE')

        # To force the creation of the table
        row = tbl.find_one(recipe_name=recipes)
        if row is None:
            self.logger.error('could not find recipes %s', recipes)
            return

        del row['id']
        self.reduced.upsert(row, keys)

        with self.db as tx:
            table = tx[self.reduced.name]
            for row in tbl.find(recipe_name=recipes):
                del row['id']
                table.upsert(row, keys=keys)

    def select_column(self, name, notnull=True, distinct=False,
                      where=None, table='raw'):
        """Select values from a column of the database."""
        col = self.get_table(table).table.c[name]
        wc = col.isnot(None) if notnull else None
        if where is not None:
            wc = sql.and_(where, wc)
        select = sql.select([col], whereclause=wc)
        if distinct:
            select = select.distinct(col)
        return [x[0] for x in self.execute(select)]

    def select_dates(self, dpr_type=None, table='raw', column='name',
                     where=None, **kwargs):
        """Select the list of dates to process."""
        tbl = self.get_table(table)
        if dpr_type is not None:
            wc = (tbl.table.c.DPR_TYPE == dpr_type)
            if where is not None:
                where = where & wc
            else:
                where = wc
        dates = self.select_column(column, where=where, table=table, **kwargs)
        dates = self.frames.filter_valid(dates, DPR_TYPE=dpr_type,
                                         column=column)
        return list(sorted(dates))

    def get_processed(self, table='reduced', filter_names=None, **clauses):
        """Return the list of processed names for a given query."""
        try:
            tbl = self.get_table(table)
        except ValueError:
            # table does not exist
            return []

        processed = set(o['name'] for o in tbl.find(**clauses))
        if filter_names:
            processed = processed & set(filter_names)

        if len(processed) > 0:
            self.logger.debug('Processed:')
            for exp in sorted(processed):
                self.logger.debug('- %s', exp)
        return processed

    def get_files(self, DPR_TYPE, first_only=False, remove_excludes=False,
                  select=None, exclude_flags=None, return_explist=False,
                  **clauses):
        """Return the list of files for a given DPR_TYPE and a query.

        Parameters
        ----------
        DPR_TYPE : str
            DPR.TYPE of files to find.
        first_only : bool
            When an item gives several files, return only the first one.
        remove_excludes : bool
            If True removes files that are listed in the exclude settings.
        select : dict
            Allows to make selection on any table. This should be a dict of
            (tablename, dict), where the dict value defines a query to make
            with dataset's find method.
        exclude_flags : list of flags
            List of flags to exclude.
        return_explist : bool
            If True, also return the list of exposure names.
        **clauses
            Parameters passed to `self.reduced.find`.

        """
        flist = []
        exc = set()
        if remove_excludes:
            exc.update(self.frames.get_excludes(DPR_TYPE=DPR_TYPE))

        if exclude_flags is not None:
            exc.update(self.get_flagged(exclude_flags))

        if select is not None:
            names = set()
            for key, val in select.items():
                if isinstance(val, str):
                    # raw sql query
                    res = [x[0] for x in self.execute(
                        sql.select([sql_column('name')])
                        .where(sql_text(val))
                        .select_from(self.get_table(key).table))]
                elif isinstance(val, dict):
                    tbl = self.get_table(key)
                    if key == 'raw' and 'OBJECT' in clauses:
                        kw = dict(OBJECT=clauses['OBJECT'])
                    else:
                        kw = {}
                    res = [x['name'] for x in tbl.find(**val, **kw)]
                else:
                    raise ValueError('query should be a string or dict')
                names.update(res)

            clauses['name'] = list(names)

        ntot = 0
        explist = []
        for r in self.reduced.find(DPR_TYPE=DPR_TYPE, **clauses):
            ntot += 1
            if r['name'] in exc:
                continue

            explist.append(r['name'])
            files = iglob(f"{r['path']}/{DPR_TYPE}*.fits")
            if first_only:
                flist.append(next(files))
            else:
                flist.extend(files)

        self.logger.info('Selected %d files out of %d', len(flist), ntot)
        if return_explist:
            return flist, explist
        else:
            return flist

    def get_flagged(self, exclude_flags):
        """Return the list of flagged exposures.

        Parameters
        ----------
        exclude_flags : list or bool
            List of flags, or True to use all flags.

        """
        if isinstance(exclude_flags, (list, tuple)):
            return self.flags.find(*exclude_flags)
        elif exclude_flags is True:
            # exclude all flagged exposures
            return self.flags.find(*list(self.flags.flags))
        else:
            raise ValueError('wrong format for exclude_flags, it should '
                             'be a dict or True to exclude all flags')

    def update_db(self, force=False):
        """Create or update the database containing FITS keywords."""

        # Already parsed raw files
        known_files = (self.select_column('filename')
                       if 'filename' in self.raw.columns else [])

        # Get the list of FITS files in the raw directory
        nskip = 0
        flist = []
        for root, dirs, files in os.walk(self.raw_path):
            if root.endswith('.cache'):
                # skip the cache directory
                self.logger.debug('skipping %s', root)
                continue
            for f in files:
                if f.endswith(('.fits', '.fits.fz')):
                    if f in known_files:
                        nskip += 1
                        if not force:
                            continue
                    flist.append(join(root, f))

        self.logger.info('%d new FITS files, %d known', len(flist), nskip)

        # Parse FITS headers to get the keyword values
        rows = parse_raw_keywords(flist, runs=self.conf.get('runs'))

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

        # weather conditions
        parse_weather_conditions(self, force=force)

        # GTO logs
        if 'GTO_logs' in self.conf:
            self.logger.info('Importing GTO logs')
            parse_gto_db(self.db, self.conf['GTO_logs']['db'])

        # Cleanup cached attributes
        del self.nights, self.runs, self.exposures

    def update_qc(self, dpr_types=None, recipe_name=None, force=False):
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

        now = datetime.datetime.now().isoformat()
        for dpr_type in dpr_types:
            self.logger.info('Parsing %s files', dpr_type)

            tbl = self.db[f'qc_{dpr_type}']
            if not force:
                processed = self.get_processed(table=tbl.name,
                                               version=self.version)
                self.logger.info('Found %d processed exps', len(processed))
            else:
                processed = set()

            rows = []
            items = list(self.reduced.find(DPR_TYPE=dpr_type))
            for item in ProgressBar(items):
                if item['name'] in processed:
                    continue

                keys = {
                    'name': item['name'],
                    'reduced_id': item['id'],
                    'version': self.version,
                    'recipe_name': item['recipe_name'],
                    'date_parsed': now,
                    **{k: item[k] for k in ('DATE_OBS', 'INS_MODE', 'run')}
                }
                flist = sorted(iglob(f"{item['path']}/{dpr_type}*.fits"))
                for row in parse_qc_keywords(flist):
                    rows.append({**keys, **row})

            if len(rows) == 0:
                self.logger.info('nothing to do')
                continue

            tbl.insert_many(rows)
            self.logger.info('inserted %d rows', len(rows))
            self.qc_info.upsert(
                {'DPR_TYPE': dpr_type, 'table': f'qc_{dpr_type}',
                 'version': self.version, 'date_updated': now,
                 'nrows': tbl.count(version=self.version)},
                ['DPR_TYPE', 'version'])

    def clean(self, recipe_list=None, date_list=None, night_list=None,
              remove_files=True, force=False):
        """Remove database entries and files."""
        for attr in (date_list, night_list):
            if attr and isinstance(attr, str):
                raise ValueError(f'{attr} should be a list')
        if isinstance(recipe_list, str):
            recipe_list = [recipe_list]

        kwargs = {}
        if recipe_list:
            kwargs = {'recipe_name': [normalize_recipe_name(rec)
                                      for rec in recipe_list]}
        if date_list:
            kwargs['name'] = self.prepare_dates(date_list, datecol='name',
                                                table='reduced')
        if night_list:
            kwargs['night'] = self.prepare_dates(night_list, datecol='night',
                                                 table='reduced')

        count = len(set(o['name'] for o in self.reduced.find(**kwargs)))
        action = 'Remove' if force else 'Would remove'
        if not force:
            self.logger.info('Dry-run mode, nothing will be done')

        if remove_files:
            for item in set(o['path'] for o in self.reduced.find(**kwargs)):
                if os.path.exists(item):
                    self.logger.info('%s %s', action, item)
                    if force:
                        shutil.rmtree(item)

        self.logger.info('%s %d exposures/nights from the database',
                         action, count)
        if force:
            self.reduced.delete(**kwargs)

    def find_illum(self, night, ref_temp, ref_mjd_date):
        """Find the best ILLUM exposure for the night.

        First, illums are sorted by date to find the closest one in time, then
        if there are multiple illums within 2 hours, the one with the closest
        temperature is used.

        """
        illums = [
            {'date': o['DATE_OBS'],                         # Date
             'temp': abs(o['INS_TEMP7_VAL'] - ref_temp),    # Temperature diff
             'mjd': abs(o['MJD_OBS'] - ref_mjd_date) * 24,  # Date diff (hours)
             'path': o['path']}                             # File path
            for o in self.raw.find(DPR_TYPE='FLAT,LAMP,ILLUM', night=night)]

        logger = self.logger
        if len(illums) == 0:
            logger.warning('No ILLUM found')
            return

        # sort by time difference
        illums.sort(key=operator.itemgetter('mjd'))

        # Filter illums to keep the ones within 2 hours
        close_illums = [illum for illum in illums if illum['mjd'] < 2]

        if len(close_illums) == 0:
            logger.warning('No ILLUM in less than 2h, taking the closest one')
            res = illums[0]
        elif len(close_illums) == 1:
            logger.debug('Only one ILLUM in less than 2h')
            res = close_illums[0]
        else:
            logger.debug('More than one ILLUM in less than 2h, take closest '
                         'temperature')
            # Sort by temperature difference
            close_illums.sort(key=operator.itemgetter('temp'))
            res = close_illums[0]
            for illum in close_illums:
                logger.debug('%s Temp diff=%.2f Time diff=%.2f',
                             illum['date'], illum['temp'], illum['mjd'] * 60)

        logger.info('Found ILLUM : %s (Temp diff: %.3f, Time diff: %.2f min.)',
                    res['date'], res['temp'], res['mjd'] * 60)
        if res['temp'] > 1:
            logger.warning('ILLUM with Temp difference > 1°, not using it')
            return None

        return res['path']

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
            label = 'calibration sequence'
            datecol = namecol = 'TPL_START'
        else:
            label = 'exposure'
            datecol = 'DATE_OBS'
            namecol = 'name'

        log = self.logger
        ndates = len(date_list)
        log.info('Running %s for %d %ss', recipe_name, ndates, label)

        if skip and len(self.reduced) > 0:
            processed = self.get_processed(recipe_name=recipe_name,
                                           filter_names=date_list)
            if processed == set(date_list):
                log.info('Already processed, nothing to do')
                return
            log.info('Found %d processed exps', len(processed))
        else:
            processed = set()

        # Instantiate the recipe object
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
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
                if len(res) == 0:
                    raise RuntimeError('could not find exposures')
                elif len(res) > 1:
                    raise RuntimeError('found several input frames instead of '
                                       'one. Maybe use "from_recipe" ?')
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

            if getattr(recipe, 'use_drs_output', True):
                out = f'{date}.{ins_mode}' if calib else date
                kwargs['output_dir'] = join(self.reduced_path, output_dir, out)
            else:
                kwargs['output_dir'] = join(self.reduced_path, output_dir)

            kwargs.update(self.frames.get_frames(
                recipe, night=night, ins_mode=ins_mode, dry_run=dry_run,
                recipe_conf=recipe_conf, OBJECT=res[0]['OBJECT']))

            if getattr(recipe, 'use_illum', False):
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
                    'run': res[0]['run'],
                    'recipe_name': recipe_name,
                    'DATE_OBS': res[0][datecol],
                    'DPR_CATG': res[0]['DPR_CATG'],
                    'OBJECT': res[0]['OBJECT'],
                    'INS_MODE': ins_mode,
                })

            if ndates > 1:
                log.info('===================================================')

    def _run_recipe_simple(self, recipe_cls, name, OBJECT, flist,
                           params_name=None, save_kwargs=None,
                           dry_run=False, **kwargs):
        """Run a recipe once, simpler than _run_recipe_loop.

        This is to run recipes like exp_align, exp_combine. Takes a list of
        files and process them.
        """
        self.logger.info('Running %s', recipe_cls.recipe_name)
        if isinstance(flist, (list, tuple)):
            self.logger.info('%d files', len(flist))
            self.logger.debug('- ' + '\n- '.join(flist))
        elif isinstance(flist, dict):
            self.logger.info('%d files', len(dict_values(flist)))
            self.logger.debug('- ' + '\n- '.join(flist))  # FIXME: improve this

        # Instantiate the recipe object
        recipe_name = params_name or recipe_cls.recipe_name
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
        recipe = self._instantiate_recipe(recipe_cls, recipe_name)
        kwargs['output_dir'] = join(self.reduced_path, recipe.output_dir, name)
        kwargs.update(self.frames.get_frames(recipe, recipe_conf=recipe_conf,
                                             OBJECT=OBJECT))

        if dry_run:
            return

        recipe.run(flist, params=recipe_conf.get('params'), **kwargs)
        self._save_reduced(recipe, keys=('name', 'recipe_name', 'DPR_TYPE'),
                           name=name, OBJECT=OBJECT, recipe_name=recipe_name,
                           **(save_kwargs or {}))

    def prepare_dates(self, dates, DPR_TYPE=None, datecol='name', table='raw'):
        """Compute the list of dates (nights, exposures) to process."""

        alldates = self.select_dates(dpr_type=DPR_TYPE, column=datecol,
                                     distinct=True, table=table)

        if dates is None:
            date_list = alldates
        else:
            if isinstance(dates, str):
                dates = [dates]

            date_list = []
            tbl = self.get_table(table).table
            for date in dates:
                if date in self.runs:
                    where = (tbl.c.run == date)
                    if DPR_TYPE is not None:
                        where &= (tbl.c.DPR_TYPE == DPR_TYPE)
                    d = self.select_column(datecol, distinct=True, where=where,
                                           table=table)
                    if d:
                        d = self.frames.filter_valid(d, DPR_TYPE=DPR_TYPE,
                                                     column=datecol)
                        date_list += d
                elif date in self.nights:
                    where = (tbl.c.night == date)
                    if DPR_TYPE is not None:
                        where &= (tbl.c.DPR_TYPE == DPR_TYPE)
                    d = self.select_column(datecol, distinct=True, where=where,
                                           table=table)
                    if d:
                        d = self.frames.filter_valid(d, DPR_TYPE=DPR_TYPE,
                                                     column=datecol)
                        date_list += d
                elif date in alldates:
                    date_list.append(date)
                elif '*' in date:
                    date_list += fnmatch.filter(alldates, date)
                else:
                    self.logger.warning('Date %s not found', date)

        if date_list:
            date_list.sort()
            self.logger.debug('Selected dates:')
            for date in date_list:
                self.logger.debug('- %s', date)
        else:
            self.logger.warning('No valid date found')

        return date_list

    def process_calib(self, recipe_name, dates=None, params_name=None,
                      **kwargs):
        """Run a calibration recipe.

        Parameters
        ----------
        recipe_name : str
            Recipe to run.
        dates : str or list of str
            List of dates to process.
        params_name : str
            Name of the parameter block, default to recipe_name.
        **kwargs :
            Additional arguments passed to _run_recipe_loop.

        """
        recipe_cls = get_recipe_cls(recipe_name)
        # get the list of nights to process
        dates = self.prepare_dates(dates, DPR_TYPE=recipe_cls.DPR_TYPE,
                                   datecol='TPL_START')
        self._run_recipe_loop(recipe_cls, dates, calib=True,
                              params_name=params_name, **kwargs)

    def process_exp(self, recipe_name, dates=None, dataset=None,
                    params_name=None, **kwargs):
        """Run a science recipe.

        Parameters
        ----------
        recipe_name : str
            Recipe to run.
        dates : str or list of str
            List of dates to process.
        dataset : str
            If given, all exposures from this dataset are processed.
        params_name : str
            Name of the parameter block, default to recipe_name.
        **kwargs :
            Additional arguments passed to _run_recipe_loop.

        """
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
        redc = self.reduced.table.c

        # get the list of dates to process
        if dates is None and dataset:
            dates = self.exposures[dataset]
        elif dates is None and 'from_recipe' in recipe_conf:
            dates = [o['name'] for o in self.reduced.find(
                recipe_name=recipe_conf['from_recipe'])]
            dates = self.select_dates(
                table='reduced', distinct=True,
                where=(redc.recipe_name == recipe_conf['from_recipe']))
        else:
            dates = self.prepare_dates(dates, DPR_TYPE='OBJECT')

        if recipe_name == 'superflat':
            # Build a Table (name, run, path) for PIXTABLE_REDUCED that can
            # be used for the superflats
            rawc = self.rawc
            wc = (redc.DPR_TYPE == 'PIXTABLE_REDUCED')
            if 'from_recipe' in recipe_conf:
                wc = wc & (redc.recipe_name == recipe_conf['superflat_from'])
            exps = [
                (name, run, path)
                for (name, run, path) in self.execute(
                    sql.select([rawc.name, rawc.run, redc.path])
                    .select_from(self.reduced.table
                                 .join(self.raw.table, redc.name == rawc.name))
                    .where(wc)
                    .order_by(rawc.name))
            ]
            tbl = Table(rows=exps, names=('name', 'run', 'path'))

            if 'exclude_flags' in recipe_conf:
                # exclude flagged exposures
                excludes = self.get_flagged(recipe_conf['exclude_flags'])
                tbl['excluded'] = np.in1d(tbl['name'], excludes)
            else:
                tbl['excluded'] = False

            kwargs['exposures'] = tbl

        recipe_cls = get_recipe_cls(recipe_name)
        use_reduced = recipe_cls.recipe_name not in ('muse_scibasic', )
        self._run_recipe_loop(recipe_cls, dates, params_name=params_name,
                              use_reduced=use_reduced, **kwargs)

    def process_standard(self, recipe_name='muse_standard', dates=None,
                         **kwargs):
        """Reduce a standard exposure.

        Running both muse_scibasic and muse_standard.

        Parameters
        ----------
        recipe_name : str
            Recipe to run.
        dates : str or list of str
            List of dates to process.
        **kwargs :
            Additional arguments passed to _run_recipe_loop.

        """
        recipe_sci = get_recipe_cls('muse_scibasic')
        recipe_std = get_recipe_cls(recipe_name)

        # get the list of dates to process
        dates = self.prepare_dates(dates, DPR_TYPE='STD')

        # run muse_scibasic with specific parameters (tag: STD)
        recipe = self._instantiate_recipe(recipe_std, recipe_name,
                                          verbose=False)
        recipe_kw = {'tag': 'STD', 'output_dir': recipe.output_dir}
        self._run_recipe_loop(recipe_sci, dates, recipe_kwargs=recipe_kw,
                              **kwargs)

        # run muse_standard
        self._run_recipe_loop(recipe_std, dates, use_reduced=True, **kwargs)

    def exp_align(self, dataset, recipe_name='muse_exp_align', filt='white',
                  params_name=None, name=None, exps=None, force=False,
                  **kwargs):
        """Compute offsets between exposures of a dataset.

        Parameters
        ----------
        dataset : str
            Dataset name.
        recipe_name : str
            Recipe to run: 'muse_exp_align' (DRS, default), or 'imphot'.
        filt : str
            Filter to use for the images, only for muse_exp_align.
        params_name : str
            Name of the parameter block, default to recipe_name.
        name : str
            Name of the output record, default to '{dataset}_{recipe_name}'.
        exps : list of str
            List of exposures to process. By default all exposures of the
            dataset are processed.
        force : bool
            Force processing if it was already done previously.

        """
        recipe_name = normalize_recipe_name(recipe_name)
        params_name = params_name or recipe_name
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
        recipe_cls = get_recipe_cls(recipe_name)

        processed = set()
        if recipe_name == 'imphot':
            if force:
                kwargs['force'] = force
            else:
                # Find already processed files
                kwargs['processed'] = processed = self.get_processed(
                    OBJECT=dataset, DPR_TYPE='IMPHOT', recipe_name=params_name)
                self.logger.info('Found %d processed exps', len(processed))

        DPR_TYPE = recipe_cls.DPR_TYPE
        name = (name or recipe_conf.get('name') or 'OFFSET_LIST_{}'.format(
            'drs' if recipe_name == 'muse_exp_align' else recipe_name))

        # get the list of dates to process
        from_recipe = recipe_conf.get('from_recipe', 'muse_scipost')
        if exps:
            query = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                           recipe_name=from_recipe, name=exps))
        else:
            query = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                           recipe_name=from_recipe))

        flist = [f for r in query
                 for f in iglob(f"{r['path']}/{DPR_TYPE}*.fits")]

        filt = recipe_conf.get('filt', filt)
        if recipe_name == 'muse_exp_align' and filt:
            flist = [f for f in flist
                     if fits.getval(f, 'ESO DRS MUSE FILTER NAME') == filt]

        self._run_recipe_simple(recipe_cls, name, dataset, flist,
                                params_name=params_name, **kwargs)

        if recipe_name == 'imphot':
            # Special case to insert IMPHOT result files in the table
            info = self.reduced.find_one(name=name)
            del info['id']
            rows = [{**info, 'name': item['name'], 'DPR_TYPE': 'IMPHOT',
                     'path': join(info['path'], item['name'])}
                    for item in query if item['name'] not in processed]
            upsert_many(self.db, self.reduced.name, rows,
                        keys=('name', 'recipe_name', 'DPR_TYPE'))

    def exp_combine(self, dataset, recipe_name='muse_exp_combine', name=None,
                    params_name=None, force=False, **kwargs):
        """Combine exposures for a dataset.

        Parameters
        ----------
        dataset : str
            Dataset name.
        recipe_name : str
            Recipe to run: 'muse_exp_combine' (DRS, default), or
            'mpdaf_combine' (cube combination with MPDAF).
        name : str
            Name of the output record, default to '{dataset}_{recipe_name}'.
        params_name : str
            Name of the parameter block, default to recipe_name.
        force : bool
            Force processing if it was already done previously.

        """
        recipe_name = normalize_recipe_name(recipe_name)
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
        from_recipe = recipe_conf.get('from_recipe', 'muse_scipost')
        recipe_cls = get_recipe_cls(recipe_name)
        DPR_TYPE = recipe_cls.DPR_TYPE
        name_dict = {'muse_exp_combine': 'drs', 'mpdaf_combine': 'mpdaf'}

        names_select = recipe_conf.get('names_with_selection')
        if not names_select:
            name = (name or recipe_conf.get('name') or '{}_{}'.format(
                dataset, name_dict.get(recipe_name, recipe_name)))
            names_select = {name: recipe_conf.get('select')}

        if name is not None:
            names_select = {name: names_select[name]}

        use_scale = recipe_conf.get('use_scale')
        params = params_name or recipe_name
        processed = self.get_processed(recipe_name=params)

        flags = recipe_conf.get('exclude_flags')
        for name, select in names_select.items():
            if not force and name in processed:
                self.logger.info('Skipping %s, already processed', name)
                continue
            # get the list of files to process
            self.logger.info('Processing %s', name)
            flist, explist = self.get_files(
                DPR_TYPE, first_only=True, OBJECT=dataset,
                recipe_name=from_recipe, select=select, remove_excludes=True,
                exclude_flags=flags, order_by='name', return_explist=True)

            if use_scale:
                scale_tbl = self._get_scales(explist, use_scale['from'],
                                             use_scale['bands'])
            else:
                scale_tbl = None

            self._run_recipe_simple(
                recipe_cls, name, dataset, flist, params_name=params_name,
                scale_table=scale_tbl, **kwargs)

    def std_combine(self, runs, recipe_name='muse_std_combine', name=None,
                    params_name=None, force=False, **kwargs):
        """Combine std stars for a list of runs.

        Parameters
        ----------
        runs : list of str
            List of run names.
        recipe_name : str
            Recipe to run: 'muse_exp_combine' (DRS, default), or
            'mpdaf_combine' (cube combination with MPDAF).
        name : str
            Name of the output record, default to '{dataset}_{recipe_name}'.
        params_name : str
            Name of the parameter block, default to recipe_name.
        force : bool
            Force processing if it was already done previously.

        """
        recipe_name = normalize_recipe_name(recipe_name)
        recipe_conf = self._get_recipe_conf(recipe_name, params_name)
        from_recipe = recipe_conf.get('from_recipe', 'muse_standard')
        recipe_cls = get_recipe_cls(recipe_name)
        DPR_TYPES = recipe_cls.DPR_TYPES

        params = params_name or recipe_name
        processed = self.get_processed(recipe_name=params)

        for run in runs:
            if not force and run in processed:
                self.logger.info('Skipping run %s, already processed', run)
                continue
            else:
                self.logger.info('Processing run %s', run)

            # get the list of files to process
            flist = {DPR_TYPE: self.get_files(DPR_TYPE, first_only=True,
                                              run=run, recipe_name=from_recipe,
                                              remove_excludes=True)
                     for DPR_TYPE in DPR_TYPES}

            if any(len(v) == 0 for v in flist.values()):
                self.logger.error('No files for run %s', run)
                continue

            # this is the name used for the output_dir
            rec_name = name or run
            self._run_recipe_simple(recipe_cls, rec_name, run, flist,
                                    params_name=params_name,
                                    save_kwargs={'run': run}, **kwargs)

    def _get_recipe_conf(self, recipe_name, params_name=None, item=None):
        """Get config dict for a recipe."""
        if params_name is not None:
            if params_name not in self.conf['recipes']:
                raise ValueError(f"could not find the '{params_name}' "
                                 "parameters in the settings file")
            recipe_name = params_name

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
                     **self._get_recipe_conf(recipe_name, item='init')}
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

    def _get_scales(self, explist, from_recipe, bands):
        """Get scale and offset factors from the imphot tables."""
        # read imphot tables, select useful columns, and stack them
        tables = []
        for o in self.reduced.find(name=explist, recipe_name=from_recipe,
                                   DPR_TYPE='IMPHOT', order_by='name'):
            data = fits.getdata(f"{o['path']}/IMPHOT.fits")
            t = Table([[o['name']] * len(data), data['filter'],
                       data['scale'], data['bg']],
                      names=('name', 'filter', 'scale', 'offset'))
            tables.append(t)

        tbl = vstack(tables)

        # select values for the bands of interest
        if isinstance(bands, str):
            scale_tbl = tbl[tbl['filter'] == bands]
        else:
            # compute the mean over the bands
            tbl = tbl[np.logical_or.reduce(
                [tbl['filter'] == f for f in bands], axis=0)]
            scale_tbl = tbl.group_by('name').groups.aggregate(np.mean)
        return scale_tbl
