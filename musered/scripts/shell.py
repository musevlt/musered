import click


@click.pass_obj
def shell(mr):
    """Starts an IPython shell."""

    # Ipython does not work if it receive sys.argv arguments, so we remove this
    # now...
    import sys

    sys.argv[:] = sys.argv[:1]

    # First create a config object from the traitlets library
    from traitlets.config import Config

    c = Config()

    # Now we can set options as we would in a config file:
    #   c.Class.config_value = value
    # For example, we can set the exec_lines option of the InteractiveShellApp
    # class to run some code when the IPython REPL starts
    c.InteractiveShellApp.exec_lines = [
        'print("\\nStarting IPython for MuseRed")',
        'print("\\nThe MuseRed object is available as `mr`\\n")',
        "import musered",
        f'mr = musered.MuseRed(version="{mr.version}")',
    ]
    c.InteractiveShell.colors = "LightBG"
    c.InteractiveShell.confirm_exit = False
    c.TerminalIPythonApp.display_banner = False

    # Now we start ipython with our configuration
    import IPython

    IPython.start_ipython(config=c)
