"""The pyGAPS command line interface"""

import click
import pygaps
import matplotlib.pyplot as plt


@click.command()
@click.argument(
    'iso_file',
    type=click.File('rb'))
@click.option(
    '-v', '--verbose', is_flag=True,
    help='Enables verbose mode.')
@click.option(
    '-d', '--display', is_flag=True,
    type=click.BOOL,
    help='Display the isotherm.',
)
@click.option(
    '--bet-area', is_flag=True,
    type=click.BOOL,
    help='Display the isotherm.',
)
def cli(iso_file, verbose, display, bet_area):
    iso = pygaps.isotherm_from_json(iso_file.read())
    if display:
        iso.print_info()
    if bet_area:
        pygaps.area_BET(iso, verbose=True)
        plt.show()
