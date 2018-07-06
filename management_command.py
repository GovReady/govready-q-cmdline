from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils.crypto import get_random_string

from siteapp.models import User, Organization, Project
from guidedmodules.models import AppSource, Task, TaskAnswer
from guidedmodules.module_logic import ModuleAnswers

import sys
import os
import os.path
import rtyaml

def log(msg):
    print(msg, file=sys.stderr)

class Command(BaseCommand):
    help = 'Starts compliance apps using a YAML driver file that specifies apps and data.'

    def add_arguments(self, parser):
        parser.add_argument('data.yaml', type=str)
        parser.add_argument('outdir', type=str)

    def handle(self, *args, **options):
        self.StartApps(options['data.yaml'], options["outdir"])

    @staticmethod
    def StartApps(fn, outdir):
        # Create stub data structures that are required to do module logic
        # but that have no end-user-visible presence.
        Command.dummy_org = Organization.objects.create(subdomain=get_random_string(12))
        Command.dummy_user = User.objects.create(username=get_random_string(12))

        # Cache app sources and app instances as we load app data into the
        # database so that when sources and apps occur multiple times we
        # reuse the existing instances in the database.
        Command.app_sources = { }
        Command.app_instances = { }

        # Open the end-user data file.
        data = rtyaml.load(open(fn))

        # Start the app.
        project = Command.start_app(data.get("app"))

        # Fill in the answers.
        Command.set_answers(project.root_task, data.get("questions", []))

        # Generate outputs.
        os.makedirs(outdir, exist_ok=True)
        for path, outputdoc in Command.generate_task_outputs([], project.root_task):
            path = "_".join(path)
            for ext, format in (("html", "html"), ("md", "markdown")):
                if format in outputdoc:
                    fn = os.path.join(outdir, path + "." + ext)
                    with open(fn, "w") as f:
                        f.write(outputdoc[format])

    @staticmethod
    def start_app(app):
        # Validate app info. It can be specified either as a string path
        # to a local copy of an app, or as a Python dict holding 'source'
        # and 'name' keys, where 'source' is the AppSource connection spec.
        if not isinstance(app, (dict, str)): raise ValueError("invalid data type")
        if isinstance(app, dict):
            if not isinstance(app.get("source"), dict): raise ValueError("invalid data type")
            if not isinstance(app.get("name"), str): raise ValueError("invalid data type")

        # Get an existing AppInstance if we've already created this app,
        # otherwise create a new AppInstance.
        key = rtyaml.dump(app)
        if key in Command.app_instances:
            app_inst = Command.app_instances[key]
        else:
            # Create a AppSource, or reuse if this source has been used before.

            if isinstance(app, str):
                # If given as a string, take the last directory name as the
                # app name and the preceding directories as the AppSource
                # connection path.
                spec = { "type": "local", "path": os.path.dirname(app) }
                appname = os.path.basename(app)
            else:
                # Otherwise the 'source' and 'name' keys hold the source and app info.
                spec = app["source"]
                appname = app["name"]

            # If we've already created & cached the AppSource, use it.
            srckey = rtyaml.dump(spec)
            if srckey in Command.app_sources:
                app_src = Command.app_sources[srckey]

            # Create a new AppSource.
            else:
                app_src = AppSource.objects.create(
                    slug="source_{}_{}".format(len(Command.app_sources), get_random_string(6)),
                    spec=spec,
                )
                Command.app_sources[srckey] = app_src

            # Start an app.
            from guidedmodules.app_loading import load_app_into_database
            with app_src.open() as conn:
                log("Loading compliance app {} from {}...".format(appname, app_src.get_description()))
                app_inst = load_app_into_database(conn.get_app(appname))

            Command.app_instances[key] = app_inst

        # Start the app --- make a Project object.
        log("Starting compliance app {} from {}...".format(app_inst.appname, app_inst.source.get_description()))
        module = app_inst.modules.get(module_name="app")
        project = Project.objects.create(organization=Command.dummy_org)
        project.set_root_task(module, Command.dummy_user)

        return project

    @staticmethod
    def set_answers(task, answers):
        # Fill in the answers for this task using the JSON data in answers,
        # which is a list of dicts that have "id" holding the question ID
        # and other fields. We call set_answer for all questions, even if
        # there is no user-provided answer, because some module-type questions
        # without protocols should be answered with a sub-Task anyway (see below).

        # Map the answers to a dict.
        if not isinstance(answers, list): raise ValueError("invalid data type")
        answers = { answer["id"]: answer for answer in answers
                    if isinstance(answer, dict) and "id" in answer }

        log("Answering {}...".format(task))
        not_answered = []
        for question in task.module.questions.order_by('definition_order'):
            if not Command.set_answer(task, question, answers.get(question.key)):
                not_answered.append(question.key)
        if not_answered:
            log("  There were no answers for: {}".format(", ".join(not_answered)))

    @staticmethod
    def set_answer(task, question, answer):
        # Set the answer to the question for the given task.

        if question.spec["type"] == "module" and question.answer_type_module is not None:
            # If there is no answer provided, normally we leave
            # the answer blank. However, for module-type questions
            # with a module type (not a protocol), we should at least
            # *start* the sub-task with the module answer type, even if we
            # don't answer any of its questions, because it may be
            # a question-less module that only provides output documents.
            log("Starting {}...".format(question.key))
            sub_task = task.get_or_create_subtask(Command.dummy_user, question)
            if answer is not None:
                Command.set_answers(sub_task, answer.get("questions", []))
                return True
            return False

        # If the question isn't answered, leave it alone.
        if answer is None:
            return False

        # Set an answer to the question.

        # Get the TaskAnswer record, which has the save_answer function.
        taskans, isnew = TaskAnswer.objects.get_or_create(task=task, question=question)
        
        if question.spec["type"] in ("module", "module-set"):
            # A module-type question with a protocol (if there was no protocol, it
            # was handled above) or a module-set question (with or without a protocol).

            if question.spec["type"] == "module":
                answers = [answer]
            else:
                answers = answer.get("answers", [])
            
            # Start the app(s).
            for i, answer in enumerate(answers):
                if question.answer_type_module is not None:
                    # Start the sub-task.
                    answers[i] = task.get_or_create_subtask(Command.dummy_user, question)
                else:
                    # Start the app. The app to start is specified in the 'app' key.
                    if not isinstance(answer, dict): raise ValueError("invalid data type")
                    project = Command.start_app(answer.get("app"))

                    # Validate that the protocols match.
                    unimplemented_protocols = set(question.spec.get("protocol", [])) - set(project.root_task.module.spec.get("protocol", []))
                    if unimplemented_protocols:
                        # There are unimplemented protocols.
                        log("{} doesn't implement the protocol {} required to answer {}.".format(
                            project.root_task.module.app,
                            ", ".join(sorted(unimplemented_protocols)),
                            question.key
                        ))
                        return False

                    # Keep the root Task to be an answer to the question.
                    answers[i] = project.root_task

                # Set answers of sub-task.
                Command.set_answers(answers[i], answer.get("questions", []))

            # Save the answer.
            if taskans.save_answer(None, answers, None, Command.dummy_user, "api"):
                log("Answered {} with {}...".format(question.key, answers))
                return True

        else:
            # This is a regular question type with YAML data holding the answer value.
            # Validate the value.
            from guidedmodules.answer_validation import validator
            try:
                value = validator.validate(question, answer["answer"])
            except ValueError as e:
                log("Answering {}: {}...".format(question.key, e))
                return False

            # Save the value.
            if taskans.save_answer(value, [], None, Command.dummy_user, "api"):
                log("Answered {} with {}...".format(question.key, answer))
                return True

            # No change, somehow.
            return False

    @staticmethod
    def generate_task_outputs(path, task):
        print("Generating documents for", " ".join(path) if path else "top-level app", "...")

        # Generate this task's output documents.
        for i, doc in enumerate(task.render_output_documents()):
            key = doc["id"] if "id" in doc else str(i)
            yield (path+[key], doc)

        # Run recursively on any module answers to questions.
        for key, val in task.get_answers().with_extended_info().as_dict().items():
            if isinstance(val, ModuleAnswers) and val.task:
                yield from Command.generate_task_outputs(path+[key], val.task)