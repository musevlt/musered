import logging
import sys

from .utils import load_yaml_config, load_db


class MuseRed:

    def __init__(self, settings_file):
        self.logger = logging.getLogger(__name__)
        self.settings_file = settings_file
        self.logger.debug('loading settings from %s', settings_file)
        self.conf = load_yaml_config(settings_file)
        self.datasets = self.conf['datasets']
        self.rawpath = self.conf['paths']['raw']
        self.db = load_db(self.conf['db'])

    def list_datasets(self):
        self.logger.info('Available datasets:')
        for name in self.datasets:
            self.logger.info('- %s', name)
            sys.exit(0)
