"""`deploy/load/utilization.sh` over a canned `/proc/stat` pair, a fake psql and redis-cli."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[4] / "deploy" / "load" / "utilization.sh"


def _fake(path: Path, body: str) -> str:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)
    return str(path)


def _run(tmp_path: Path, psql_body: str, *extra: str) -> subprocess.CompletedProcess[str]:
    first = tmp_path / "stat-1"
    second = tmp_path / "stat-2"
    first.write_text("cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 1 1 1 0 0 0 0 0 0\n")
    second.write_text("cpu  200 0 200 1000 0 0 0 0 0 0\ncpu0 1 1 1 1 0 0 0 0 0 0\n")
    psql = _fake(tmp_path / "psql", psql_body)
    redis = _fake(tmp_path / "redis-cli", "printf '# Clients\\r\\nconnected_clients:4\\r\\n'\n")
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--samples",
            "1",
            "--interval",
            "0",
            "--proc-stat",
            str(first),
            "--proc-stat",
            str(second),
            "--psql",
            psql,
            "--redis-cli",
            redis,
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "LC_ALL": "C"},
    )


def test_one_sample_is_one_json_line(tmp_path: Path) -> None:
    done = _run(tmp_path, "printf '12|3|9|2|7|12||web@a:12\\n'\n")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1
    sample = json.loads(lines[0])
    assert sample["host_cpu"] == 50.0
    assert (sample["pg_total"], sample["pg_active"], sample["pg_idle"]) == (12, 3, 9)
    assert sample["idle_in_tx"] == 2
    assert sample["outbox_pending"] == 7
    assert sample["redis_clients"] == 4
    assert "worker_backlog" not in sample
    assert isinstance(sample["ts"], float)


def test_the_outbox_count_reads_pending_rows_and_is_null_before_migrate(tmp_path: Path) -> None:
    body = (
        'case "$*" in *"from events_outbox where status = \'\'pending\'\'"*"to_regclass"*)'
        " printf '5|1|4|0|-|5||web@a:5\\n' ;;\n"
        "*) echo 'the query reads no pending outbox' >&2; exit 1 ;; esac\n"
    )
    done = _run(tmp_path, body)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["outbox_pending"] is None


def test_four_counts_are_could_not_look(tmp_path: Path) -> None:
    done = _run(tmp_path, "printf '12|3|9|7\\n'\n")
    assert done.returncode == 2
    assert "not six counts and two named lists" in done.stderr
    assert done.stdout == ""


def test_the_worker_backlog_sums_both_halves_of_the_queue(tmp_path: Path) -> None:
    described = (
        '{"stats": [{"taskQueueType": "activity", "approximateBacklogCount": 3},\n'
        '{"taskQueueType": "workflow", "approximateBacklogCount": 2}]}'
    )
    temporal = _fake(
        tmp_path / "temporal",
        'case "$*" in "task-queue describe --task-queue djb-laptop -o json")'
        f" cat <<'JSON'\n{described}\nJSON\n;; *) exit 1 ;; esac\n",
    )
    done = _run(
        tmp_path,
        "printf '1|1|0|0|0|1||web@a:1\\n'\n",
        "--temporal",
        temporal,
        "--task-queue",
        "djb-laptop",
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["worker_backlog"] == 5
    assert "worker backlog" not in done.stderr


def test_a_describe_with_no_backlog_is_could_not_look(tmp_path: Path) -> None:
    temporal = _fake(tmp_path / "temporal", "echo '{\"pollers\": null}'\n")
    done = _run(
        tmp_path, "printf '1|1|0|0|0|1||web@a:1\\n'\n", "--temporal", temporal, "--task-queue", "q"
    )
    assert done.returncode == 2
    assert "approximateBacklogCount" in done.stderr


def test_it_says_what_it_does_not_cover(tmp_path: Path) -> None:
    done = _run(tmp_path, "printf '1|1|0|0|0|1||web@a:1\\n'\n")
    assert (
        "does_not_cover: RDS metrics, worker backlog, the pool's own depth "
        "(no endpoint exposes it)" in done.stderr
    )


def test_a_psql_that_cannot_answer_is_could_not_look(tmp_path: Path) -> None:
    done = _run(tmp_path, "echo 'connection refused' >&2\nexit 1\n")
    assert done.returncode == 2
    assert "could not look" in done.stderr
    assert done.stdout == ""


def test_the_census_query_excludes_its_own_backend(tmp_path: Path) -> None:
    body = (
        'case "$*" in *"pid <> pg_backend_pid()"*) printf \'5|1|4|0|0|5||web@a:5\\n\' ;;\n'
        "*) echo 'the query counted its own backend' >&2; exit 1 ;; esac\n"
    )
    done = _run(tmp_path, body)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["pg_total"] == 5


def test_cpu_only_names_its_box_and_reads_no_database(tmp_path: Path) -> None:
    done = _run(tmp_path, "exit 1\n", "--cpu-only", "--cpu-key", "client_cpu")
    assert done.returncode == 0, done.stderr
    sample = json.loads(done.stdout)
    assert set(sample) == {"ts", "client_cpu"}
    assert sample["client_cpu"] == 50.0


def test_the_census_splits_client_backends_from_the_rest(tmp_path: Path) -> None:
    body = (
        'case "$*" in *"backend_type = \'client backend\'"*)'
        " printf '27|1|22|4|4|26|autovacuum_worker:1|web@a:10,worker@b:16\\n' ;;\n"
        "*) echo 'the query does not split client backends' >&2; exit 1 ;; esac\n"
    )
    done = _run(tmp_path, body)
    assert done.returncode == 0, done.stderr
    sample = json.loads(done.stdout)
    assert (sample["pg_total"], sample["pg_clients"]) == (27, 26)
    assert sample["pg_other"] == "autovacuum_worker:1"


def test_no_other_backend_is_an_empty_pg_other(tmp_path: Path) -> None:
    done = _run(tmp_path, "printf '5|1|4|0|0|5||web@a:5\\n'\n")
    assert done.returncode == 0, done.stderr
    sample = json.loads(done.stdout)
    assert (sample["pg_total"], sample["pg_clients"], sample["pg_other"]) == (5, 5, "")


def test_the_census_names_each_client_backends_process_class(tmp_path: Path) -> None:
    body = (
        'case "$*" in *"application_name"*)'
        " printf '26|0|22|4|4|26||web@a:10,worker@b:16\\n' ;;\n"
        "*) echo 'the query names no application' >&2; exit 1 ;; esac\n"
    )
    done = _run(tmp_path, body)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["pg_by_app"] == "web@a:10,worker@b:16"


def test_the_census_does_not_filter_on_the_role(tmp_path: Path) -> None:
    body = (
        "case \"$*\" in *usename*) echo 'the census filters a role' >&2; exit 1 ;;\n"
        "*) printf '5|1|4|0|0|5||web@a:5\\n' ;; esac\n"
    )
    done = _run(tmp_path, body)
    assert done.returncode == 0, done.stderr
