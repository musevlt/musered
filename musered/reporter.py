import textwrap
from astropy.table import Table
from collections import defaultdict

from .recipes import recipe_classes
from .utils import query_count_to_table


class TextReporter:

    def __init__(self, report_format='txt'):
        assert report_format in ('txt', 'html')
        self.report_format = report_format

    def show_table(self, t, max_lines=-1, **kwargs):
        if self.report_format == 'txt':
            t.pprint(max_lines=max_lines, **kwargs)
        elif self.report_format == 'html':
            from IPython.display import display
            display(t)

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
            self.show_table(t)

        if 'DATE_OBS' not in self.reduced.columns:
            print(f'\nProcessed data:\n')
            print('Nothing yet.')
        else:
            print(f'\nProcessed calib data:\n')
            t = query_count_to_table(self.db, 'reduced',
                                     where=self.redc.DPR_CATG == 'CALIB')
            if t:
                self.show_table(t)

            print(f'\nProcessed science data:\n')
            t = query_count_to_table(self.db, 'reduced',
                                     where=self.redc.DPR_CATG == 'SCIENCE')
            if t:
                self.show_table(t)

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
        self.show_table(t, max_lines=-1)

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
            self.show_table(t)
