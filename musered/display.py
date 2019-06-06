# musered display utilities

import numpy as np
from datetime import datetime
from .utils import join_tables, parse_datetime


WeatherTranslate = dict(
    Photometric="PH",
    Clear="CL",
    ThinCirrus="TN",
    ThickCirrus="TK",
    Cloudy="CO",
    Windy="W",
)
WeatherColors = dict(
    PH="green", CL="blue", TN="magenta", TK="red", CO="black", W="cyan"
)


def display_nights(
    ax,
    mr,
    tabname,
    colname,
    nights=None,
    weather=True,
    color="k",
    symbol="o",
    explist=[],
    return_pval=False,
    std=False,
    scol="black",
):
    """Display QA values for selection of nights.

    Parameters
    ----------
    mr: MuseRed
        Musered object
    tabname: str
        QA table name (qa_raw, qa_reduced)
    colname: str
        column name to plot
    nights: list of str
        list of nights to plot, if None all nights are plotted
    weather: bool
        if True weather information is displayed as color coded lines
    color: str
        symbol color (filled)
    symbol: str
        type of symbol
    explist: list of str
        list of exposures to display with unfilled symbol
    return_pval: bool
        if True the plotted dates and values are returned
    std: bool
        if true plot also observed std stars
    scol: str
        color of std line
    """
    # perform selection with join
    qatab = mr.db[mr.tables[tabname]].table
    cols = [mr.rawc.name, mr.rawc.night, qatab.columns[colname]]

    if nights is not None:
        wc = mr.rawc.night.in_(nights)
    else:
        wc = None

    exps = list(
        join_tables(
            mr.db,
            [qatab.name, mr.raw.name],
            columns=cols,
            use_labels=False,
            whereclause=wc,
        )
    )

    if weather:
        w = mr.get_astropy_table("weather_conditions")

    dates = [parse_datetime(exp["name"]) for exp in exps if exp["name"] not in explist]
    vals = [exp[colname] for exp in exps if exp["name"] not in explist]
    ax.plot_date(dates, vals, marker=symbol, color=color)

    if std:  # display std stars observation
        wdates = {
            dt["name"]: datetime.strptime(dt["name"], "%Y-%m-%dT%H:%M:%S.%f")
            for dt in mr.raw.find(DPR_TYPE="STD", night=nights)
        }
        exc = mr.frames.get_excludes(DPR_TYPE="STD")
        for name, wt in wdates.items():
            if name in exc:
                ax.axvline(wt, color=scol, ls="-.", alpha=0.6)
            else:
                ax.axvline(wt, color=scol, ls="--", alpha=0.7)

    if return_pval:
        pdates = dates
        pvals = vals

    if len(explist) > 0:
        dates = [parse_datetime(exp["name"]) for exp in exps if exp["name"] in explist]
        if len(dates) > 0:
            vals = [exp[colname] for exp in exps if exp["name"] in explist]
            ax.plot_date(
                dates, vals, marker=symbol, markerfacecolor="w", markeredgecolor=color
            )
            if return_pval:
                pvals += vals
                pdates += dates
    if weather:
        nights = np.unique([exp["night"] for exp in exps])
        mask = np.in1d(w["night"], nights)
        wn = w[mask]
        for e in wn:
            wt = datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S")
            wcond = [WeatherTranslate[el] for el in e["Conditions"].split(",")]
            wcol = WeatherColors[wcond[0]]
            ax.axvline(wt, color=wcol, alpha=0.5)
    if return_pval:
        return (pdates, pvals)


def display_runs(
    axlist, mr, tabname, colname, runs=None, median=False, color="k", **kwargs
):
    """Display QA values for selection of runs.

    Parameters
    ----------
    axlist: list of axes
        List of axis (number of axis must be equal to the list of runs).
    mr: MuseRed
        Musered object.
    tabname: str
        QA table name (qa_raw, qa_reduced).
    colname: str
        Column name to plot.
    runs: list of str
        List of runs to plot, if None all runs are plotted (dimension must
        be equal to axlist dimension).
    median: bool
        If True the median value of all runs is plotted.
    color: str
        symbol color (filled)
    **kwargs
        Additional args passed to display_nights.

    """
    if runs is None:
        runs = sorted(mr.runs)

    # loop on runs
    lvals = []
    for ax, run in zip(axlist, runs):
        nights = np.unique(
            [e["night"] for e in mr.raw.find(run=run, name=mr.exposures["MXDF"])]
        )
        nights = nights.tolist()
        dates, vals = display_nights(
            ax,
            mr,
            tabname,
            colname,
            nights=nights,
            color=color,
            return_pval=True,
            **kwargs,
        )
        if len(vals) > 0 and vals is not None:
            lvals += [v for v in vals if v is not None]
        ax.set_title(run)

    if median:
        med = np.median(lvals)
        for ax in axlist:
            ax.axhline(med, color=color, alpha=0.5)
