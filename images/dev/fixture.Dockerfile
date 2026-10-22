# Dev image for the docker tests' fixture repo (tests/jobs/test_coord_loop_docker.py):
# the executor image's toolchain (git, grep, python) is all its grep-style
# suites need. Not used for any real repo.
FROM vigil/claude-executor:2.1.306
USER 10001:10001
WORKDIR /work
