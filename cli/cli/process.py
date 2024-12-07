import logging
import subprocess

logger = logging.getLogger(__name__)


def bash(cmd, env=None, **kwargs):
    if trace := kwargs.pop("trace", True):
        logger.info("run: %s", cmd)
    try:
        output = subprocess.check_output(
            f"bash -ec 'set -o pipefail; {cmd}'",
            shell=True,
            text=True,
            env=env,
            **kwargs,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "command failed: %s\nstdout=\n%s\nstderr=\n%s\n", cmd, e.stdout, e.stderr
        )
        raise e
    if trace:
        logger.info("output:\n%s", output)
    return output
