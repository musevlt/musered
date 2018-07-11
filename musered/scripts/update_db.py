import click


@click.pass_obj
def update_db(mr):
    """Create or update the database containing FITS keywords."""

    mr.update_db()
