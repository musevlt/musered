from .recipe import *   # noqa
from .calib import *    # noqa
from .science import *  # noqa
from .calib import calib_classes
from .science import sci_classes
from .imphot import IMPHOT
from .mpdaf import MPDAFCOMBINE
from .std import STDCOMBINE
from .superflat import SUPERFLAT

recipe_classes = {
    **calib_classes,
    **sci_classes,
    **{cls.recipe_name: cls for cls in (
        IMPHOT, MPDAFCOMBINE, SUPERFLAT, STDCOMBINE)}
}
