import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--regenerate", action="store_true", default=False, help="Regenerate test data"
    )


@pytest.fixture
def regenerate(request):
    return request.config.getoption("--regenerate")
