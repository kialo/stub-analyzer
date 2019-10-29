import re
from typing import Any
from unittest.mock import patch

import pytest  # type: ignore
from _pytest.capture import CaptureFixture  # type: ignore

from testing.util import MypyNodeFactory, WithStubTestConfig

from .analyze import analyze_stubs, compare, main
from .compare import MatchResult


class TestAnalyzeStubs(WithStubTestConfig):
    def test_analyze_missing(self, capsys: Any) -> None:
        analyze_stubs(
            self.mypy_config_path,
            self.handwritten_stubs_path,
            self.generated_stubs_path,
            self.get_expectations_path("missing.json"),
        )

        _, err = capsys.readouterr()

        assert "missing.MISSING_CONSTANT" not in err
        assert (
            'Expected "missing.missing_function" to be '
            '"mismatch" but it was "not_found"' in err
        )
        assert (
            "Expected the following symbols to fail, but they were not processed:\n"
            " - missing.missing_decorator" in err
        )
        assert 'Symbol "missing.MissingClass" not found in generated stubs' in err

    def test_ignore_missing_module_symbols(self, capsys: CaptureFixture) -> None:
        success = analyze_stubs(
            self.mypy_config_path,
            str(self._base_dir / "test-stubs" / "test_ignore_missing_module_symbols"),
        )

        stdout, err = capsys.readouterr()

        assert 'Symbol "isort.comments.__name__" not found' not in err
        assert 'Symbol "isort.comments.__doc__" not found' not in err
        assert 'Symbol "isort.comments.__file__" not found' not in err
        assert 'Symbol "isort.comments.__package__" not found' not in err

        assert success

    def test_analyze_mismatching(self, capsys: Any) -> None:
        analyze_stubs(
            self.mypy_config_path,
            self.handwritten_stubs_path,
            self.generated_stubs_path,
            self.get_expectations_path("mismatching.json"),
        )

        _, err = capsys.readouterr()

        assert "mismatching.mismatching_function" not in err
        assert (
            'Expected "mismatching.MISMATCHING_CONSTANT" to be "not_found" '
            'but it was "mismatch"' in err
        )
        assert "Types for mismatching.mismatch_variable do not match" in err

    def test_analyze_matching(self, capsys: Any) -> None:
        analyze_stubs(
            self.mypy_config_path,
            self.handwritten_stubs_path,
            self.generated_stubs_path,
            self.get_expectations_path("matching.json"),
        )

        _, err = capsys.readouterr()

        assert "matching.matching_function" not in err
        assert (
            'Expected "matching.MATCHING_CONSTANT" to be "not_found" but it matched'
            in err
        )
        assert (
            'Expected "matching.matching_variable" to be "mismatch" but it matched'
            in err
        )

    def test_analyze_additional_params(self, capsys: Any) -> None:
        analyze_stubs(
            self.mypy_config_path,
            self.handwritten_stubs_path,
            self.generated_stubs_path,
            self.get_expectations_path("additional_function_params.json"),
        )

        _, err = capsys.readouterr()

        assert "functions.additional_args" not in err
        assert (
            'Expected "functions.matching_function" to be "mismatch_additional_args" '
            "but it matched" in err
        )


class TestCompareSymbols:
    def test_generated_is_missing_a_function(self, mypy_nodes: MypyNodeFactory) -> None:
        func_def_symbol = mypy_nodes.get_missing_function_node()
        result = list(compare([func_def_symbol], []))

        assert all(map(lambda x: x.match_result is MatchResult.NOT_FOUND, result))

    def test_generated_is_missing_a_class(self, mypy_nodes: MypyNodeFactory) -> None:
        class_symbol = mypy_nodes.get_missing_class()
        result = list(compare([class_symbol], []))

        assert all(map(lambda x: x.match_result is MatchResult.NOT_FOUND, result))


class TestCommandLineTool:
    @patch("sys.argv", ["analyze-stubs"])
    def test_missing_required_arguments(self, capsys: CaptureFixture) -> None:
        with pytest.raises(SystemExit) as ex:
            main()
        assert ex.value.code == 2

        output = capsys.readouterr().err

        assert re.search(r"analyze-stubs: error", output)
        assert re.search(
            r"the following arguments are required: -c/--config, stubs_handwritten",
            output,
        )

    @patch(
        "sys.argv",
        [
            "analyze-stubs",
            "-c",
            "mypy.ini",
            "testing/test-stubs/test_generated_reference_stubs",
        ],
    )
    def test_generated_reference_stubs(self, capsys: CaptureFixture) -> None:
        """
        Ensures that analyzing stubs with automatically generated reference
        stubs works as expected.
        """
        with pytest.raises(SystemExit) as ex:
            main()
        assert ex.value.code == 1

        output = capsys.readouterr().err

        # incorrectly stubbed
        assert re.search(r"Types for black.DEFAULT_LINE_LENGTH do not match", output)
        assert re.search(r"Types for black.shutdown do not match", output)
        assert re.search(
            r"Symbol \"black.NotFound\" not found in generated stubs", output
        )

        # cancel has been correctly stubbed
        assert not re.search(r"cancel", output)
