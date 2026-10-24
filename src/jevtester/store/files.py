"""Suites and question sets as YAML files under `suites/`, reviewed in git."""

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from jevtester.errors import InvalidRequestError, NotFoundError
from jevtester.spec import QuestionSet, Suite

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
"""Suite, question set, and policy names: lowercase letters, digits, `-`, and `_`, so a name is a safe file name."""
QUESTION_SETS = "question-sets"


def check_name(name: str, kind: str) -> str:
    """Check that a name can be a file name.

    Args:
        name: The name.
        kind: What it names, for the error message, like `suite`.

    Returns:
        The name.

    Raises:
        InvalidRequestError: The name has characters other than lowercase letters, digits, `-`, and `_`.
    """
    if not NAME_PATTERN.match(name):
        raise InvalidRequestError(f"A {kind} name uses lowercase letters, digits, - and _, got {name!r}", field="name")
    return name


def _describe(path: Path, error: ValidationError) -> str:
    first = error.errors(include_url=False)[0]
    location = ".".join(str(part) for part in first["loc"])
    return f"{path.name}: {location}: {first['msg']}" if location else f"{path.name}: {first['msg']}"


def _read[M: BaseModel](path: Path, model: type[M]) -> M:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise InvalidRequestError(f"{path.name} isn't valid YAML: {error}") from error
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise InvalidRequestError(_describe(path, error)) from error


def _dump(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)


class SuiteFiles:
    """The suites and question sets in one directory."""

    def __init__(self, root: Path) -> None:
        """Read and write files under `root`.

        Args:
            root: The suites directory. Question sets are in its `question-sets/` directory.
        """
        self.root = root

    def suite_path(self, name: str) -> Path:
        """The file for a suite.

        Args:
            name: The suite's name.

        Returns:
            `<root>/<name>.yaml`.
        """
        return self.root / f"{check_name(name, 'suite')}.yaml"

    def question_set_path(self, name: str) -> Path:
        """The file for a question set.

        Args:
            name: The question set's name.

        Returns:
            `<root>/question-sets/<name>.yaml`.
        """
        return self.root / QUESTION_SETS / f"{check_name(name, 'question set')}.yaml"

    def list_suites(self) -> list[Suite]:
        """Read every suite.

        Returns:
            The suites, by name.

        Raises:
            InvalidRequestError: A suite file is invalid.
        """
        return [_read(path, Suite) for path in sorted(self.root.glob("*.yaml"))]

    def load_suite(self, name: str) -> Suite:
        """Read one suite.

        Args:
            name: The suite's name.

        Returns:
            The suite.

        Raises:
            NotFoundError: There's no such suite.
            InvalidRequestError: The file is invalid, or its name doesn't match the file name.
        """
        path = self.suite_path(name)
        if not path.is_file():
            raise NotFoundError(f"No suite named {name}")
        suite = _read(path, Suite)
        if suite.name != name:
            raise InvalidRequestError(f"{path.name} names the suite {suite.name}")
        return suite

    def save_suite(self, suite: Suite) -> None:
        """Write a suite, replacing its file.

        Args:
            suite: The suite.
        """
        data = suite.model_dump(mode="json", exclude_defaults=True)
        data = {"name": suite.name, "question_set": suite.question_set, **data}
        self.suite_path(suite.name).write_text(_dump(data))

    def list_question_sets(self) -> list[QuestionSet]:
        """Read every question set.

        Returns:
            The question sets, by name.

        Raises:
            InvalidRequestError: A question set file is invalid.
        """
        return [_read(path, QuestionSet) for path in sorted((self.root / QUESTION_SETS).glob("*.yaml"))]

    def load_question_set(self, name: str) -> QuestionSet:
        """Read one question set.

        Args:
            name: The question set's name.

        Returns:
            The question set as its file has it now.

        Raises:
            NotFoundError: There's no such question set.
            InvalidRequestError: The file is invalid, or its name doesn't match the file name.
        """
        path = self.question_set_path(name)
        if not path.is_file():
            raise NotFoundError(f"No question set named {name}")
        question_set = _read(path, QuestionSet)
        if question_set.name != name:
            raise InvalidRequestError(f"{path.name} names the question set {question_set.name}")
        return question_set

    def save_question_set(self, question_set: QuestionSet) -> None:
        """Write a question set, replacing its file.

        Args:
            question_set: The question set.
        """
        path = self.question_set_path(question_set.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        questions = {
            key: question.model_dump(mode="json", exclude_none=True) for key, question in question_set.questions.items()
        }
        path.write_text(_dump({"name": question_set.name, "questions": questions}))
