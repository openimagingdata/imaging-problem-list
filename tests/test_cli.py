"""Tests for the finding extractor CLI."""

from click.testing import CliRunner

from finding_extractor.cli import format_json_output, format_table_output, main
from finding_extractor.models import (
    ExamInfo,
    ExtractedFinding,
    FindingAttribute,
    FindingLocation,
    ReportExtraction,
    ValidationResult,
)


class TestFormatJsonOutput:
    """Test cases for JSON output formatting."""

    def test_basic_json_output(self):
        """Test formatting extraction as JSON."""
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="CT Abdomen"),
            findings=[
                ExtractedFinding(
                    finding_name="test finding",
                    presence="present",
                    report_text="Test text.",
                ),
            ],
        )
        output = format_json_output(extraction)
        assert "CT Abdomen" in output
        assert "test finding" in output
        assert '"presence": "present"' in output

    def test_json_with_validation(self):
        """Test formatting extraction with validation results."""
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="Test"),
        )
        validation = ValidationResult(
            is_valid=True,
            verbatim_errors=[],
            coverage_warnings=[],
        )
        output = format_json_output(extraction, validation)
        assert "_validation" in output
        assert "is_valid" in output


class TestFormatTableOutput:
    """Test cases for table output formatting."""

    def test_basic_table_output(self):
        """Test formatting extraction as table."""
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="CT Abdomen"),
            findings=[
                ExtractedFinding(
                    finding_name="pneumonia",
                    presence="present",
                    report_text="Pneumonia seen.",
                ),
            ],
        )
        output = format_table_output(extraction)
        assert "CT Abdomen" in output
        assert "pneumonia" in output
        assert "PRESENT" in output or "Present" in output

    def test_table_with_attributes(self):
        """Test table output with finding attributes."""
        extraction = ReportExtraction(
            exam_info=ExamInfo(study_description="CT"),
            findings=[
                ExtractedFinding(
                    finding_name="renal calculus",
                    presence="present",
                    location=FindingLocation(
                        body_region="abdomen",
                        specific_anatomy="right kidney",
                        laterality="right",
                    ),
                    attributes=[
                        FindingAttribute(key="size", value="3 mm"),
                    ],
                    report_text="Stone seen.",
                ),
            ],
        )
        output = format_table_output(extraction)
        assert "renal calculus" in output
        assert "abdomen" in output
        assert "right" in output.lower()
        assert "size=3 mm" in output


class TestCLI:
    """Test cases for CLI commands."""

    def test_cli_help(self):
        """Test CLI help output."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "extract structured findings" in result.output.lower()
        assert "--exam-type" in result.output
        assert "--output" in result.output
        assert "--model" in result.output

    def test_cli_missing_file(self):
        """Test CLI with missing file."""
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent.txt"])
        assert result.exit_code != 0
