import numpy as np
from astropy.utils.decorators import lazyproperty
from enum import Enum
from sqlalchemy import sql

from .utils import ensure_list, load_table

# pre-defined list of flags, can be extended in the settings file
FLAGS = {
    'BAD_CENTERING': 'Centering offset is wrong',
    'BAD_IMAQUALITY': 'Bad image quality',
    'BAD_SKY_FLUX': 'Sky flux looks wrong',
    'BAD_SKY_SUB': 'Sky subtraction is bad',
    'BAD_SLICE': 'Slices with wrong flux',
    'IMPHOT_BAD_SCALE': 'Flux scale value computed by Imphot seems wrong',
    'IMPHOT_HIGH_BKG': 'Flux offset value computed by Imphot seems wrong',
    'IMPHOT_OUTLIER_OFFSET': 'Centering value computed by Imphot seems wrong',
    'SATELLITE': 'Satellite track',
    'SHORT_EXPTIME': 'Incomplete observation',
    'SLICE_GRADIENT': 'Slices show a flux gradient',
}


class QAFlags:
    """Manage QA flags.

    Parameters
    ----------
    table : dataset.Table
        The table containing the flags.
    additional_flags : dict
        Additional flags, added to the default FLAGS dict.

    """

    def __init__(self, table, additional_flags=None):
        flags = FLAGS.copy()
        if additional_flags:
            flags.update(additional_flags)
        self.flags = Enum('flags', flags.items())

        # create integer columns for all flags
        self.table = table
        self.table._sync_columns({'name': '', **{k: 1 for k in self.names}},
                                 True)
        self.execute = self.table.db.executable.execute

    @lazyproperty
    def names(self):
        """Return the list of flag names."""
        return [f.name for f in self.flags]

    def __getattr__(self, name):
        try:
            return self.flags[name]
        except KeyError:
            raise AttributeError

    def __dir__(self):
        return self.names + super().__dir__()

    def _upsert_many(self, rows, keys=['name']):
        with self.table.db as tx:
            table = tx[self.table.name]
            for row in rows:
                table.upsert(row, keys=keys)

    def add(self, exps, *flags, value=1):
        """Add flags to exposures."""
        flags = {flag.name: value for flag in flags}
        self._upsert_many([{'name': e, **flags} for e in ensure_list(exps)])

    def remove(self, exps, *flags):
        """Remove flags from exposures."""
        # TODO: add a mode where we check that the flags were present
        self.add(exps, *flags, value=None)

    def list(self, exps):
        """List flags for exposures."""
        exps = ensure_list(exps)
        res = {o['name']: o for o in self.table.find(name=exps)}
        out = []
        for exp in exps:
            if exp not in res:
                out.append([])
            else:
                expf = res[exp]
                out.append([flag for flag in self.flags if (
                    expf[flag.name] is not None and expf[flag.name] > 0)])
        return out[0] if len(exps) == 1 else out

    def find(self, *flags, _and=False):
        """Find exposures that have some flags."""
        col = self.table.table.c
        clauses = [col[flag.name] > 0 for flag in flags]
        if len(clauses) > 1:
            func = sql.and_ if _and else sql.or_
            wc = func(*clauses)
        else:
            wc = clauses[0]
        return [x[0] for x in self.execute(
            sql.select(['name'], whereclause=wc))]

    def as_table(self, indexes=None, remove_empty_columns=True):
        """Return the flags table as an astropy Table."""
        # For some reason columns are created as float instead of int. So we
        # need to convert them. We also remove the columns with no flagged
        # exposure.
        tbl = load_table(self.table.db, self.table.name, indexes=indexes)
        to_remove = ['id']
        for name, col in tbl.columns.items():
            if col.info.dtype.kind == 'f':
                col = col.astype(int)
                tbl.replace_column(name, col)
                if remove_empty_columns and col.sum() is np.ma.masked:
                    to_remove.append(name)
        tbl.remove_columns(to_remove)
        return tbl
