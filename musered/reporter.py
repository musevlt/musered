import click
import json
import matplotlib.pyplot as plt
import numpy as np
import os
import re
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

FILTER_KEY = "ESO DRS MUSE FILTER NAME"


class TextFormatter:
    show_title = print
    show_text = print

    def show_table(self, t, **kwargs):
        if t is not None:
            kwargs.setdefault("max_lines", -1)
            t.pprint(**kwargs)


class HTMLFormatter:
    def show_title(self, text):
        display(HTML(f"<h2>{text}</h2>"))

    def show_text(self, text):
        display(HTML(f"<p>{text}</p>"))

    def show_table(self, t, **kwargs):
        if t is not None:
            kwargs.setdefault("max_width", -1)
            display(HTML(t._base_repr_(html=True, **kwargs)))


class Reporter:
    def __init__(self, report_format="txt"):
        assert report_format in ("txt", "html")
        self.format = report_format
        self.fmt = (
            HTMLFormatter if self.format == "html" and IPYTHON else TextFormatter
        )()

    def list_datasets(self):
        """Print the list of datasets."""
        self.fmt.show_title("Datasets:")
        for name in self.datasets:
            nexp = len(self.exposures[name])
            self.fmt.show_text(f"- {name} : {nexp} exposures")

    def list_nights(self):
        """Print the list of nights."""
        self.fmt.show_title("Nights:")
        for x in sorted(self.nights):
            self.fmt.show_text(f"- {x}")

    def list_runs(self):
        """Print the list of runs."""
        if not self.runs:
            return

        exc = self.flags.find(*list(self.flags.flags))
        self.fmt.show_title("Runs:")
        for name in sorted(self.runs):
            run = self.conf["runs"][name]
            nexp = self.raw.count(run=name, DPR_TYPE="OBJECT")
            nexc = self.raw.count(run=name, DPR_TYPE="OBJECT", name=exc)
            text = (
                f"- {name} : {run['start_date']} - {run['end_date']}, "
                f"{nexp} exposures"
            )
            if nexc > 0:
                text += f" ({nexc} flagged)"
            self.fmt.show_text(text)

    def list_calibs(self):
        """Print the list of calibration sequences."""
        self.fmt.show_title("Calibrations:")
        for dpr_type, explist in sorted(self.calib_exposures.items()):
            self.fmt.show_text(f"- {dpr_type}")
            self.fmt.show_text("  - " + "\n  - ".join(explist))

    def list_exposures(self):
        """Print the list of exposures."""
        self.fmt.show_title("Exposures:")
        for name, explist in sorted(self.exposures.items()):
            self.fmt.show_text(f"- {name}")
            self.fmt.show_text("  - " + "\n  - ".join(explist))

    def info(
        self,
        date_list=None,
        run=None,
        filter_excludes=True,
        header=True,
        show_tables=("raw", "calib", "science"),
    ):
        """Print a summary of the raw and reduced data."""

        if header:
            self.fmt.show_text(f"Reduction version {self.version}")
            self.fmt.show_text(f"{self.raw.count()} files\n")
            self.list_datasets()
            print()
            self.list_runs()

        if len(self.raw) == 0:
            self.fmt.show_text("Nothing yet.")
            return

        redc = self.reduced.table.c
        exclude_names = self.frames.get_excludes() if filter_excludes else None

        # count files per night and per type, raw data, then reduced
        if "raw" in show_tables:
            self.fmt.show_title(f"\nRaw data:\n")
            if len(self.raw) == 0:
                self.fmt.show_text("Nothing yet.")
            else:
                # uninteresting objects to exclude from the report
                excludes = (
                    "Astrometric calibration (ASTROMETRY)",
                    "WAVE,LSF",
                    "WAVE,MASK",
                )
                t = query_count_to_table(
                    self.raw,
                    exclude_obj=excludes,
                    date_list=date_list,
                    run=run,
                    exclude_names=exclude_names,
                    datecol="night",
                    countcol="OBJECT",
                )
                self.fmt.show_table(t)

        if len(self.reduced) == 0:
            if "calib" in show_tables or "science" in show_tables:
                self.fmt.show_title(f"\nProcessed data:\n")
                self.fmt.show_text("Nothing yet.")
            return

        if "calib" in show_tables:
            self.fmt.show_title(f"\nProcessed calib data:\n")
            t = query_count_to_table(
                self.reduced,
                date_list=date_list,
                run=run,
                exclude_names=exclude_names,
                datecol="night",
                countcol="recipe_name",
                where=redc.DPR_CATG == "CALIB",
            )
            if t:
                self.fmt.show_table(t)

        if "science" in show_tables:
            self.fmt.show_title(f"\nProcessed science data:\n")
            t = query_count_to_table(
                self.reduced,
                where=redc.DPR_CATG == "SCIENCE",
                date_list=date_list,
                run=run,
                exclude_names=exclude_names,
                datecol="name",
                countcol="recipe_name",
            )
            if t:
                self.fmt.show_table(t)

    def info_exp(self, expname, full=True, recipes=None, show_weather=True):
        """Print information about a given exposure or night."""
        if recipes:
            recipes = [normalize_recipe_name(name) for name in recipes]

        res = defaultdict(list)
        for r in self.reduced.find(name=expname):
            if recipes and r["recipe_name"] not in recipes:
                continue
            res[r["recipe_name"]].append(r)

        res = list(res.values())
        res.sort(key=lambda x: x[0]["date_run"])

        if len(res) == 0:
            self.logger.debug("%s not found", expname)
            return

        click.secho(f"\n {expname} \n", fg="green", bold=True, reverse=True)

        if not recipes and "gto_logs" in self.db:
            logs = list(self.db["gto_logs"].find(name=expname))
            if logs:
                click.secho(f"★ GTO logs:", fg="green", bold=True)
                colors = dict(A="green", B="yellow", C="red")
                for log in logs:
                    if log["flag"]:
                        rk = log["flag"]
                        log["rk"] = click.style(
                            f"Rank {rk}", reverse=True, fg=colors.get(rk, "red")
                        )
                        print("- {date}\t{author}\t{rk}\t{comment}".format(**log))
                    if log["fdate"]:
                        print("- {fdate}\t{fauthor}\t\t{fcomment}".format(**log))
                print()

        if show_weather and not recipes and "weather_conditions" in self.db:
            click.secho(f"★ Weather Conditions:", fg="green", bold=True)
            table = self.db["weather_conditions"]
            for log in table.find(night=res[0][0]["night"], order_by="Time"):
                print("- {Time}\t{Conditions:12s}\t{Comment}".format(**log))
            print()

        for recipe in res:
            o = recipe[0]
            o.setdefault("recipe_file", None)
            frames = ", ".join(click.style(r["DPR_TYPE"], bold=True) for r in recipe)
            usert = o.get("user_time") or 0
            syst = o.get("sys_time") or 0
            click.secho(f"★ Recipe: {o['recipe_name']}", fg="green", bold=True)
            print(
                textwrap.dedent(
                    f"""\
            - date    : {o['date_run']}
            - log     : {o['log_file']}
            - json    : {o['recipe_file']}
            - frames  : {frames}
            - path    : {o['path']}
            - runtime : {usert:.1f} (user) {syst:.1f} (sys)\
            """
                )
            )
            if o["nbwarn"] > 0:
                click.secho(f"- warning : {o['nbwarn']}", fg="red", bold=True)
            # else:
            #     click.secho(f"- warning : {o['nbwarn']}")

            if o["recipe_file"] is None:
                continue

            if full and os.path.isfile(o["recipe_file"]):
                with open(o["recipe_file"]) as f:
                    info = json.load(f)

                for name in ("calib", "raw"):
                    if name not in info or not info[name]:
                        continue
                    print(f"- {name:7s} :")
                    maxlen = max(len(k) for k, v in info[name].items() if v)
                    for k, v in info[name].items():
                        if isinstance(v, str):
                            print(f"  - {k:{maxlen}s} : {v}")
                        elif v is not None:
                            for line in v:
                                print(f"  - {k:{maxlen}s} : {line}")
            print()

    def info_raw(self, **kwargs):
        """Print information about raw exposures for a given night or type."""

        rows = list(self.raw.find(**kwargs))
        if len(rows) == 0:
            self.logger.error("Could not find exposures")
            return

        t = Table(rows=rows, names=rows[0].keys())
        t.keep_columns(
            [
                "name",
                "EXPTIME",
                "OBJECT",
                "TPL_START",
                # 'DPR_CATG', 'DPR_TYPE',
                "INS_DROT_POSANG",
                "INS_MODE",
                "INS_TEMP7_VAL",
                "OCS_SGS_AG_FWHMX_MED",  # 'OCS_SGS_AG_FWHMY_MED',
                "OCS_SGS_FWHM_MED",  # 'OCS_SGS_FWHM_RMS',
                "TEL_AIRM_END",
                "TEL_AIRM_START",
                "OBS_NAME",
            ]
        )
        for col in t.columns.values():
            col.name = (
                col.name.replace("TEL_", "").replace("OCS_SGS_", "").replace("INS_", "")
            )
        t.sort("name")
        self.fmt.show_table(t, max_width=-1)

    def info_qc(self, dpr_type, date_list=None, **kwargs):
        tablename = f"qc_{dpr_type}"
        if tablename not in self.db:
            self.update_qc(dpr_types=[dpr_type])

        table = self.db[tablename]
        if not date_list:
            date_list = [o["DATE_OBS"] for o in table.distinct("DATE_OBS")]
        elif isinstance(date_list, str):
            date_list = [date_list]
        else:
            date_list = self.prepare_dates(
                date_list, datecol="name", DPR_TYPE=dpr_type, table="reduced"
            )

        recipe_cls = recipe_classes[table.find_one()["recipe_name"]]
        cols = ["filename", "hdu", "DATE_OBS", "INS_MODE"]
        cols.extend(recipe_cls.QC_keywords.get(dpr_type, []))

        for date_obs in date_list:
            self.fmt.show_title(f"\n{date_obs}\n")
            rows = list(table.find(DATE_OBS=date_obs))
            if len(rows) == 0:
                self.fmt.show_text("no QC.")
                continue
            t = Table(rows=[[row[k] for k in cols] for row in rows], names=cols)
            self.fmt.show_table(t, **kwargs)

    def info_warnings(self, date_list=None, recipes=None, mode="list"):
        assert mode in ("list", "summary", "detail")

        redc = self.reduced.table.c
        wc = redc.nbwarn > 0
        if date_list:
            dates = self.prepare_dates(date_list, datecol="name", table="reduced")
            wc &= redc.name.in_(dates)
        if recipes:
            wc &= redc.recipe_name.in_(recipes)

        rows = []
        cols = ("recipe_name", "name", "nbwarn", "log_file")
        query = sql.select([redc[c] for c in cols], whereclause=wc).distinct(
            redc.recipe_name, redc.name
        )

        for o in self.execute(query, order_by="name"):
            if o["nbwarn"] > 0:
                rows.append([o[col] for col in cols])

        if len(rows) == 0:
            self.fmt.show_text("No warnings.")
            return

        t = Table(rows=rows, names=cols)

        if mode == "detail":
            pat = re.compile(r"\[(WARNING|  ERROR)\]\[.*\] (.*)\n")
            for row in t:
                print(
                    f"\n{row['recipe_name']}, {row['name']}, "
                    f"{row['nbwarn']} warnings\n"
                )
                with open(row["log_file"]) as fp:
                    text = fp.read()
                for match in re.finditer(pat, text):
                    level, msg = match.groups(0)
                    print(f"- {level:7s} : {msg}")
        elif mode == "summary":
            d = defaultdict(dict)
            recipes = set(t["recipe_name"])
            for row in t:
                d[row["name"]][row["recipe_name"]] = row["nbwarn"]
            for key, val in d.items():
                val["name"] = key
                for rec in recipes:
                    val.setdefault(rec, 0)
            tbl = Table(rows=list(d.values()), masked=True)
            tbl.sort("name")
            tbl["name"].format = "<s"
            tbl.columns.move_to_end("name", last=False)
            for col in tbl.columns.values()[1:]:
                col[col == 0] = np.ma.masked
            self.fmt.show_table(tbl)
        else:
            t.sort("name")
            t["name"].format = "<s"
            self.fmt.show_table(t)

    def show_images(
        self,
        recipe_name,
        dataset=None,
        DPR_TYPE="IMAGE_FOV",
        filt="white",
        ncols=4,
        figsize=4,
        limit=None,
        date=None,
        catalog=None,
        zoom_center=None,
        zoom_size=None,
        **kwargs,
    ):
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
        date : str or list of str
            List of dates for which images are shown.
        catalog : str
            Catalog to be plotted on images, needs 'ra' and 'dec' columns.
        zoom_center : (float, float)
            Position (in pixels) on which to zoom in.
        zoom_size : (float, float)
            Size (in pixels) of the zoom.
        **kwargs
            Additional parameters are passed to `mpdaf.obj.Image.plot`.

        """
        imgs = self.export_images(
            recipe_name,
            dataset=dataset,
            date=date,
            DPR_TYPE=DPR_TYPE,
            filt=filt,
            limit=limit,
        )

        if catalog is not None:
            tbl = Table.read(catalog)
            skycoords = np.array([tbl["dec"], tbl["ra"]])

        nrows = int(np.ceil(len(imgs) / ncols))
        fig, axes = plt.subplots(
            nrows,
            ncols,
            sharex=True,
            sharey=True,
            figsize=(figsize * ncols, figsize * nrows),
            gridspec_kw={"wspace": 0, "hspace": 0},
        )

        for im, ax in zip(imgs, axes.flat):
            if zoom_size is not None and zoom_center is not None:
                im = im.subimage(
                    zoom_center, zoom_size, unit_center=None, unit_size=None
                )
            im.plot(ax=ax, **kwargs)
            filtr = im.primary_header[FILTER_KEY]
            title = get_exp_name(im.filename)
            if filtr:
                title = f"{title} ({filtr})"
            ax.text(10, im.shape[1] - 25, title)

            if catalog is not None:
                x, y = im.wcs.sky2pix(skycoords.T).T
                sel = (x > 0) & (x < im.shape[0]) & (y > 0) & (y < im.shape[1])
                ax.scatter(x[sel], y[sel], c="r", marker="+")

        for ax in axes.flat[len(imgs) :]:
            ax.axis("off")
        for ax in axes.flat:
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect("equal")

        return fig

    def export_images(
        self,
        recipe_name,
        dataset=None,
        DPR_TYPE="IMAGE_FOV",
        filt="white",
        limit=None,
        outname=None,
        out="list",
        date=None,
    ):
        """Export images as Image list, HDUs, or cube.

        Parameters
        ----------
        recipe_name : str
            Recipe for which images are exported.
        dataset : str, optional
            Dataset for which images are exported.
        DPR_TYPE : str, optional
            Type of images to show.
        filt : str, optional
            Filter, default to white.
        limit : int
            Maximum number of images to show.
        outname : str
            Filename to save the FITS file.
        out : {'list', 'cube', 'hdulist'}
            Specify the output format, 'list' of images, 'cube' of images, or
            'hdulist' with one extension per image.
        date : str or list of str
            List of dates for which images are exported.

        """
        dataset = dataset or list(self.datasets.keys())[0]
        recipe_name = normalize_recipe_name(recipe_name)
        kwargs = {}
        if date:
            kwargs["name"] = self.prepare_dates(date, DPR_TYPE="OBJECT")
        res = list(
            self.reduced.find(
                OBJECT=dataset,
                DPR_TYPE=DPR_TYPE,
                recipe_name=recipe_name,
                _limit=limit,
                order_by="name",
                **kwargs,
            )
        )

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

        self.logger.info("Found %d images", len(imgs))
        if out == "cube":
            cube = Cube(
                data=np.ma.array([im.data for im in imgs]),
                var=np.ma.array([im.data for im in imgs]),
                wcs=imgs[0].wcs,
            )
            if outname:
                cube.write(outname, savemask="nan")
            return cube
        elif out == "hdulist":
            hdul = fits.HDUList([fits.PrimaryHDU()])
            for im in imgs:
                hdr = im.primary_header.copy()
                hdr.update(im.wcs.to_header())
                hdu = fits.ImageHDU(data=im.data.filled(np.nan), header=hdr)
                hdu.name = get_exp_name(im.filename)
                hdul.append(hdu)
            if outname:
                hdul.writeto(outname, overwrite=True)
            return hdul
        elif out == "list":
            return imgs
        else:
            raise ValueError(f"unknown output format {out}")
