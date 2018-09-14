from .recipe import *
from .calib import *
from .science import *
from .calib import calib_classes
from .science import sci_classes
from .imphot import IMPHOT
from .mpdaf import MPDAFCOMBINE

recipe_classes = {
    **calib_classes,
    **sci_classes,
    **{cls.recipe_name: cls for cls in (IMPHOT, MPDAFCOMBINE)}
}
