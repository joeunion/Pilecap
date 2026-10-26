"""The load drive's judgments over canned samples, run by name and off every gate (ADR perf-1)."""

from __future__ import annotations

import argparse
import http.server
import importlib.util
import json
import ssl
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
DRIVE = REPO / "deploy" / "load" / "drive.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("load_drive", DRIVE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["load_drive"] = module
    spec.loader.exec_module(module)
    return module


drive = _load()


def _samples(*, n: int, seconds: float, ms: float, status: int = 200) -> list[Any]:
    """`n` door samples spread evenly over `seconds`."""
    return [
        drive.Sample("usage.report", "GET /usage/", True, status, ms, seconds * (i + 0.5) / n)
        for i in range(n)
    ]


def _step(index: int, concurrency: int, ms: float, *, started: float, seconds: float = 60.0) -> Any:
    step = drive.StepResult(
        index, concurrency, seconds, _samples(n=200, seconds=seconds, ms=ms), started_epoch=started
    )
    step.judge()
    return step


def _util(ts: float, cpu: float, total: int, active: int) -> dict[str, Any]:
    return {"ts": ts, "host_cpu": cpu, "pg_total": total, "pg_active": active, "pg_idle": 0}


def test_the_envelope_line_carries_utilization() -> None:
    steps = [
        _step(0, 1, 50.0, started=1000.0),
        _step(1, 2, 80.0, started=1060.0),
        _step(2, 4, 1500.0, started=1120.0),
    ]
    assert steps[2].verdict == "over"
    knee = {"step": 2, "concurrency": 4, "verdict": "found"}
    util = [_util(1010.0 + 5 * i, 10.0, 6, 1) for i in range(20)] + [
        _util(1120.0 + 5 * i, 60.0 + i, 12 + (i % 3), 3 + (i % 4)) for i in range(12)
    ]
    part, ok = drive.utilization_part(_summaries(steps), knee, util)
    assert ok
    assert part == "host_cpu=71.0,client_cpu=not_sampled,pg_total=14,pg_active=6"

    line = drive.envelope_line(
        steps=_summaries(steps),
        knee=knee,
        utilization=part,
        instrument="deploy/load/drive.py run --ladder 1,2,4",
        size="t4g.large",
        scale="prepared",
        topology="compose-one-host",
    )
    fields = dict(f.split("=", 1) for f in line.split(" | "))
    assert set(fields) >= {"metric", "instrument", "conditions", "utilization"}
    assert fields["utilization"] == part
    assert "knee=conc-4" in fields["metric"]
    assert "err=0.0" in fields["conditions"] and "throttled=0" in fields["conditions"]
    assert "topology=compose-one-host" in fields["conditions"]


def test_utilization_with_no_sample_in_the_knee_step_is_undetermined() -> None:
    steps = [_step(0, 1, 50.0, started=1000.0), _step(1, 2, 1500.0, started=1060.0)]
    knee = {"step": 1, "concurrency": 2, "verdict": "found"}
    part, ok = drive.utilization_part(_summaries(steps), knee, [_util(1010.0, 10.0, 6, 1)])
    assert not ok
    assert part.startswith("undetermined")


def test_the_utilization_file_reader_refuses_a_bad_line(tmp_path: Path) -> None:
    good = tmp_path / "u.jsonl"
    good.write_text('{"ts": 1.0, "host_cpu": 2.0, "pg_total": 3, "pg_active": 1}\n')
    assert drive.read_utilization(str(good))[0]["pg_total"] == 3
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    with pytest.raises(SystemExit) as exc:
        drive.read_utilization(str(bad))
    assert exc.value.code == 2


def _soak_samples(window_ms: list[float], per_window: int, *, errors_in_last: int = 0) -> list[Any]:
    out = []
    width = drive.SOAK_WINDOW_SECONDS
    for w, ms in enumerate(window_ms):
        for i in range(per_window):
            status = 500 if (w == len(window_ms) - 1 and i < errors_in_last) else 200
            at = w * width + width * (i + 0.5) / per_window
            out.append(drive.Sample("files.list", "GET /files/", True, status, ms, at))
    return out


def _soak_util(
    windows: int, pg_total: int, *, origin: float = 5000.0, outbox: list[int | None] | None = None
) -> list[dict[str, Any]]:
    width = drive.SOAK_WINDOW_SECONDS
    pending = outbox if outbox is not None else [3] * windows
    return [
        {
            **_util(origin + w * width + 5 * k, 40.0, pg_total, 2),
            "outbox_pending": pending[w],
            "pg_clients": pg_total,
            "pg_other": "",
            "pg_by_app": f"web@w:{pg_total}",
        }
        for w in range(windows)
        for k in range(int(width // 5))
    ]


def _judge(samples: list[Any], util: list[dict[str, Any]], **bounds: Any) -> Any:
    seconds = 3 * drive.SOAK_WINDOW_SECONDS
    return drive.judge_soak(samples, seconds, 5000.0, util, budget=18, outbox_slack=500, **bounds)


def test_soak_verdicts() -> None:
    steady = _judge(_soak_samples([100.0, 110.0, 120.0], 100), _soak_util(3, 15))
    assert steady.verdict == "steady", steady.reasons
    assert [w["pg_total"] for w in steady.windows] == [15, 15, 15]
    assert [w["outbox_pending"] for w in steady.windows] == [3, 3, 3]

    drifting = _judge(_soak_samples([100.0, 120.0, 151.0], 100), _soak_util(3, 15))
    assert drifting.verdict == "drifting", drifting.reasons

    over_budget = _judge(_soak_samples([100.0, 100.0, 100.0], 100), _soak_util(3, 19))
    assert over_budget.verdict == "unsteady"
    assert any("pg_clients=19" in r for r in over_budget.reasons)

    erroring = _judge(
        _soak_samples([100.0, 100.0, 100.0], 100, errors_in_last=2), _soak_util(3, 10)
    )
    assert erroring.verdict == "unsteady"

    thin = _judge(
        _soak_samples([100.0, 100.0, 100.0], drive.MIN_WINDOW_SAMPLES - 1), _soak_util(3, 10)
    )
    assert thin.verdict == "undetermined"

    unsampled = _judge(_soak_samples([100.0, 100.0, 100.0], 100), [])
    assert unsampled.verdict == "undetermined"


def test_a_soak_window_is_judged_at_the_tiers_half_percent() -> None:
    assert drive.SOAK_ERR_MAX == drive.BAR_ERR_PCT / 100 == 0.005
    one_in_125 = _soak_samples([100.0, 100.0, 100.0], 125, errors_in_last=1)
    at_the_tier = _judge(one_in_125, _soak_util(3, 10))
    assert at_the_tier.verdict == "unsteady", at_the_tier.reasons
    assert any(r.startswith("err: window 2: err=0.80% above 0.50%") for r in at_the_tier.reasons)
    looser = _judge(one_in_125, _soak_util(3, 10), err_bound=0.01)
    assert looser.verdict == "steady", looser.reasons


def test_a_growing_outbox_is_unsteady_past_one_relay_pass() -> None:
    samples = _soak_samples([100.0, 100.0, 100.0], 100)
    inside = _judge(samples, _soak_util(3, 10, outbox=[40, 300, 540]))
    assert inside.verdict == "steady", inside.reasons
    grew = _judge(samples, _soak_util(3, 10, outbox=[40, 300, 541]))
    assert grew.verdict == "unsteady"
    assert grew.reasons == [
        "outbox: outbox_pending grew 40 -> 541, above one relay pass (RECONCILE_BATCH=500)"
    ]
    unread = _judge(samples, _soak_util(3, 10, outbox=[3, None, 3]))
    assert unread.verdict == "undetermined"
    assert "outbox_pending" in unread.reasons[0]


def test_the_outbox_slack_is_read_from_the_relay() -> None:
    assert drive.declared_outbox_slack(REPO / "apps" / "events" / "activities.py") == 500


def test_the_soak_line_names_every_bound_and_the_broken_one() -> None:
    util = _soak_util(3, 19, outbox=[4, 9, 600])
    for n, u in enumerate(util):
        u["worker_backlog"] = 2
        u["idle_in_tx"] = n % 4
    result = _judge(_soak_samples([100.0, 100.0, 100.0], 100, errors_in_last=1), util)
    assert [w["idle_in_tx"] for w in result.windows] == [3, 3, 3]
    line = drive.soak_line(result, 16, 15, 18, 0.5)
    assert line == (
        "soak=unsteady concurrency=16 minutes=15 pool_budget=18 max_pg_clients=19 max_pg_total=19 "
        "max_idle_in_tx=3 outbox_pending=4/600 err_max=1.00 err_bound=0.5 max_worker_backlog=2 "
        "max_host_cpu=40.0 max_organs_cpu=- broken=err,outbox,pg_clients pg_by_app=web@w:19"
    )


def _pool_util(windows: list[list[tuple[int, int, str]]]) -> list[dict[str, Any]]:
    """Per window, the (pg_total, pg_clients, pg_other) samples, 40 s apart, from origin 5000."""
    width = drive.SOAK_WINDOW_SECONDS
    return [
        {
            **_util(5000.0 + w * width + 40 * k, 40.0, total, 2),
            "outbox_pending": 3,
            "pg_clients": clients,
            "pg_other": other,
            "pg_by_app": f"web@w:10,worker@a:{clients - 10}",
        }
        for w, these in enumerate(windows)
        for k, (total, clients, other) in enumerate(these)
    ]


def test_the_budget_is_judged_on_client_backends_and_the_rest_is_named() -> None:
    samples = _soak_samples([100.0, 100.0, 100.0], 100)
    quiet = [(26, 26, ""), (25, 25, "")]
    vacuum = [(26, 26, ""), (27, 26, "autovacuum_worker:1"), (26, 26, "")]
    steady = drive.judge_soak(
        samples,
        3 * drive.SOAK_WINDOW_SECONDS,
        5000.0,
        _pool_util([quiet, vacuum, quiet]),
        budget=26,
        outbox_slack=500,
    )
    assert steady.verdict == "steady", steady.reasons
    assert [w["pg_other"] for w in steady.windows] == [None, "autovacuum_worker:1", None]
    line = drive.soak_line(steady, 16, 15, 26, 0.5)
    assert "pool_budget=26 max_pg_clients=26 max_pg_total=27 pg_other=autovacuum_worker:1 " in line
    assert "broken=" not in line and "pg_by_app=" not in line

    quiet_line = drive.soak_line(
        drive.judge_soak(
            samples,
            3 * drive.SOAK_WINDOW_SECONDS,
            5000.0,
            _pool_util([quiet, quiet, quiet]),
            budget=26,
            outbox_slack=500,
        ),
        16,
        15,
        26,
        0.5,
    )
    assert "max_pg_clients=26 max_pg_total=26 max_idle_in_tx" in quiet_line

    over = [(26, 26, ""), (27, 27, ""), (26, 26, "")]
    unsteady = drive.judge_soak(
        samples,
        3 * drive.SOAK_WINDOW_SECONDS,
        5000.0,
        _pool_util([quiet, over, quiet]),
        budget=26,
        outbox_slack=500,
    )
    assert unsteady.verdict == "unsteady"
    assert unsteady.reasons == [
        "pg_clients: window 1: pg_clients=27 above the declared pool budget 26"
    ]
    over_line = drive.soak_line(unsteady, 16, 15, 26, 0.5)
    assert over_line.endswith(" broken=pg_clients pg_by_app=web@w:10,worker@a:17")
    assert "pg_other=" not in over_line

    older = [
        {k: v for k, v in u.items() if k not in ("pg_clients", "pg_other")}
        for u in _pool_util([quiet, vacuum, quiet])
    ]
    unread = drive.judge_soak(
        samples, 3 * drive.SOAK_WINDOW_SECONDS, 5000.0, older, budget=26, outbox_slack=500
    )
    assert unread.verdict == "undetermined"
    assert "pg_clients is read, never inferred" in unread.reasons[0]


def test_each_soak_window_names_both_boxes_cpu(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    width = drive.SOAK_WINDOW_SECONDS
    util = [{k: v for k, v in u.items() if k != "host_cpu"} for u in _soak_util(3, 10)]
    web = [
        {"ts": 5000.0 + w * width + 7 * k, "host_cpu": 50.0 + w * 10 + k}
        for w in range(3)
        for k in range(3)
    ]
    organs = [
        {"ts": 5000.0 + w * width + 11 * k, "organs_cpu": 80.0 + w + k}
        for w in range(3)
        for k in range(3)
    ]
    result = _judge(_soak_samples([100.0, 100.0, 100.0], 100), util + web + organs)
    assert result.verdict == "steady", result.reasons
    assert [w["host_cpu"] for w in result.windows] == [(51.0, 52.0), (61.0, 62.0), (71.0, 72.0)]
    assert [w["organs_cpu"] for w in result.windows] == [(81.0, 82.0), (82.0, 83.0), (83.0, 84.0)]
    line = drive.soak_line(result, 8, 15, 18, 0.5)
    assert line.endswith("max_host_cpu=72.0 max_organs_cpu=84.0")

    args = argparse.Namespace(
        activities=REPO / "apps" / "events" / "activities.py",
        err_bound=0.5,
        concurrency=8,
        minutes=15,
        out=str(tmp_path),
    )
    drive._print_soak(
        args,
        _soak_samples([100.0, 100.0, 100.0], 100),
        3 * width,
        5000.0,
        util + web + organs,
        18,
        "test-cpu",
    )
    printed = capsys.readouterr().out
    assert "organs_cpu=81.0/82.0" in printed and "host_cpu=71.0/72.0" in printed

    unsampled = _judge(_soak_samples([100.0, 100.0, 100.0], 100), util)
    assert [w["organs_cpu"] for w in unsampled.windows] == [None, None, None]
    assert drive.soak_line(unsampled, 8, 15, 18, 0.5).endswith("max_host_cpu=- max_organs_cpu=-")


def test_the_pool_budget_is_read_from_the_settings() -> None:
    base = REPO / "config" / "settings" / "base.py"
    assert drive.declared_pool_budget(base, {"web": 1, "worker": 2}) == 26
    assert drive.declared_pool_budget(base, {"web": 1, "worker": 1}) == 18


def test_the_processes_are_read_off_the_rendered_compose(tmp_path: Path) -> None:
    rendered = tmp_path / "compose.json"
    rendered.write_text(
        json.dumps({"services": {"web": {}, "worker": {"deploy": {"replicas": 2}}, "caddy": {}}})
    )
    assert drive.compose_processes(rendered) == {"web": 1, "worker": 2}
    assert drive.parse_processes("web=1,worker=2") == {"web": 1, "worker": 2}
    assert drive.format_processes({"web": 1, "worker": 2}) == "web=1,worker=2"


def test_429_is_counted_not_sampled() -> None:
    samples = _samples(n=150, seconds=60.0, ms=40.0) + _samples(
        n=60, seconds=60.0, ms=2.0, status=429
    )
    step = drive.StepResult(0, 1, 60.0, samples, started_epoch=0.0)
    step.judge()
    summary = step.summary()
    assert summary["throttled"] == 60
    assert summary["errors_door"] == 0
    assert summary["requests_door"] == 150
    assert summary["p50_ms"] == 40.0
    line = drive.envelope_line(
        steps=[summary],
        knee={"verdict": "not_reached"},
        utilization="not_sampled",
        instrument="deploy/load/drive.py run",
        size="s",
        scale="p",
        topology="t",
    )
    assert "throttled=60" in line


class _Paths:
    def __init__(self, cafile: str | None, capath: str | None) -> None:
        self.cafile = cafile
        self.capath = capath


def test_a_python_without_a_bundle_uses_certifi(tmp_path: Path) -> None:
    certifi = pytest.importorskip("certifi")
    bare = _Paths(None, str(tmp_path / "no-such-dir"))
    chosen, said = drive.resolve_ca_bundle("", bare)
    assert chosen == certifi.where()
    assert "certifi" in said

    named = tmp_path / "ca.pem"
    named.write_text("x")
    assert drive.resolve_ca_bundle(str(named), bare)[0] == str(named)

    real = ssl.get_default_verify_paths()
    if real.cafile:
        assert drive.resolve_ca_bundle("", real)[0] is None


def _summaries(steps: list[Any]) -> list[dict[str, Any]]:
    return [s.summary() for s in steps]


def test_the_line_carries_client_cpu(tmp_path: Path) -> None:
    steps = [_step(0, 1, 50.0, started=1000.0), _step(1, 2, 1500.0, started=1060.0)]
    knee = {"step": 1, "concurrency": 2, "verdict": "found"}
    web = [_util(1060.0 + 5 * i, 80.0, 12, 4) for i in range(12)]
    client = [{"ts": 1060.0 + 5 * i, "client_cpu": 20.0 + i} for i in range(12)]
    part, ok = drive.utilization_part(_summaries(steps), knee, web + client)
    assert ok
    assert part == "host_cpu=80.0,client_cpu=31.0,pg_total=12,pg_active=4"

    alone, _ = drive.utilization_part(_summaries(steps), knee, web)
    assert "client_cpu=not_sampled" in alone

    files = []
    for name, rows in (("web", web), ("client", client)):
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        files.append(str(path))
    assert drive.read_utilization_files(files) == web + client


def test_each_client_carries_its_own_credential_and_tenant(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    creds = tmp_path / "credentials.json"
    creds.write_text(
        json.dumps(
            [
                {"tenant": f"t{n % 4}", "token": f"token-{n}"} for n in range(8)
            ]  # pragma: allowlist secret
        )
    )
    credentials = drive.read_credentials(str(creds))
    assert len(credentials) == 8

    seen: list[tuple[str, str]] = []
    lock = threading.Lock()

    def answer(self: Any, method: str, path: str, **_: Any) -> Any:
        with lock:
            seen.append((self._auth["Authorization"], self._auth["X-Tenant"]))
        return drive.Reply(200, b"{}", 1.0)

    monkeypatch.setattr(drive.Doors, "api", answer)
    monkeypatch.setattr(
        drive, "MIX", (drive.Operation("usage.report", 1, "read", drive.op_usage_report, "x"),)
    )
    fixtures = {f"t{n}": drive.Fixtures(f"t{n}", "", "r", "tpl", ("f",)) for n in range(4)}
    args = argparse.Namespace(base_url="https://box.invalid")
    step = drive.run_step(0, 8, 1.0, args, credentials, fixtures, drive.Created())
    assert not step.faults, step.faults

    pairs = set(seen)
    assert {token for token, _ in pairs} == {f"Bearer token-{n}" for n in range(8)}
    assert len({tenant for _, tenant in pairs}) == 4
    for token, tenant in pairs:
        n = int(token.rsplit("-", 1)[1])
        assert tenant == f"t{n % 4}", "a client's token is never sent under another tenant"

    line = drive.envelope_line(
        steps=_summaries([step]),
        knee={"verdict": "not_reached"},
        utilization="not_sampled",
        instrument="deploy/load/drive.py run",
        size="c7g.large",
        scale="prepared",
        topology="web-box-organs-box-drive-off-box",
        client="t4g.medium",
        credentials=credentials,
    )
    conditions = dict(
        pair.split("=", 1) for pair in line.split(" | ")[2].split("=", 1)[1].split(",")
    )
    assert conditions["tenants"] == "4" and conditions["credentials"] == "8"
    assert conditions["client"] == "t4g.medium"
    assert conditions["topology"] == "web-box-organs-box-drive-off-box"


def _kinded(step_ms: dict[str, float], *, n: int = 200, seconds: float = 60.0) -> list[Any]:
    out = []
    for op, ms in step_ms.items():
        out += [drive.Sample(op, op, True, 200, ms, seconds * (i + 0.5) / n) for i in range(n)]
    return out


def test_the_bar_is_read_against_declared_bars() -> None:
    assert (drive.BAR_CLIENTS, drive.BAR_P95_MS, drive.BAR_ERR_PCT) == (8, 1000.0, 0.5)

    def ladder(ms_at_8: float, *, errors_at_8: int = 0) -> list[dict[str, Any]]:
        steps = []
        for i, conc in enumerate((1, 2, 4, 8)):
            ms = ms_at_8 if conc == 8 else 100.0
            samples = _kinded({"usage.report": ms, "comms.send": ms * 2})
            if conc == 8 and errors_at_8:
                samples += [
                    drive.Sample("comms.send", "x", True, 500, 10.0, 30.0)
                    for _ in range(errors_at_8)
                ]
            step = drive.StepResult(i, conc, 60.0, samples, started_epoch=1000.0 + 60 * i)
            step.judge()
            steps.append(step.summary())
        return steps

    shape = {"topology": drive.BAR_TOPOLOGY, "credentials": drive.BAR_MIN_CREDENTIALS}
    good = ladder(300.0)
    assert good[0]["p95_read_ms"] == 100.0 and good[0]["p95_write_ms"] == 200.0
    assert drive.judge_bar(good, **shape) == "met"

    slow = drive.judge_bar(ladder(600.0), **shape)
    assert slow.startswith("unmet(") and "p95_ms=1200" in slow and "conc-8" in slow

    erring = drive.judge_bar(ladder(300.0, errors_at_8=10), **shape)
    assert erring.startswith("unmet(") and "err=" in erring and "conc-8" in erring

    short = drive.judge_bar(good[:3], **shape)
    assert short.startswith("unmet(") and "conc-8" in short

    line = drive.envelope_line(
        steps=good,
        knee={"verdict": "not_reached"},
        utilization="not_sampled",
        instrument="deploy/load/drive.py run",
        size="s",
        scale="p",
        topology=drive.BAR_TOPOLOGY,
        credentials=[
            drive.Credential(tenant=f"t{n % 4}", token="") for n in range(drive.BAR_MIN_CREDENTIALS)
        ],
    )
    parts = dict(f.split("=", 1) for f in line.split(" | "))
    assert parts["bar"] == "met"
    assert "p95_read_ms=300" in parts["metric"] and "p95_write_ms=600" in parts["metric"]


def test_the_baseline_census_refuses_a_principal_over_its_bound(tmp_path: Path) -> None:
    clean = "app|app|6|1|5|3\ntemporal|temporal|12|2|10|1\nzitadel|zitadel|7|0|7|9\n"
    ok, lines = drive.judge_baseline(clean, app_db="app", budget=18)
    assert ok, lines

    over = clean.replace("zitadel|zitadel|7", "zitadel|zitadel|23")
    ok, lines = drive.judge_baseline(over, app_db="app", budget=18)
    assert not ok and any("zitadel" in line and "23" in line for line in lines)

    stranger = clean + "mystery|someone|1|0|1|0\n"
    ok, lines = drive.judge_baseline(stranger, app_db="app", budget=18)
    assert not ok and any("mystery" in line for line in lines)


def test_resolve_dials_the_address_and_keeps_the_name(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            seen.append(self.headers["Host"])
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: Any) -> None:
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setitem(drive.RESOLVE, "minio.invalid", "127.0.0.1")
        port = server.server_address[1]
        reply = drive.Pool(5.0).call("GET", f"http://minio.invalid:{port}/bucket/key")
    finally:
        server.shutdown()
    assert reply.status == 200, reply.error
    assert seen == [f"minio.invalid:{port}"]


def test_judge_rebuilds_the_lines_from_every_box(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    steps = [_step(0, 1, 50.0, started=1000.0), _step(1, 8, 300.0, started=1060.0)]
    (out / "drive-20261021T000000Z.json").write_text(
        json.dumps(
            {
                "steps": _summaries(steps),
                "knee": {"verdict": "not_reached"},
                "instrument": "deploy/load/drive.py run --ladder 1,8",
                "conditions": {
                    "size": "c7g.large",
                    "scale": "prepared",
                    "topology": "t",
                    "client": "c",
                },
                "clients": {"credentials": 8, "tenants": ["a", "b", "c", "d"]},
            }
        )
    )
    web = tmp_path / "web.jsonl"
    web.write_text(
        "".join(json.dumps({"ts": 1060.0 + i, "host_cpu": 70.0}) + "\n" for i in range(5))
    )
    organs = tmp_path / "organs.jsonl"
    organs.write_text(
        "".join(
            json.dumps(_util(1060.0 + i, 30.0, 9, 2) | {"organs_cpu": 30.0}) + "\n"
            for i in range(5)
        )
    )
    args = drive.build_parser().parse_args(
        ["judge", "--out", str(out), "--utilization", str(web), "--utilization", str(organs)]
    )
    assert drive.command_judge(args) == 0


def test_a_throttled_client_waits_as_told(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[float] = []

    def throttled(self: Any, method: str, path: str, **_: Any) -> Any:
        calls.append(time.perf_counter())
        self.told_to_wait = 0.25
        return drive.Reply(429, b"", 1.0, retry_after=0.25)

    monkeypatch.setattr(drive.Doors, "api", throttled)
    monkeypatch.setattr(
        drive, "MIX", (drive.Operation("usage.report", 1, "read", drive.op_usage_report, "x"),)
    )
    creds = [drive.Credential(tenant="t", token="k")]  # noqa: S106 — a fake API token the drive presents to a stub
    fixtures = {"t": drive.Fixtures("t", "", "r", "tpl", ("f",))}
    args = argparse.Namespace(base_url="https://box.invalid")
    step = drive.run_step(0, 1, 1.0, args, creds, fixtures, drive.Created())
    assert step.throttled == len(calls)
    assert 3 <= len(calls) <= 5, "a 429 is waited out, never spun on"


def test_clients_sharing_a_credential_share_its_pace(monkeypatch: pytest.MonkeyPatch) -> None:
    assert drive.declared_auth_rate(REPO / "config" / "settings" / "base.py") == 10.0
    calls: list[str] = []

    def answer(self: Any, method: str, path: str, **_: Any) -> Any:
        calls.append(path)
        return drive.Reply(200, b"{}", 1.0)

    monkeypatch.setattr(
        drive.Pool, "call", lambda self, method, url, **_: answer(self, method, url)
    )
    monkeypatch.setattr(drive, "PACE_PER_SECOND", [20.0])
    monkeypatch.setattr(drive, "PACERS", {})
    monkeypatch.setattr(
        drive, "MIX", (drive.Operation("usage.report", 1, "read", drive.op_usage_report, "x"),)
    )
    creds = [drive.Credential(tenant="t", token="one")]  # noqa: S106 — a fake API token the drive presents to a stub
    fixtures = {"t": drive.Fixtures("t", "", "r", "tpl", ("f",))}
    args = argparse.Namespace(base_url="https://box.invalid")
    drive.run_step(0, 2, 1.0, args, creds, fixtures, drive.Created())
    assert 15 <= len(calls) <= 23, (
        f"two clients on one credential made {len(calls)} calls in 1 s at 20/s"
    )


def test_the_envelope_line_names_the_pacer_beside_throttled() -> None:
    step = drive.StepResult(0, 1, 60.0, _kinded({"usage.report": 100.0}), started_epoch=1000.0)
    step.judge()

    def conditions(**pace: float) -> dict[str, str]:
        line = drive.envelope_line(
            steps=[step.summary()],
            knee={"verdict": "not_reached"},
            utilization="not_sampled",
            instrument="deploy/load/drive.py run",
            size="s",
            scale="p",
            topology="t",
            **pace,
        )
        return dict(pair.split("=", 1) for pair in line.split(" | ")[2][11:].split(","))

    paced = conditions(pace=9.5)
    assert paced["pacer"] == "9.5/s" and "throttled" in paced
    assert conditions()["pacer"] == "off"


def _fields(line: str) -> dict[str, str]:
    return dict(f.split("=", 1) for f in line.split(" | "))


def _ladder_line(*, credentials: int, topology: str, top: int = 8, pace: float = 0.0) -> str:
    steps = [_step(i, c, 100.0, started=1000.0 + 60 * i) for i, c in enumerate((1, 2, 4, 8))]
    line: str = drive.envelope_line(
        steps=[s for s in _summaries(steps) if s["concurrency"] <= top],
        knee={"verdict": "not_reached"},
        utilization="not_sampled",
        instrument="deploy/load/drive.py run --ladder 1,2,4,8",
        size="s",
        scale="p",
        topology=topology,
        credentials=[drive.Credential(tenant=f"t{n % 4}", token="") for n in range(credentials)],
        pace=pace,
    )
    return line


def test_the_instrument_string_carries_the_pacer() -> None:
    paced = _fields(_ladder_line(credentials=8, topology=drive.BAR_TOPOLOGY, pace=9.5))
    unpaced = _fields(_ladder_line(credentials=8, topology=drive.BAR_TOPOLOGY))
    assert paced["instrument"].endswith(" pacer=9.5/s"), paced["instrument"]
    assert unpaced["instrument"].endswith(" pacer=off"), unpaced["instrument"]
    assert paced["instrument"] != unpaced["instrument"]
    assert drive.paced_instrument(paced["instrument"], "9.5/s") == paced["instrument"]


def test_a_one_credential_ladder_wears_the_invalid_mark(tmp_path: Path) -> None:
    mark = "validity=INVALID: one credential above one client"
    assert mark in _ladder_line(credentials=1, topology=drive.BAR_TOPOLOGY)
    assert mark not in _ladder_line(credentials=1, topology=drive.BAR_TOPOLOGY, top=1)
    assert mark not in _ladder_line(credentials=8, topology=drive.BAR_TOPOLOGY)

    out = tmp_path / "out"
    out.mkdir()
    steps = [_step(0, 1, 50.0, started=1000.0), _step(1, 16, 300.0, started=1060.0)]
    (out / "drive-20261023T000000Z.json").write_text(
        json.dumps(
            {
                "steps": _summaries(steps),
                "knee": {"verdict": "not_reached"},
                "instrument": "deploy/load/drive.py run --ladder 1,16",
                "conditions": {
                    "size": "t4g.large",
                    "scale": "prepared",
                    "topology": "compose-one-host-drive-on-box",
                    "client": "",
                },
                "clients": {"credentials": 1, "tenants": ["a"]},
                "credential_pace_per_second": 9.5,
            }
        )
    )
    web = tmp_path / "web.jsonl"
    web.write_text("".join(json.dumps(_util(1060.0 + i, 70.0, 9, 2)) + "\n" for i in range(5)))
    printed = tmp_path / "judged.txt"
    with printed.open("w") as sink:
        old, sys.stdout = sys.stdout, sink
        try:
            rc = drive.main(["judge", "--out", str(out), "--utilization", str(web)])
        finally:
            sys.stdout = old
    text = printed.read_text()
    assert rc == 0, text
    assert mark in text and "bar=met" not in text, text


def test_judge_bar_reads_the_topology_and_the_credential_count() -> None:
    steps = [_step(i, c, 100.0, started=1000.0 + 60 * i) for i, c in enumerate((1, 2, 4, 8))]
    good = _summaries(steps)
    assert drive.judge_bar(good, topology=drive.BAR_TOPOLOGY, credentials=8) == "met"
    one_box = drive.judge_bar(good, topology="compose-one-host-drive-on-box", credentials=1)
    assert one_box.startswith("unjudged(") and "topology=" in one_box and "credentials=1" in one_box
    one_cred = drive.judge_bar(good, topology=drive.BAR_TOPOLOGY, credentials=1)
    assert one_cred.startswith("unjudged(") and "topology=" not in one_cred
    line = _ladder_line(credentials=1, topology="compose-one-host-drive-on-box", pace=9.5)
    assert _fields(line)["bar"].startswith("unjudged("), line


def _recorded(knee: str, conditions: str, bar: str = "met") -> str:
    head = f"metric=p95_ms=1000 {knee} | instrument=deploy/load/drive.py run --ladder 1,2 --seed 1"
    tail = f"utilization=host_cpu=1 | bar={bar}"
    return f"  - `{head} | conditions=size=s,scale=p,{conditions} | {tail}`"


_PROD = "topology=web-box-organs-box-drive-off-box"
_OLD = _recorded(
    "knee=conc-16", f"concurrency=16,err=0.0,throttled=0,{_PROD},tenants=4,credentials=8"
)
_ONE_BOX = _recorded(
    "knee=not_reached",
    "concurrency=32,err=0.0,throttled=0,pacer=9.5/s,"
    "topology=compose-one-host-drive-on-box,tenants=1,credentials=1",
)
_PAIRED = _recorded(
    "knee=conc-32",
    f"concurrency=32,err=2.83,throttled=0,pacer=9.5/s,{_PROD},tenants=4,credentials=8",
)
_EXAMPLE = (
    "`metric=p95_ms=2000 knee=conc-8 | instrument=deploy/load/drive.py --size A"
    " | conditions=size=t,scale=A,concurrency=8,err=0.0,pacer=9.5/s,credentials=1"
    " | utilization=host_cpu=92.7`"
)
_CHAPTER = "\n".join(
    [
        "## 1 · The envelope",
        _EXAMPLE,
        "## 9 · Recorded knees",
        "- 2026-10-22 · old",
        _OLD,
        "  - `soak=unsteady concurrency=8 minutes=30`",
        "- 2026-10-23 · one box",
        _ONE_BOX,
        "- 2026-10-23 · production",
        _PAIRED,
        "<!-- recorded-knees end -->",
        "## 10 · Shapes",
        _EXAMPLE,
        "",
    ]
)


def test_restamp_rewrites_the_paced_lines_and_keeps_the_old_era(tmp_path: Path) -> None:
    chapter = tmp_path / "capacity.md"
    chapter.write_text(_CHAPTER)
    assert drive.main(["judge", "--restamp", str(chapter)]) == 0
    before, after = _CHAPTER.splitlines(), chapter.read_text().splitlines()
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert changed == [before.index(_ONE_BOX), before.index(_PAIRED)], after

    one_box = _fields(after[changed[0]].strip()[3:-1])
    assert one_box["instrument"].endswith(" pacer=9.5/s")
    assert one_box["bar"].startswith("unjudged(")
    assert one_box["validity"] == "INVALID: one credential above one client"
    paired = _fields(after[changed[1]].strip()[3:-1])
    assert paired["instrument"].endswith(" pacer=9.5/s") and paired["bar"] == "met"
    assert "validity" not in paired

    assert drive.main(["judge", "--restamp", str(chapter)]) == 0
    assert chapter.read_text().splitlines() == after, "a second restamp changed a line"
