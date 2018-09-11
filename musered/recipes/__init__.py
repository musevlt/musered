from .recipe import Recipe
from .calib import *
from .science import *
from .calib import calib_classes
from .science import sci_classes
from .imphot import IMPHOT

recipe_classes = {
    **calib_classes,
    **sci_classes,
    **{cls.recipe_name: cls for cls in (IMPHOT, )}
}
