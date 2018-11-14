from .recipe import BaseRecipe
from .recipe import *   # noqa
from .calib import *    # noqa
from .science import *  # noqa
from .imphot import IMPHOT
from .mpdaf import MPDAFCOMBINE
from .std import STDCOMBINE
from .superflat import SUPERFLAT
from ..utils import all_subclasses

recipe_classes = {cls.recipe_name: cls for cls in
                  all_subclasses(BaseRecipe) if cls.recipe_name}

__all__ = [cls.__name__ for cls in all_subclasses(BaseRecipe)]
