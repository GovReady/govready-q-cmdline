"Command-Line" GovReady-Q via Management Command
================================================

This repository contains a "Django management command" module that can be added to the GovReady-Q source code.

The command is a driver for a command-line version of GovReady-Q. It takes the following actions:

* Creates a dummy organization and user.
* Starts apps and answers questions according to a YAML file given on the command line.
* Writes out all generated output documents in HTML and Markdown formats to an output directory given on the command line.

Note that the database records go into whatever database your GovReady-Q installation is configured to use (e.g. `local/db.sqlite`), and the records created by this tool are not deleted at the end. To avoid polluting your current GovReady-Q database, create a separate install of GovReady-Q.

Installation and Usage
----------------------

Clone this repository in a directory next to govready-q:

	$ git clone https://github.com/GovReady/govready-q-cmdline

Also clone the compliance app repositories containing the compliance apps referenced in the `demo.yaml` into directories next to govready-q:

	git clone git@github.com:GovReady/govready-q-apps-django.git
	git clone git@github.com:GovReady/govready-apps-dev.git

Then go into the govready-q directoy and set up a symlink so Django can see the management command:

	$ cd govready-q
	$ ln -s ../../../../govready-q-cmdline/management_command.py guidedmodules/management/commands/cmdline.py

(The link target's path is always _relative_ to the location of the link, so that's why three extra `../`s are necessary to point to the path to the actual Python file.)

Test that it starts:

	$ ./manage.py cmdline
	usage: manage.py cmdline [-h] [--version] [-v {0,1,2,3}] [--settings SETTINGS]
	                         [--pythonpath PYTHONPATH] [--traceback] [--no-color]
	                         data.yaml outdir
	manage.py cmdline: error: the following arguments are required: data.yaml, outdir

Test that it runs:

	./manage.py cmdline ../govready-q-cmdline/demo.yaml outputdir/

Check the output in:

	outputdir/ssp_0.html
