from .recipe import Recipe
from .calib import *
from .science import *
from .calib import calib_classes
from .science import sci_classes

recipe_classes = {**calib_classes, **sci_classes}
