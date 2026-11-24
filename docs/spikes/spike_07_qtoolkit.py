"""Spike 07: Inspect qtoolkit ShellIO interface for DirectRunner suitability."""

import inspect

from qtoolkit.core.data_objects import QResources
from qtoolkit.io.shell import ShellIO


def main() -> None:
    sio = ShellIO(stdout_path="job.out", stderr_path="job.err")
    print("get_submission_script sig:", inspect.signature(sio.get_submission_script))

    res = QResources(
        job_name="qcai_test",
        output_filepath="job.out",
        error_filepath="job.err",
    )
    script = sio.get_submission_script("g16 < job.gjf > job.log", res)
    print("=== Generated ShellIO script ===")
    print(script)

    print("get_submit_cmd:", sio.get_submit_cmd("submit.sh"))
    print("get_job_cmd:", sio._get_job_cmd("12345"))
    print("get_cancel_cmd:", sio.get_cancel_cmd("12345"))

    sub = sio.parse_submit_output(exit_code=0, stdout="98765\n", stderr="")
    print("parse_submit_output:", sub)
    qjob = sio.parse_job_output(
        exit_code=0,
        stdout="  PID USER     ELAPSED S COMMAND\n98765 alice      01:23 R g16\n",
        stderr="",
        job_id="98765",
    )
    print("parse_job_output:", qjob)
    assert sub.job_id == "98765"
    assert qjob is not None and qjob.job_id == "98765"
    print("\nPASS: spike_07_qtoolkit")


if __name__ == "__main__":
    main()
