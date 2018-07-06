import click
# import logging
from astroquery.eso import Eso

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
def cli():
    """Muse data reduction."""


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('--username', help='username')
@click.option('--destination', default='raw', help='destination directory')
@click.option('--target-name', help='target name')
@click.option('--verbose', is_flag=True, help='verbose output')
def retrieve_data(username, destination, target_name, verbose):
    """Retrieve data from the ESO archive."""

    eso = Eso()
    eso.login(username, store_password=True)

    # logging.getLogger('astropy').setLevel('DEBUG')

    table = eso.query_instrument('muse',
                                 column_filters={'obs_targ_name': target_name})
    if verbose:
        print(len(table))
        print('\n'.join(table['DP.ID']))

    eso.retrieve_data(table['DP.ID'], destination=destination,
                      with_calib='raw')


cli.add_command(retrieve_data)

if __name__ == '__main__':
    cli()
