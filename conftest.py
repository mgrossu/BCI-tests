import pytest
import testinfra
import subprocess
import os
import tempfile

from typing import Any, NamedTuple

from requests import get

from bci_tester.parse_data import Container
from bci_tester.helpers import (
    get_selected_runtime,
    GitRepositoryBuild,
)


class ContainerData(NamedTuple):
    version: str
    image_url: str
    connection: Any


@pytest.fixture(scope="function")
def container_git_clone(request, auto_container):
    """This fixture clones the `GitRepositoryBuild` passed as an indirect
    parameter to it into the currently selected container.

    It returns the GitRepositoryBuild to the requesting test function.
    """
    assert isinstance(request.param, GitRepositoryBuild), (
        f"got an invalid request parameter {type(request.param)}, "
        "expected GitRepository"
    )
    auto_container.connection.run_expect([0], request.param.clone_command)
    yield request.param


@pytest.fixture(scope="function")
def host_git_clone(request, host, tmp_path):
    """This fixture clones the `GitRepositoryBuild` into a temporary directory
    on the host system, `cd`'s into it and returns the path and the
    `GitRepositoryBuild` as a tuple to the test function requesting this it.
    """

    if isinstance(request.param, GitRepositoryBuild):
        git_repo_build = request.param
    elif (
        hasattr(request.param, "values")
        and len(request.param.values) == 1
        and isinstance(request.param.values[0], GitRepositoryBuild)
    ):
        git_repo_build = request.param.values[0]
    else:
        raise ValueError(
            f"got an invalid request parameter {type(request.param)}, "
            "expected GitRepositoryBuild or SubRequest with a GitRepositoryBuild"
        )
    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        host.run_expect([0], git_repo_build.clone_command)
        yield tmp_path, git_repo_build
    finally:
        os.chdir(cwd)


@pytest.fixture(scope="module")
def container_runtime():
    return get_selected_runtime()


# All the tests using this fixture in a single testfile will use single container,
# unless the parallelization effort forces them to create another one.
# If we need to move towards one test per container, remove
# scope='module' to default back to scope='function'
# NB: We've pulled the image beforehand, so the docker-run should be almost instant, and it shouldn't be a problem
# to switch scope. If the docker pull is _NOT_ in the tox.ini, make sure your pull the image if you want to run on scope='function'.
@pytest.fixture(scope="module")
def auto_container(request, container_runtime):
    launch_data: Container = request.param

    container_id = (
        subprocess.check_output(
            [container_runtime.runner_binary] + launch_data.launch_cmd
        )
        .decode()
        .strip()
    )
    yield ContainerData(
        version=launch_data.version,
        image_url=launch_data.url,
        connection=testinfra.get_host(
            f"{container_runtime.runner_binary}://{container_id}"
        ),
    )
    subprocess.check_call(
        [container_runtime.runner_binary, "rm", "-f", container_id]
    )


container = auto_container


@pytest.fixture(scope="module")
def dapper(host):
    """Fixture that ensures that dapper is installed on the host system and
    yields the path to the dapper binary.

    If dapper is already installed on the host, then its location is
    returned. Otherwise, dapper is either build from source inside a temporary
    directory or downloaded from rancher.com (if no go toolchain can be found).

    """
    if host.exists("dapper"):
        yield host.find_command("dapper")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        if host.exists("go"):
            gopath = os.path.join(tmpdir, "gopath")
            host.run_expect(
                [0], f"GOPATH={gopath} go get github.com/rancher/dapper"
            )
            yield os.path.join(gopath, "bin", "dapper")
        else:
            resp = get(
                "https://releases.rancher.com/dapper/latest/dapper-"
                + host.system_info.type.capitalize()
                + "-"
                + host.system_info.arch
            )
            dest = os.path.join(tmpdir, "dapper")
            with open(dest, "wb") as dapper_file:
                dapper_file.write(resp.content)
            yield dest
