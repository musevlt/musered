import cpl
import datetime
import itertools
import logging
import numpy as np
import operator
import os
import textwrap
from astropy.table import Table
from astropy.utils.decorators import lazyproperty
from collections import defaultdict
from glob import glob, iglob
from mpdaf.log import setup_logging
from sqlalchemy import sql

from .recipes import recipe_classes
from .static_calib import StaticCalib
from .utils import (load_yaml_config, load_db, parse_date, parse_raw_keywords,
                    parse_qc_keywords, query_count_to_table, ProgressBar)


class MuseRed:
    """The main class handling all MuseRed's logic.

    This class manages the database, and use the settings file, to provide all
    the methods to operate on the datasets.

    """

    def __init__(self, settings_file='settings.yml'):
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
                sql.select([self.rawc.OBJECT, self.rawc.DATE_OBS])
                .where(self.rawc.DPR_TYPE == 'OBJECT')):
            out[obj].append(name)
        return out

    def list_datasets(self):
        """Print the list of datasets."""
        print('Datasets:')
        for name in self.datasets:
            print(f'- {name}')

    def list_nights(self):
        """Print the list of nights."""
        print('Nights:')
        for x in sorted(self.nights):
            print(f'- {x}')

    def list_exposures(self):
        """Print the list of exposures."""
        print('Exposures:')
        for name, explist in sorted(self.exposures.items()):
            print(f'- {name}')
            print('  - ' + '\n  - '.join(explist))

    def info(self):
        """Print a summary of the raw and reduced data."""
        print(f'{self.raw.count()} files\n')
        self.list_datasets()

        # count files per night and per type, raw data, then reduced
        print(f'\nRaw data:\n')
        if 'night' not in self.raw.columns:
            print('Nothing yet.')
        else:
            # uninteresting objects to exclude from the report
            excludes = ('Astrometric calibration (ASTROMETRY)', )
            t = query_count_to_table(self.db, 'raw', exclude_obj=excludes)
            t.pprint(max_lines=-1)

        if 'DATE_OBS' not in self.reduced.columns:
            print(f'\nProcessed data:\n')
            print('Nothing yet.')
        else:
            print(f'\nProcessed calib data:\n')
            t = query_count_to_table(self.db, 'reduced',
                                     where=self.redc.DPR_CATG == 'CALIB')
            if t:
                t.pprint(max_lines=-1)

            print(f'\nProcessed science data:\n')
            t = query_count_to_table(self.db, 'reduced',
                                     where=self.redc.DPR_CATG == 'SCIENCE')
            if t:
                t.pprint(max_lines=-1)

    def info_exp(self, date_obs):
        """Print information about a given exposure or night."""
        res = defaultdict(list)
        for r in self.reduced.find(DATE_OBS=date_obs):
            res[r['recipe_name']].append(r)

        res = list(res.values())
        res.sort(key=lambda x: x[0]['date_run'])

        print(textwrap.dedent(f"""
        ==================
         {date_obs}
        ==================
        """))

        for recipe in res:
            o = recipe[0]
            frames = ', '.join(r['OBJECT'] for r in recipe)
            print(textwrap.dedent(f"""\
            recipe: {o['recipe_name']}
            - date    : {o['date_run']}
            - log     : {o['log_file']}
            - frames  : {frames}
            - path    : {o['path']}
            - warning : {o['nbwarn']}
            - runtime : {o['user_time']:.1f} (user) {o['sys_time']:.1f} (sys)
            """))

    def info_raw(self, date_obs):
        """Print information about raw exposures."""
        rows = list(self.raw.find(night=date_obs))
        t = Table(rows=rows, names=rows[0].keys())
        t.keep_columns([
            'ARCFILE', 'DATE_OBS', 'EXPTIME', 'OBJECT',
            # 'DPR_CATG', 'DPR_TYPE',
            'INS_DROT_POSANG', 'INS_MODE', 'INS_TEMP7_VAL',
            'OCS_SGS_AG_FWHMX_MED', 'OCS_SGS_AG_FWHMY_MED',
            'OCS_SGS_FWHM_MED', 'OCS_SGS_FWHM_RMS',
            'TEL_AIRM_END', 'TEL_AIRM_START',
        ])
        for col in t.columns.values():
            col.name = (col.name.replace('TEL_', '').replace('OCS_SGS_', '')
                        .replace('INS_', ''))
        t.sort('ARCFILE')
        t.pprint(max_lines=-1, max_width=-1)

    def info_qc(self, dpr_type, date_list=None):
        if dpr_type not in self.db:
            self.update_qc(dpr_types=[dpr_type])

        if not date_list:
            date_list = self.select_dates(dpr_type, table=dpr_type,
                                          distinct=True)

        table = self.db[dpr_type]
        recipe_cls = recipe_classes[table.find_one()['recipe_name']]
        cols = ['filename', 'DATE_OBS', 'INS_MODE']
        cols.extend(recipe_cls.QC_keywords.get(dpr_type, []))

        for date_obs in date_list:
            t = Table(rows=[[row[k] for k in cols] for row in
                            table.find(DATE_OBS=date_obs)], names=cols)
            t.pprint(max_lines=-1)

    def set_loglevel(self, level):
        logger = logging.getLogger('musered')
        level = level.upper()
        logger.setLevel(level)
        logger.handlers[0].setLevel(level)

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

    def select_dates(self, dpr_type, table='raw', column='DATE_OBS', **kwargs):
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
            for f in files:
                if f.endswith(('.fits', '.fits.fz')):
                    flist.append(os.path.join(root, f))
        self.logger.info('found %d FITS files', len(flist))

        # get the list of files already in the database
        try:
            arcf = self.select_column('ARCFILE')
        except Exception:
            arcf = []

        rows, nskip = parse_raw_keywords(flist, force=force, processed=arcf)
        self.raw.insert_many(rows)
        self.logger.info('inserted %d rows, skipped %d', len(rows), nskip)

        # cleanup cached attributes
        del self.nights

        for name in ('night', 'DATE_OBS', 'DPR_TYPE'):
            if not self.raw.has_index([name]):
                self.raw.create_index([name])

        if 'DATE_OBS' in self.reduced.columns:
            for name in ('DATE_OBS', 'DPR_TYPE'):
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
                keys = {k: item[k] for k in ('DATE_OBS', 'INS_MODE')}
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

        conf.setdefault('log_dir', os.path.join(self.reduced_path, 'logs'))
        os.makedirs(conf['log_dir'], exist_ok=True)

        # terminal logging: disable cpl's logger as it uses the root logger.
        cpl.esorex.msg.level = 'off'
        default_fmt = '%(levelname)s - %(name)s: %(message)s'
        setup_logging(name='cpl', level=conf.get('msg', 'info').upper(),
                      color=True, fmt=conf.get('msg_format', default_fmt))

        # default params for recipes
        params = self.conf['recipes'].setdefault('common', {})
        params.setdefault('log_dir', conf['log_dir'])
        params.setdefault('temp_dir', os.path.join(self.reduced_path, 'tmp'))

    def find_calib(self, night, dpr_type, ins_mode, nrequired=24, day_off=0):
        """Return calibration files for a given night, type, and mode."""
        res = self.reduced.find_one(DATE_OBS=night, INS_MODE=ins_mode,
                                    DPR_TYPE=dpr_type)
        if res is None and day_off != 0:
            if isinstance(night, str):
                night = parse_date(night)
            for off, direction in itertools.product(range(1, day_off + 1),
                                                    (1, -1)):
                off = datetime.timedelta(days=off * direction)
                res = self.reduced.find_one(DATE_OBS=(night + off).isoformat(),
                                            INS_MODE=ins_mode,
                                            DPR_TYPE=dpr_type)
                if res is not None:
                    self.logger.warning('Using %s from night %s',
                                        dpr_type, night + off)
                    break

        if res is None:
            raise ValueError(f'could not find {dpr_type} for night {night}')

        flist = sorted(glob(f"{res['path']}/{dpr_type}*.fits"))
        if len(flist) != nrequired:
            raise ValueError(f'found {len(flist)} {dpr_type} files '
                             f'instead of {nrequired}')
        return flist

    def get_calib_frames(self, recipe, night, ins_mode, day_off=0,
                         exclude_frames=None):
        """Return a dict with all calibration frames for a recipe."""
        frames = {}
        exclude_frames = set(exclude_frames or recipe.exclude_frames)
        nrequired = {'TWILIGHT_CUBE': 1}

        for frame in set(recipe.calib_frames) - exclude_frames:
            if frame in self.static_calib.STATIC_FRAMES:
                frames[frame] = self.static_calib.get(frame, date=night)
            else:
                frames[frame] = self.find_calib(
                    night, frame, ins_mode, day_off=day_off,
                    nrequired=nrequired.get(frame, 24))

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

    def run_recipe(self, recipe_cls, date_list, skip=False, calib=False,
                   recipe_kwargs=None, use_reduced=False, **kwargs):
        """Main method used to run a recipe.

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
        recipe_kwargs : dict
            Additional arguments passed to the `musered.Recipe` instantiation.
        use_reduced : bool
            If True, find data in the reduced table, otherwise on raw.
        **kwargs
            Additional arguments passed to `musered.Recipe.run`.

        """
        recipe_name = recipe_cls.recipe_name
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
                'DATE_OBS', table='reduced', distinct=True,
                whereclause=(self.redc.recipe_name == recipe_name))
            log.debug('processed: ' + ', '.join(map(str, sorted(processed))))
            if len(processed) == len(date_list):
                log.info('Already processed, nothing to do')
                return
            elif len(processed) > 0:
                log.info('%d %ss already processed', len(processed), label)

        # Instantiate the recipe object.
        # Use parameters from the settings, common first, and then from
        # recipe_name.init, and from recipe_kwargs
        recipe_conf = self.conf['recipes'].get(recipe_name, {})
        recipe_kw = {**self.conf['recipes']['common'],
                     **recipe_conf.get('init', {})}
        if recipe_kwargs is not None:
            recipe_kw.update(recipe_kwargs)
        recipe = recipe_cls(**recipe_kw)

        table = self.reduced if use_reduced else self.raw
        for date_obs in date_list:
            if skip and date_obs in processed:
                log.debug('%s already processed', date_obs)
                continue

            DPR_TYPE = recipe.DPR_TYPE
            res = list(table.find(**{datecol: date_obs, 'DPR_TYPE': DPR_TYPE}))
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
                     label, date_obs, len(flist), DPR_TYPE, ins_mode)

            if recipe.use_drs_output:
                outn = f'{date_obs}.{ins_mode}' if calib else date_obs
                output_dir = os.path.join(self.reduced_path,
                                          recipe.output_dir, outn)
                kwargs['output_dir'] = output_dir
            else:
                output_dir = recipe.output_dir

            calib_frames = self.get_calib_frames(
                recipe, night, ins_mode, day_off=3,
                exclude_frames=recipe_conf.get('exclude_frames'))

            if recipe.use_illum:
                ref_temp = np.mean([o['INS_TEMP7_VAL'] for o in res])
                ref_date = np.mean([o['MJD_OBS'] for o in res])
                kwargs['illum'] = self.find_illum(night, ref_temp, ref_date)

            params = recipe_conf.get('params')
            recipe.run(flist, name=res[0][namecol], params=params,
                       **calib_frames, **kwargs)

            date_run = datetime.datetime.now().isoformat()
            out_frames = []
            for out_frame in recipe.output_frames:
                # save in database for each output frame, but check before that
                # files were created for each frame (some are optional)
                if any(iglob(f"{output_dir}/{out_frame}*.fits")):
                    out_frames.append(out_frame)
                    self.reduced.upsert({
                        'date_run': date_run,
                        'night': night,
                        'recipe_name': recipe_name,
                        'name': res[0][namecol],
                        'DATE_OBS': date_obs,
                        'path': output_dir,
                        'DPR_TYPE': out_frame,
                        'DPR_CATG': res[0]['DPR_CATG'],
                        'OBJECT': res[0]['OBJECT'],
                        'INS_MODE': ins_mode,
                        **recipe.dump()
                    }, ['DATE_OBS', 'recipe_name', 'DPR_TYPE'])

            if len(out_frames) == 0:
                raise RuntimeError('could not find output files')
            log.info('Processed data (%s) available in %s',
                     ', '.join(out_frames), output_dir)

    def process_calib(self, recipe_name, night_list=None, skip=False,
                      **kwargs):
        """Run a calibration recipe."""

        recipe_cls = recipe_classes['muse_' + recipe_name]

        # get the list of nights to process
        if night_list is None:
            night_list = self.select_dates(recipe_cls.DPR_TYPE, column='night',
                                           distinct=True)

        self.run_recipe(recipe_cls, night_list, calib=True, skip=skip,
                        **kwargs)

    def process_exp(self, recipe_name, explist=None, skip=False, **kwargs):
        """Run a science recipe."""

        recipe_cls = recipe_classes['muse_' + recipe_name]

        # get the list of dates to process
        if explist is None:
            if recipe_name in ('scibasic', ):
                table = 'raw'
                dpr_type = 'OBJECT'
            else:
                table = 'reduced'
                dpr_type = recipe_cls.DPR_TYPE
            explist = self.select_dates(dpr_type, table=table)

        self.run_recipe(recipe_cls, explist, skip=skip, **kwargs)

    def process_standard(self, explist=None, skip=False, **kwargs):
        """Reduce a standard exposure, running both muse_scibasic and
        muse_standard.
        """
        recipe_sci = recipe_classes['muse_scibasic']
        recipe_std = recipe_classes['muse_standard']

        # get the list of dates to process
        if explist is None:
            explist = self.select_dates('STD')

        # run muse_scibasic with specific parameters (tag: STD)
        recipe_kw = {'tag': 'STD', 'output_dir': recipe_std.output_dir}
        self.run_recipe(recipe_sci, explist, skip=skip,
                        recipe_kwargs=recipe_kw, **kwargs)

        # run muse_standard
        self.run_recipe(recipe_std, explist, skip=skip, use_reduced=True,
                        **kwargs)
