from .recipe import BaseRecipe
from .recipe import *   # noqa
from .calib import *    # noqa
from .science import *  # noqa
from .imphot import IMPHOT
from .mpdaf import MPDAFCOMBINE
from .std import STDCOMBINE
from .superflat import SUPERFLAT
from .zap import ZAP
from ..utils import all_subclasses

recipe_classes = {cls.recipe_name: cls for cls in
                  all_subclasses(BaseRecipe) if cls.recipe_name}

__all__ = [cls.__name__ for cls in all_subclasses(BaseRecipe)] + [
    'normalize_recipe_name', 'get_recipe_cls']


def normalize_recipe_name(recipe_name):
    """Add ``muse_`` prefix if needed for the DRS recipe names.

    >>> normalize_recipe_name('scibasic')
    'muse_scibasic'
    >>> normalize_recipe_name('muse_scibasic')
    'muse_scibasic'

    """
    if recipe_name in recipe_classes:
        return recipe_name
    elif not recipe_name.startswith('muse_'):
        recipe_name = 'muse_' + recipe_name
    return recipe_name


def get_recipe_cls(recipe_name):
    """Return the class for a recipe."""
    recipe_name = normalize_recipe_name(recipe_name)
    return recipe_classes[recipe_name]
