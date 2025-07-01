import logging
import subprocess

logger = logging.getLogger(__name__)


def bash(cmd, env=None, **kwargs):
    traceErr = kwargs.pop("traceErr", True)
    if kwargs.pop("trace", True):
        logger.info("run: %s", cmd)
    try:
        return subprocess.check_output(
            f"bash -ec 'set -o pipefail; {cmd}'",
            shell=True,
            text=True,
            env=env,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        if traceErr:
            logger.error(
                "command failed: %s\nstdout=\n%s\nstderr=\n%s\n",
                cmd,
                e.stdout,
                e.stderr,
            )
        raise e
