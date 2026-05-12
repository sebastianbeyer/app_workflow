"""Download a single monthly chunk of DestinE data via polytope.

Data is fetched on the model's native HEALPix grid (no `grid`/`area` keys in
the request) and written as raw GRIB. Regridding happens in a separate rule.
"""

import argparse
import calendar
from datetime import date
from pathlib import Path

import earthkit.data
import yaml


def log(msg: str, level: str = "INFO"):
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\033[94m[{ts}] {level}: {msg}\033[0m", flush=True)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args():
    p = argparse.ArgumentParser(description="Download one monthly DestinE chunk as GRIB on native HEALPix.")
    p.add_argument("--destine-config", required=True)
    p.add_argument("--experiment", required=True, help="Experiment key from destine.yaml")
    p.add_argument("--variable", required=True, help="Variable key from destine.yaml")
    p.add_argument("--frequency", required=True, choices=["hourly", "daily", "monthly"])
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int, required=True, choices=range(1, 13))
    p.add_argument("--source-resolution", required=True, choices=["standard", "high"],
                   help="HEALPix source resolution; overrides 'resolution' from destine.yaml")
    p.add_argument("--output", required=True, help="Path to output .grib file")
    p.add_argument("--skip-tls", action="store_true",
                   help="Skip TLS certificate verification (use when server cert is expired)")
    return p.parse_args()


def build_request(experiment_cfg, variable_cfg, frequency, year, month):
    """Build a polytope request for a single (year, month) chunk on the native grid."""
    request = {
        "class": experiment_cfg["class"],
        "dataset": experiment_cfg["dataset"],
        "type": experiment_cfg["type"],
        "expver": experiment_cfg["expver"],
        "generation": experiment_cfg["generation"],
        "realization": experiment_cfg["realization"],
        "activity": experiment_cfg["activity"],
        "experiment": experiment_cfg["experiment"],
        "model": experiment_cfg["model"],
        "resolution": experiment_cfg["resolution"],
        "param": variable_cfg["param"],
        "levtype": variable_cfg["levtype"],
    }
    # Variable-specific extras (e.g. fixed levelist) — skip config-only keys.
    config_only = {"param", "levtype", "frequencies", "name"}
    for k, v in variable_cfg.items():
        if k not in config_only:
            request[k] = v

    if frequency == "monthly":
        # Monthly averages live in stream 'clmn' and are addressed by year/month.
        request["stream"] = "clmn"
        request["year"] = str(year)
        request["month"] = str(month)
    else:
        # Hourly / daily live in stream 'clte', addressed by date range + time.
        last_day = calendar.monthrange(year, month)[1]
        d0 = date(year, month, 1)
        d1 = date(year, month, last_day)
        request["stream"] = "clte"
        request["date"] = f"{d0:%Y%m%d}/to/{d1:%Y%m%d}"
        if frequency == "hourly":
            request["time"] = "/".join(f"{h:02d}" for h in range(24))
        else:  # daily
            request["time"] = "00"

    return request


def disable_ssl_verification():
    """Globally disable SSL certificate verification for outgoing HTTPS calls."""
    import ssl
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    old_session_init = requests.Session.__init__

    def patched_session_init(self, *args, **kwargs):
        old_session_init(self, *args, **kwargs)
        self.verify = False

    requests.Session.__init__ = patched_session_init

    old_send = requests.adapters.HTTPAdapter.send

    def patched_send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        return old_send(self, request, stream=stream, timeout=timeout, verify=False, cert=cert, proxies=proxies)

    requests.adapters.HTTPAdapter.send = patched_send

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    old_pool_init = urllib3.HTTPSConnectionPool.__init__

    def patched_pool_init(self, *args, **kwargs):
        kwargs["cert_reqs"] = "CERT_NONE"
        kwargs.setdefault("ssl_context", ctx)
        old_pool_init(self, *args, **kwargs)

    urllib3.HTTPSConnectionPool.__init__ = patched_pool_init
    log("TLS certificate verification disabled")


def main():
    args = parse_args()

    if args.skip_tls:
        disable_ssl_verification()

    cfg = load_yaml(args.destine_config)
    experiments = cfg.get("experiments", {})
    variables = cfg.get("variables", {})

    if args.experiment not in experiments:
        raise KeyError(f"Experiment '{args.experiment}' not in {args.destine_config}")
    if args.variable not in variables:
        raise KeyError(f"Variable '{args.variable}' not in {args.destine_config}")

    experiment_cfg = dict(experiments[args.experiment])
    experiment_cfg["resolution"] = args.source_resolution
    variable_cfg = variables[args.variable]

    allowed = variable_cfg.get("frequencies", [])
    if allowed and args.frequency not in allowed:
        log(f"Warning: frequency '{args.frequency}' not in declared frequencies "
            f"{allowed} for variable '{args.variable}' — sending anyway.", level="WARN")

    request = build_request(experiment_cfg, variable_cfg, args.frequency, args.year, args.month)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Polytope request: {request}")
    kwargs = {"address": experiment_cfg["address"], "stream": False}
    if args.skip_tls:
        kwargs["skip_tls"] = True

    result = earthkit.data.from_source(
        "polytope", "destination-earth", request, **kwargs,
    )

    log(f"Writing GRIB to {output_path}")
    result.save(str(output_path))
    log("Done")


if __name__ == "__main__":
    main()
