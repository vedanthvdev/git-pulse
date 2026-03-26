"""Integration test conftest — auto-applies the 'integration' marker."""

import pytest

pytestmark = pytest.mark.integration
