from quant.cli import main
from quant.execution.gateways.manual import ManualGateway, format_orders


def test_cli_help():
    assert main([]) == 0


def test_data_probe_dispatch(monkeypatch):
    seen=[]
    monkeypatch.setattr('quant.cli._delegate',lambda module,argv:seen.append((module,argv)) or 0)
    assert main(['data','probe-tushare','--as-of','2026-11-05'])==0
    assert seen==[('quant.data.probe_tushare',['--as-of','2026-11-05'])]
    assert main(['data','structured-events','--resume'])==0
    assert seen[-1]==('quant.data.structured_events',['--resume'])


def test_cli_gpu_check_cpu(monkeypatch):
    monkeypatch.setattr(
        "quant.core.gpu.detect_device",
        lambda refresh=False: type("R", (), {"to_dict": lambda self: {"resolved": "cpu"}})(),
    )
    monkeypatch.setattr("quant.core.gpu.main", lambda argv=None: 0)
    assert main(["gpu-check"]) == 0


def test_manual_gateway_dry_run(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "quant.execution.gateways.manual.send",
        lambda title, body: [type("S", (), {"ok": True, "channel": "outbox"})()],
    )
    result = ManualGateway().notify_orders(title="orders", body="buy 1")
    assert result["gateway"] == "manual"
    assert result["submitted"] is False
    assert result["notified"] is True
    orders = tmp_path / "orders.csv"
    orders.write_text("symbol,side,qty\n000001.SZ,BUY,100\n", encoding="utf-8")
    text = format_orders(orders)
    assert "000001.SZ" in text
