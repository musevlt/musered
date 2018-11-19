import click
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import textwrap

from astropy.io import fits
from astropy.table import Table
from collections import defaultdict
from glob import iglob
from mpdaf.obj import Image, Cube
from sqlalchemy import sql

from .recipes import recipe_classes, normalize_recipe_name
from .utils import query_count_to_table, get_exp_name

try:
    from IPython.display import display, HTML
except ImportError:
    IPYTHON = False
else:
    IPYTHON = True

FILTER_KEY = 'ESO DRS MUSE FILTER NAME'


class TextFormatter:
    show_title = print
    show_text = print

    def show_table(self, t, **kwargs):
        if t is not None:
            kwargs.setdefault('max_lines', -1)
            t.pprint(**kwargs)


class HTMLFormatter:
    def show_title(self, text):
        display(HTML(f'<h2>{text}</h2>'))

    def show_text(self, text):
        display(HTML(f'<p>{text}</p>'))

    def show_table(self, t, **kwargs):
        if t is not None:
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
        for name in sorted(self.runs):
            run = self.conf['runs'][name]
            nexp = self.raw.count(run=name, DPR_TYPE='OBJECT')
            self.fmt.show_text(f"- {name} : {run['start_date']} - "
                               f"{run['end_date']}, {nexp} exposures")

    def list_calibs(self):
        """Print the list of calibration sequences."""
        self.fmt.show_title('Calibrations:')
        for dpr_type, explist in sorted(self.calib_exposures.items()):
            self.fmt.show_text(f'- {dpr_type}')
            self.fmt.show_text('  - ' + '\n  - '.join(explist))

    def list_exposures(self):
        """Print the list of exposures."""
        self.fmt.show_title('Exposures:')
        for name, explist in sorted(self.exposures.items()):
            self.fmt.show_text(f'- {name}')
            self.fmt.show_text('  - ' + '\n  - '.join(explist))

    def info(self, date_list=None, run=None):
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
            t = query_count_to_table(self.db, 'raw', exclude_obj=excludes,
                                     date_list=date_list, run=run)
            self.fmt.show_table(t)

        if len(self.reduced) == 0:
            self.fmt.show_title(f'\nProcessed data:\n')
            self.fmt.show_text('Nothing yet.')
        else:
            redc = self.reduced.table.c
            self.fmt.show_title(f'\nProcessed calib data:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'], where=sql.and_(
                    redc.DPR_CATG == 'CALIB',
                    redc.DPR_TYPE.notlike('%STD%')
                ), date_list=date_list, run=run, calib=True)
            if t:
                self.fmt.show_table(t)

            self.fmt.show_title(f'\nProcessed standard:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'],
                where=redc.DPR_TYPE.like('%STD%'),
                date_list=date_list, run=run)
            if t:
                self.fmt.show_table(t)

            self.fmt.show_title(f'\nProcessed science data:\n')
            t = query_count_to_table(
                self.db, self.tables['reduced'],
                where=redc.DPR_CATG == 'SCIENCE',
                date_list=date_list, run=run)
            if t:
                self.fmt.show_table(t)

    def info_exp(self, expname, full=True, recipes=None, show_weather=True):
        """Print information about a given exposure or night."""
        if recipes:
            recipes = [normalize_recipe_name(name) for name in recipes]

        res = defaultdict(list)
        for r in self.reduced.find(name=expname):
            if recipes and r['recipe_name'] not in recipes:
                continue
            res[r['recipe_name']].append(r)

        res = list(res.values())
        res.sort(key=lambda x: x[0]['date_run'])

        if len(res) == 0:
            self.logger.debug('%s not found', expname)
            return

        click.secho(f'\n {expname} \n', fg='green', bold=True, reverse=True)

        if not recipes and 'gto_logs' in self.db:
            logs = list(self.db['gto_logs'].find(name=expname))
            if logs:
                click.secho(f"★ GTO logs:", fg='green', bold=True)
                colors = dict(A='green', B='yellow', C='orange')
                for log in logs:
                    if log['flag']:
                        rk = log['flag']
                        log['rk'] = click.style(f'Rank {rk}', reverse=True,
                                                fg=colors.get(rk, 'red'))
                        print("- {date}\t{author}\t{rk}\t{comment}"
                              .format(**log))
                    if log['fdate']:
                        print("- {fdate}\t{fauthor}\t\t{fcomment}"
                              .format(**log))
                print()

        if show_weather and not recipes and 'weather_conditions' in self.db:
            click.secho(f"★ Weather Conditions:", fg='green', bold=True)
            table = self.db['weather_conditions']
            for log in table.find(night=res[0][0]['night'], order_by='Time'):
                print("- {Time}\t{Conditions:12s}\t{Comment}".format(**log))
            print()

        for recipe in res:
            o = recipe[0]
            o.setdefault('recipe_file', None)
            frames = ', '.join(click.style(r['DPR_TYPE'], bold=True)
                               for r in recipe)
            usert = o.get('user_time') or 0
            syst = o.get('sys_time') or 0
            click.secho(f"★ Recipe: {o['recipe_name']}", fg='green', bold=True)
            print(textwrap.dedent(f"""\
            - date    : {o['date_run']}
            - log     : {o['log_file']}
            - json    : {o['recipe_file']}
            - frames  : {frames}
            - path    : {o['path']}
            - runtime : {usert:.1f} (user) {syst:.1f} (sys)\
            """))
            if o['nbwarn'] > 0:
                click.secho(f"- warning : {o['nbwarn']}", fg='red', bold=True)
            # else:
            #     click.secho(f"- warning : {o['nbwarn']}")

            if o['recipe_file'] is None:
                continue

            if full and os.path.isfile(o['recipe_file']):
                with open(o['recipe_file']) as f:
                    info = json.load(f)

                for name in ('calib', 'raw'):
                    if name not in info:
                        continue
                    print(f'- {name:7s} :')
                    maxlen = max(len(k) for k, v in info[name].items() if v)
                    for k, v in info[name].items():
                        if isinstance(v, str):
                            print(f'  - {k:{maxlen}s} : {v}')
                        elif v is not None:
                            for line in v:
                                print(f'  - {k:{maxlen}s} : {line}')
            print()

    def info_raw(self, **kwargs):
        """Print information about raw exposures for a given night or type."""

        rows = list(self.raw.find(**kwargs))
        if len(rows) == 0:
            self.logger.error('Could not find exposures')
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
        self.fmt.show_table(t, max_width=-1)

    def info_qc(self, dpr_type, date_list=None, **kwargs):
        if dpr_type not in self.db:
            self.update_qc(dpr_types=[dpr_type])

        table = self.db[dpr_type]
        if not date_list:
            date_list = [o['DATE_OBS'] for o in table.distinct('DATE_OBS')]
        elif isinstance(date_list, str):
            date_list = [date_list]
        else:
            date_list = self.prepare_dates(date_list, datecol='name',
                                           DPR_TYPE=dpr_type, table='reduced')

        recipe_cls = recipe_classes[table.find_one()['recipe_name']]
        cols = ['filename', 'hdu', 'DATE_OBS', 'INS_MODE']
        cols.extend(recipe_cls.QC_keywords.get(dpr_type, []))

        for date_obs in date_list:
            self.fmt.show_title(f'\n{date_obs}\n')
            rows = list(table.find(DATE_OBS=date_obs))
            if len(rows) == 0:
                self.fmt.show_text('no QC.')
                continue
            t = Table(rows=[[row[k] for k in cols] for row in rows],
                      names=cols)
            self.fmt.show_table(t, **kwargs)

    def show_images(self, recipe_name, dataset=None, DPR_TYPE='IMAGE_FOV',
                    filt='white', ncols=4, figsize=4, limit=None, date=None,
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
        hdulist = self.export_images(recipe_name, dataset=dataset, date=date,
                                     DPR_TYPE=DPR_TYPE, filt=filt, limit=limit)

        if catalog is not None:
            tbl = Table.read(catalog)
            skycoords = np.array([tbl['dec'], tbl['ra']])

        nrows = int(np.ceil(len(hdulist[1:]) / ncols))
        fig, axes = plt.subplots(nrows, ncols, sharex=True, sharey=True,
                                 figsize=(figsize*ncols, figsize*nrows),
                                 gridspec_kw={'wspace': 0, 'hspace': 0})

        for hdu, ax in zip(hdulist[1:], axes.flat):
            im = Image(data=hdu.data)
            if zoom_size is not None and zoom_center is not None:
                im = im.subimage(zoom_center, zoom_size, unit_center=None,
                                 unit_size=None)
            im.plot(ax=ax, **kwargs)
            filtr = hdu.header[FILTER_KEY]
            title = f'{hdu.name} ({filtr})' if filtr else hdu.name
            ax.text(10, im.shape[1] - 25, title)

            if catalog is not None:
                x, y = im.wcs.sky2pix(skycoords.T).T
                sel = (x > 0) & (x < im.shape[0]) & (y > 0) & (y < im.shape[1])
                ax.scatter(x[sel], y[sel], c='r', marker='+')

        for ax in axes.flat[len(hdulist[1:]):]:
            ax.axis('off')
        for ax in axes.flat:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect('equal')

        return fig

    def export_images(self, recipe_name, dataset=None, DPR_TYPE='IMAGE_FOV',
                      filt='white', limit=None, outname=None, cube=False,
                      date=None):
        """Export images as HDUs or cube.

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
        limit : int
            Maximum number of images to show.

        """
        dataset = dataset or list(self.datasets.keys())[0]
        recipe_name = normalize_recipe_name(recipe_name)
        kwargs = {}
        if date:
            kwargs['name'] = self.prepare_dates(date, DPR_TYPE='OBJECT')
        res = list(self.reduced.find(OBJECT=dataset, DPR_TYPE=DPR_TYPE,
                                     recipe_name=recipe_name, _limit=limit,
                                     order_by='name', **kwargs))

        filters = [filt] if isinstance(filt, str) else filt

        imgs = []
        for r in res:
            for f in iglob(f"{r['path']}/{DPR_TYPE}*.fits"):
                try:
                    filtr = fits.getval(f, FILTER_KEY)
                except KeyError:
                    filtr = None
                if filtr and filters and filtr not in filters:
                    continue
                im = Image(f, convert_float64=False)
                imgs.append(im)

        self.logger.info('Found %d images', len(imgs))
        if cube:
            cube = Cube(data=np.ma.array([im.data for im in imgs]),
                        var=np.ma.array([im.data for im in imgs]),
                        wcs=imgs[0].wcs)
            if outname:
                cube.write(outname, savemask='nan')
            return cube
        else:
            hdul = fits.HDUList([fits.PrimaryHDU()])
            for im in imgs:
                hdr = im.primary_header.copy()
                hdr.update(im.wcs.to_header())
                hdu = fits.ImageHDU(data=im.data.filled(np.nan), header=hdr)
                hdu.name = get_exp_name(im.filename)
                hdul.append(hdu)
            if outname:
                hdul.writeto(outname, savemask='nan')
            return hdul
