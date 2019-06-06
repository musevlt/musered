import click
import inspect
import logging
import os
import sys
from astropy.io import fits
from collections import Counter
from musered.utils import upsert_many


@click.argument("dataset", nargs=-1)
@click.option("--username", help="username for the ESO archive")
@click.option("--help-query", is_flag=True, help="print query options")
@click.option("--dry-run", is_flag=True, help="don't retrieve files")
@click.option("--force", is_flag=True, help="request all objects")
@click.option("--no-update-db", is_flag=True, help="don't update the database")
@click.option(
    "--calib",
    help="retrieve only calibrations for a list of "
    "comma-separated nights (YYYY MM(M) DD)",
)
@click.option("--ins-mode", help="instrument mode for calib retrieval")
@click.option("--start", help="start date, to limit query results")
@click.option("--end", help="end date, to limit query results")
@click.pass_obj
def retrieve_data(
    mr,
    dataset,
    username,
    help_query,
    dry_run,
    force,
    no_update_db,
    calib,
    ins_mode,
    start,
    end,
):
    """Retrieve files and/or calibrations from the ESO archive.

    By default this will retrieve science files and associated calibrations,
    with the filters defined in the settings files. It is also possible to
    retrieve all the calibration files for a list of nights (with --calib) and
    for an instrument mode (--ins-mode).

    Note that the definition of nights is different for MuseRed and for ESO:

    - for MuseRed, the 2017-06-19 night corresponds to the day calibrations of
      2017-06-20
    - for ESO, the 2017-06-19 night corresponds to the day calibrations of
      2017-06-19

    Examples::

        $ musered retrieve-data --start 2017-06-19 IC4406

        $ musered retrieve-data --calib 2017-06-19 --ins-mode WFM-AO-N

    """
    logger = logging.getLogger(__name__)
    if len(dataset) == 0:
        dataset = list(mr.datasets)

    params = mr.conf["retrieve_data"]
    if username is not None:
        params = {**params, "username": username}

    from astroquery.eso import Eso

    if help_query:
        Eso.query_instrument("muse", help=True)
        return

    Eso.login(**params)

    Eso.ROW_LIMIT = -1

    # customize astroquery's cache location, to have it on the same device
    # as the final path
    Eso.cache_location = os.path.join(mr.raw_path, ".cache")
    os.makedirs(Eso.cache_location, exist_ok=True)

    if calib:
        dataset = calib.split(",")

    for ds in dataset:
        if calib:
            ds = ds.replace("-", " ")
            column_filters = {"night": ds, "dp_cat": "CALIB"}
            if ins_mode is not None:
                column_filters["ins_mode"] = ins_mode
        else:
            if ds not in mr.datasets:
                logger.error("dataset '%s' not found", ds)
                sys.exit(1)
            conf = mr.datasets[ds]
            column_filters = conf["archive_filter"]

        if start:
            column_filters["stime"] = start.replace("-", " ")
        if end:
            column_filters["etime"] = end.replace("-", " ")

        logger.info("Searching files for %s", ds)
        logger.info("Filters: %s", column_filters)
        table = Eso.query_instrument("muse", cache=False, column_filters=column_filters)
        if table is None:
            logger.warning("Found nothing")
            continue
        logger.info("Found %d files", len(table))
        table.keep_columns(
            [
                "Object",
                "Target Ra Dec",
                "ProgId",
                "DP.ID",
                "EXPTIME [s]",
                "DPR CATG",
                "DPR TYPE",
                "DPR TECH",
                "TPL START",
                "INS MODE",
                "DIMM Seeing-avg",
            ]
        )
        print(table)
        if not dry_run:
            kw = dict(destination=mr.raw_path)
            if not calib:
                kw["with_calib"] = "raw"
                sig = inspect.signature(Eso.retrieve_data)
                if "request_all_objects" in sig.parameters:
                    kw["request_all_objects"] = force
            Eso.retrieve_data(table["DP.ID"], **kw)

    if not dry_run and not no_update_db:
        mr.update_db()


@click.option("--report", is_flag=True, help="report integrity checks")
@click.pass_obj
def check_integrity(mr, report):
    """Test raw files checksum."""
    checksum_col = "valid_checksum"

    if report:
        if checksum_col not in mr.raw.columns:
            print(f"{len(mr.raw)} files, not verified.")
            return

        count = Counter(mr.select_column("valid_checksum", notnull=False))
        print(f"{len(mr.raw)} files")
        print(f"verified     : {count[True]}")
        print(f"not verified : {count[None]}")
        print(f"invalid      : {count[False]}")
        if count[False] > 0:
            print("\nList of invalid files:")
            print("\n".join(o["path"] for o in mr.raw.find(valid_checksum=False)))
        return

    kw = {checksum_col: None} if checksum_col in mr.raw.columns else {}
    nrows = mr.raw.count(**kw)
    rows = []
    try:
        for i, row in enumerate(mr.raw.find(**kw), start=1):
            with fits.open(row["path"], checksum=True) as hdul:
                for hdu in hdul:
                    if not hdu._checksum_valid or not hdu._datasum_valid:
                        print(f"{i}/{nrows} : {row['path']} : INVALID")
                        rows.append({"id": row["id"], checksum_col: False})
                        break
                else:
                    nhdus = len(hdul)
                    print(f"{i}/{nrows} : {row['path']} : {nhdus} valid HDUs")
                    rows.append({"id": row["id"], checksum_col: True})
    except KeyboardInterrupt:
        print("Saving results before exit...")

    upsert_many(mr.db, "raw", rows, ["id"])
