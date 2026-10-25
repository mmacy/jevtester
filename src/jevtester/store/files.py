"""Suites and question sets as YAML files under `suites/`, reviewed in git."""

import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from jevtester.errors import InvalidRequestError, NotFoundError
from jevtester.schemas import ErrorDetail
from jevtester.spec import Case, QuestionSet, Suite
from jevtester.spec.policy import Policy

NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
"""Suite, question set, and policy names: lowercase letters, digits, `-`, and `_`, so a name is a safe file name."""
QUESTION_SETS = "question-sets"
POLICIES = "policies"
SUITE_SUFFIX = ".yaml"


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


def parse_policy(text: str, name: str) -> Policy:
    """Parse and validate a policy's YAML text.

    Args:
        text: The YAML.
        name: The name the policy must have.

    Returns:
        The policy.

    Raises:
        InvalidRequestError: The text isn't valid YAML, doesn't match the policy format, or names another policy.
            `details` lists every error.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if isinstance(mark, yaml.Mark) else None
        problem = getattr(error, "problem", None) or str(error)
        message = f"Line {line}: {problem}" if line else f"The policy isn't valid YAML: {problem}"
        raise InvalidRequestError(message, details=[ErrorDetail(message=message, line=line)]) from error
    try:
        policy = Policy.model_validate(data)
    except ValidationError as error:
        details: list[ErrorDetail] = []
        for item in error.errors(include_url=False):
            location = ".".join(str(part) for part in item["loc"]) or None
            details.append(ErrorDetail(field=location, message=item["msg"]))
        first = details[0]
        message = f"{first.field}: {first.message}" if first.field else first.message
        raise InvalidRequestError(message, field=first.field, details=details) from error
    if policy.name != name:
        raise InvalidRequestError(f"The policy is named {policy.name}, not {name}", field="name")
    return policy


def _dump(data: dict[str, Any], indent: int = 2) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120, indent=indent)


def _with_newline(text: str) -> str:
    return text if not text or text.endswith("\n") else f"{text}\n"


def _line_end(text: str, index: int) -> int:
    # The start of the line after `index`. A block scalar's end already includes its newline.
    if index > 0 and text[index - 1] == "\n":
        return index
    newline = text.find("\n", index)
    return len(text) if newline < 0 else newline + 1


def _last_end(node: yaml.Node) -> int:
    # Where the node's last scalar or flow collection ends, before any comment or blank line that follows it.
    match node:
        case yaml.MappingNode(flow_style=False) if node.value:
            return max(_last_end(value) for _, value in node.value)
        case yaml.SequenceNode(flow_style=False) if node.value:
            return max(_last_end(item) for item in node.value)
        case _:
            return node.end_mark.index


def _mapping_indent(node: yaml.Node) -> int:
    # How far a nested mapping is indented from its key in this case, or 2 when the case has none.
    if isinstance(node, yaml.MappingNode):
        for key, value in node.value:
            if isinstance(value, yaml.MappingNode) and not value.flow_style and value.value:
                return value.value[0][0].start_mark.column - key.start_mark.column
    return 2


def _block_item(data: dict[str, Any], dash: int, content: int, indent: int = 2) -> str:
    # One block list item: `-` at column `dash`, and the mapping's keys at column `content`.
    lines = _dump(data, indent).splitlines()
    first = f"{' ' * dash}-{' ' * (content - dash - 1)}{lines[0]}"
    return "".join(f"{line}\n" for line in [first, *(f"{' ' * content}{line}" for line in lines[1:])])


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
        # The suite's settings come first and its cases last, however the model orders them.
        cases = data.pop("cases", None)
        data = {"name": suite.name, "question_set": suite.question_set, **data}
        if cases is not None:
            data["cases"] = cases
        self.suite_path(suite.name).write_text(_dump(data))

    def append_case(self, name: str, case: Case) -> None:
        """Add a case to the end of a suite's `cases`, leaving the rest of the file's text as it is.

        The case is inserted as text after the last case, so the file keeps its comments, quoting, and layout. A new
        block case lines up with the cases before it.

        Args:
            name: The suite's name.
            case: The case.

        Raises:
            InvalidRequestError: The file isn't a YAML mapping.
        """
        path = self.suite_path(name)
        text = path.read_text()
        try:
            loader = yaml.SafeLoader(text)
            try:
                root = loader.get_single_node()
            finally:
                loader.dispose()
        except yaml.YAMLError as error:
            raise InvalidRequestError(f"{path.name} isn't valid YAML: {error}") from error
        if not isinstance(root, yaml.MappingNode):
            raise InvalidRequestError(f"{path.name} isn't a YAML mapping")
        data = case.model_dump(mode="json", exclude_defaults=True)
        found = next(((key, value) for key, value in root.value if key.value == "cases"), None)
        if found is None:
            text = _with_newline(text) + "cases:\n" + _block_item(data, 0, 2)
        else:
            key, cases = found
            if isinstance(cases, yaml.SequenceNode) and cases.value and cases.flow_style:
                at = cases.end_mark.index - 1
                text = f"{text[:at]}, {json.dumps(data, ensure_ascii=False)}{text[at:]}"
            elif isinstance(cases, yaml.SequenceNode) and cases.value:
                last = cases.value[-1]
                item = _block_item(data, cases.start_mark.column, last.start_mark.column, _mapping_indent(last))
                at = _line_end(text, _last_end(last))
                text = text[:at] + item + text[at:]
            else:
                # `cases:` with nothing, or `cases: []`, becomes a block list under the key.
                colon = text.index(":", key.end_mark.index) + 1
                text = text[:colon] + text[cases.end_mark.index :]
                at = _line_end(text, colon)
                text = text[:at] + _block_item(data, key.start_mark.column, key.start_mark.column + 2) + text[at:]
        path.write_text(text)

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

    def policy_path(self, name: str) -> Path:
        """The file for a policy.

        Args:
            name: The policy's name.

        Returns:
            `<root>/policies/<name>.yaml`.
        """
        return self.root / POLICIES / f"{check_name(name, 'policy')}.yaml"

    def list_policies(self) -> list[tuple[Policy, str]]:
        """Read every policy.

        Returns:
            Each policy and its YAML text, by name.

        Raises:
            InvalidRequestError: A policy file is invalid.
        """
        found: list[tuple[Policy, str]] = []
        for path in sorted((self.root / POLICIES).glob("*.yaml")):
            text = path.read_text()
            found.append((parse_policy(text, path.stem), text))
        return found

    def load_policy(self, name: str) -> tuple[Policy, str]:
        """Read one policy.

        Args:
            name: The policy's name.

        Returns:
            The policy and its YAML text.

        Raises:
            NotFoundError: There's no such policy.
            InvalidRequestError: The file is invalid.
        """
        path = self.policy_path(name)
        if not path.is_file():
            raise NotFoundError(f"No policy named {name}")
        text = path.read_text()
        return parse_policy(text, name), text

    def save_policy(self, name: str, text: str) -> Policy:
        """Validate a policy's YAML text and write it as it is, comments and all.

        Args:
            name: The policy's name.
            text: The YAML.

        Returns:
            The policy.

        Raises:
            InvalidRequestError: The text is invalid. Nothing is written.
        """
        policy = parse_policy(text, name)
        path = self.policy_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if text.endswith("\n") else f"{text}\n")
        return policy


def suite_reference(value: str, files: SuiteFiles) -> tuple[SuiteFiles, str]:
    """Resolve a suite argument to the suites directory to read and the suite's name.

    A bare name, like `parley`, is a suite in `files`. A path, which has a directory or ends in `.yaml`, like
    `other/x.yaml`, `other/x`, or `x.yaml`, is that file. Its directory is then the suites directory, so the suite's
    question set and policy are read from that directory's `question-sets/` and `policies/`.

    Args:
        value: The suite's name or file path.
        files: The configured suites directory.

    Returns:
        The suites directory and the suite's name.

    Raises:
        InvalidRequestError: The path ends in a suffix other than `.yaml`, or its file name isn't a valid suite name.
        NotFoundError: The path's file doesn't exist.
    """
    path = Path(value)
    if path.parent == Path() and path.suffix != SUITE_SUFFIX:
        return files, value
    if not path.suffix:
        path = path.with_suffix(SUITE_SUFFIX)
    if path.suffix != SUITE_SUFFIX:
        raise InvalidRequestError(f"A suite file ends in {SUITE_SUFFIX}, got {value}", field="suite")
    name = check_name(path.stem, "suite")
    if not path.is_file():
        raise NotFoundError(f"No suite file {path}", field="suite")
    return SuiteFiles(path.parent), name
