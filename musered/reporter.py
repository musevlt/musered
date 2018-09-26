import json
import matplotlib.pyplot as plt
import numpy as np
import textwrap

from astropy.io import fits
from astropy.table import Table
from collections import defaultdict
from glob import iglob
from mpdaf.obj import Image
from sqlalchemy import sql

from .recipes import recipe_classes
from .utils import query_count_to_table

try:
    from IPython.display import display, HTML
except ImportError:
    IPYTHON = False
else:
    IPYTHON = True


class TextFormatter:
    show_title = print
    show_text = print

    def show_table(self, t, **kwargs):
        kwargs.setdefault('max_lines', -1)
        t.pprint(**kwargs)


class HTMLFormatter:
    def show_title(self, text):
        display(HTML(f'<h2>{text}</h2>'))

    def show_text(self, text):
        display(HTML(f'<p>{text}</p>'))

    def show_table(self, t, **kwargs):
        kwargs.setdefault('max_width', -1)
        display(HTML(t._base_repr_(html=True, **kwargs)))


class Reporter:

    def __init__(self, report_format='txt'):
        assert report_format in ('txt', 'html')
        self.format = report_format
        self.fmt = (HTMLFormatter if self.format == 'html' and IPYTHON
                    else TextFormatter)()

    def list_datasets(self):
        """Print the list of datasets."""
        self.fmt.show_title('Datasets:')
        for name in self.datasets:
            nexp = len(self.exposures[name])
            self.fmt.show_text(f'- {name} : {nexp} exposures')

    def list_nights(self):
        """Print the list of nights."""
        self.fmt.show_title('Nights:')
        for x in sorted(self.nights):
            self.fmt.show_text(f'- {x}')

    def list_runs(self):
        """Print the list of runs."""
        self.fmt.show_title('Runs:')
        for x in sorted(self.runs):
            run = self.conf['runs'][x]
            self.fmt.show_text(
                f"- {x} : {run['start_date']} - {run['end_date']}")

    def list_exposures(self):
        """Print the list of exposures."""
        self.fmt.show_title('Exposures:')
        for name, explist in sorted(self.exposures.items()):
            self.fmt.show_text(f'- {name}')
            self.fmt.show_text('  - ' + '\n  - '.join(explist))

    def info(self):
        """Print a summary of the raw and reduced data."""
        self.fmt.show_text(f'Reduction version {self.version}')
        self.fmt.show_text(f'{self.raw.count()} files\n')
        self.list_datasets()
        print()
        self.list_runs()

        # count files per night and per type, raw data, then reduced
        self.fmt.show_title(f'\nRaw data:\n')
        if len(self.raw) == 0:
            self.fmt.show_text('Nothing yet.')
        else:
            # uninteresting objects to exclude from the report
            excludes = ('Astrometric calibration (ASTROMETRY)', 'WAVE,LSF',
                        'WAVE,MASK')
            t = query_count_to_table(self.db, 'raw', exclude_obj=excludes)
            self.fmt.show_table(t)

        if len(self.reduced) == 0:
            self.fmt.show_title(f'\nProcessed data:\n')
            self.fmt.show_text('Nothing yet.')
        else:
            self.fmt.show_title(f'\nProcessed calib data:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'], where=sql.and_(
                    self.redc.DPR_CATG == 'CALIB',
                    self.redc.DPR_TYPE.notlike('%STD%')
                ))
            if t:
                self.fmt.show_table(t)

            self.fmt.show_title(f'\nProcessed standard:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'],
                where=self.redc.DPR_TYPE.like('%STD%'))
            if t:
                self.fmt.show_table(t)

            self.fmt.show_title(f'\nProcessed science data:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'],
                where=self.redc.DPR_CATG == 'SCIENCE')
            if t:
                self.fmt.show_table(t)

    def info_exp(self, expname):
        """Print information about a given exposure or night."""
        res = defaultdict(list)
        for r in self.reduced.find(name=expname):
            res[r['recipe_name']].append(r)

        res = list(res.values())
        res.sort(key=lambda x: x[0]['date_run'])

        print(textwrap.dedent(f"""
        =========================
         {expname}
        =========================
        """))

        for recipe in res:
            o = recipe[0]
            o.setdefault('recipe_file', None)
            frames = ', '.join(r['DPR_TYPE'] for r in recipe)
            print(textwrap.dedent(f"""\
            recipe: {o['recipe_name']}
            - date    : {o['date_run']}
            - log     : {o['log_file']}
            - json    : {o['recipe_file']}
            - frames  : {frames}
            - path    : {o['path']}
            - warning : {o['nbwarn']}
            - runtime : {o['user_time']:.1f} (user) {o['sys_time']:.1f} (sys)\
            """))

            if o['recipe_file'] is None:
                continue

            with open(o['recipe_file']) as f:
                info = json.load(f)

            for name in ('calib', 'raw'):
                print(f'- {name:7s} :')
                maxlen = max(len(k) for k, v in info[name].items() if v)
                for k, v in info[name].items():
                    if isinstance(v, str):
                        print(f'  - {k:{maxlen}s} : {v}')
                    elif v is not None:
                        for line in v:
                            print(f'  - {k:{maxlen}s} : {line}')
            print()

    def info_raw(self, night, **kwargs):
        """Print information about raw exposures for a given night."""
        rows = list(self.raw.find(night=night))
        if len(rows) == 0:
            rows = list(self.raw.find(run=night))
        if len(rows) == 0:
            self.logger.error('Could not find exposures for %s', night)
            return

        t = Table(rows=rows, names=rows[0].keys())
        t.keep_columns([
            'name', 'EXPTIME', 'OBJECT',
            # 'DPR_CATG', 'DPR_TYPE',
            'INS_DROT_POSANG', 'INS_MODE', 'INS_TEMP7_VAL',
            'OCS_SGS_AG_FWHMX_MED', 'OCS_SGS_AG_FWHMY_MED',
            'OCS_SGS_FWHM_MED', 'OCS_SGS_FWHM_RMS',
            'TEL_AIRM_END', 'TEL_AIRM_START',
        ])
        for col in t.columns.values():
            col.name = (col.name.replace('TEL_', '').replace('OCS_SGS_', '')
                        .replace('INS_', ''))
        t.sort('name')
        self.fmt.show_table(t, max_width=-1, **kwargs)

    def info_qc(self, dpr_type, date_list=None, **kwargs):
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
            self.fmt.show_table(t, **kwargs)

    def show_images(self, recipe_name, dataset=None, DPR_TYPE='IMAGE_FOV',
                    filt='white', ncols=4, figsize=4, limit=None,
                    catalog=None, zoom_center=None, zoom_size=None, **kwargs):
        """Show images on a grid.

        Parameters
        ----------
        recipe_name : str
            Recipe for which images are shown.
        dataset : str, optional
            Dataset for which images are shown.
        DPR_TYPE : str, optional
            Type of images to show.
        filt : str, optional
            Filter, default to white.
        ncols : 4
            Number of columns in the grid.
        figsize : float
            Size of each subimage.
        limit : int
            Maximum number of images to show.
        catalog : str
            Catalog to be plotted on images, needs 'ra' and 'dec' columns.
        zoom_center : (float, float)
            Position (in pixels) on which to zoom in.
        zoom_size : (float, float)
            Size (in pixels) of the zoom.
        **kwargs
            Additional parameters are passed to `mpdaf.obj.Image.plot`.

        """
        dataset = dataset or list(self.datasets.keys())[0]
        res = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                     recipe_name=recipe_name, _limit=limit))

        filters = [filt] if isinstance(filt, str) else filt
        filtkey = 'ESO DRS MUSE FILTER NAME'

        flist = []
        for r in res:
            for f in iglob(f"{r['path']}/{DPR_TYPE}*.fits"):
                try:
                    filtr = fits.getval(f, filtkey)
                except KeyError:
                    filtr = None
                if filtr and filters and filtr not in filters:
                    continue
                flist.append((r['name'], filtr, f))

        if catalog is not None:
            tbl = Table.read(catalog)
            skycoords = np.array([tbl['dec'], tbl['ra']])

        nrows = int(np.ceil(len(flist) / ncols))
        fig, axes = plt.subplots(nrows, ncols, sharex=True, sharey=True,
                                 figsize=(figsize*ncols, figsize*nrows),
                                 gridspec_kw={'wspace': 0, 'hspace': 0})

        for (name, filtr, fname), ax in zip(sorted(flist), axes.flat):
            im = Image(fname)
            if zoom_size is not None and zoom_center is not None:
                im = im.subimage(zoom_center, zoom_size, unit_center=None,
                                 unit_size=None)
            im.plot(ax=ax, **kwargs)
            title = f'{name} ({filtr})' if filtr else name
            ax.text(10, im.shape[1] - 25, title)

            if catalog is not None:
                x, y = im.wcs.sky2pix(skycoords.T).T
                sel = (x > 0) & (x < im.shape[0]) & (y > 0) & (y < im.shape[1])
                ax.scatter(x[sel], y[sel], c='r', marker='+')

        for ax in axes.flat[len(flist):]:
            ax.axis('off')
        for ax in axes.flat:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect('equal')

        return fig
