"""Tests the command line interface."""

import pytest
from click.testing import CliRunner

from pygaps.cli import cli


@pytest.mark.cli
class TestCLI():

    def test_basic(self):
        """Tests basic CLI run."""
        runner = CliRunner()
        result = runner.invoke(cli)
        assert result.exit_code == 0
