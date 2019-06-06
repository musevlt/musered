from pkg_resources import DistributionNotFound, get_distribution

try:
    __version__ = get_distribution("musered").version
except DistributionNotFound:
    # package is not installed
    pass
