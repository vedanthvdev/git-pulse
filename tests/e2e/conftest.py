"""E2E test conftest — auto-applies the 'e2e' marker."""

import pytest

pytestmark = pytest.mark.e2e
