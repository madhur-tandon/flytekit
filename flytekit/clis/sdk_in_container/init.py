import click
from cookiecutter.main import cookiecutter
from cookiecutter.prompt import read_user_variable


@click.command("init")
@click.option("--template", default="simple-example", help="cookiecutter template to be used")
@click.argument("project-name")
def init(template, project_name):
    """
    Create flyte-ready projects.
    """
    click.echo(
        "What should we call your application? This serves as the top level package where your workflows will live."
    )
    app = read_user_variable("app", "myapp")
    click.echo("What should be the name of your example workflow?")
    workflow_name = read_user_variable("workflow", "workflow_example")

    config = {
        "project_name": project_name,
        "app": app,
        "workflow": workflow_name,
    }
    cookiecutter(
        "https://github.com/flyteorg/flytekit-python-template.git",
        # TODO: remove this once we make the transition to cookie-cutter official.
        checkout="cookie-cutter",
        no_input=True,
        # We do not want to clobber existing files/directories.
        overwrite_if_exists=False,
        extra_context=config,
        # By specifying directory we can have multiple templates in the same repository,
        # as described in https://cookiecutter.readthedocs.io/en/1.7.2/advanced/directories.html.
        # The idea is to extend the number of templates, each in their own subdirectory, for example
        # a tensorflow-based example.
        directory=template,
    )