# Sequential hydroland integration. Each month depends on the previous
# month's sentinel plus that month's regridded forcing. The recursion floor
# is the experiment's `startdate` in config/destine.yaml.
#
# To run experiment "X" through month YYYYMM, request
#     results/hydroland/X/YYYYMM.done
# Snakemake walks back through every preceding month down to the startdate.


def prev_yyyymm(s: str) -> str:
    """Return the YYYYMM string for the month preceding `s`."""
    y, m = int(s[:4]), int(s[4:])
    m -= 1
    if m == 0:
        y -= 1
        m = 12
    return f"{y:04d}{m:02d}"


def experiment_startdate(experiment: str) -> str:
    """Return YYYYMM start month from destine.yaml; raise if missing."""
    exp = _destine.get("experiments", {}).get(experiment, {})
    start = exp.get("startdate")
    if not start:
        raise KeyError(
            f"Experiment '{experiment}' has no 'startdate' in {DESTINE_CONFIG}. "
            "Add a `startdate: YYYYMM` line to that experiment block."
        )
    return start


def hydroland_prev_state(wc):
    """Previous month's sentinel, or the init sentinel for the experiment's start month."""
    start = experiment_startdate(wc.experiment)
    if wc.yyyymm < start:
        raise ValueError(
            f"Requested hydroland month {wc.yyyymm} is before the "
            f"'{wc.experiment}' startdate {start} (from {DESTINE_CONFIG})."
        )
    if wc.yyyymm == start:
        return f"results/hydroland/{wc.experiment}/init.done"
    return f"results/hydroland/{wc.experiment}/{prev_yyyymm(wc.yyyymm)}.done"


def hydroland_forcing(wc):
    """Regridded netCDFs that this month's hydroland step reads."""
    cfg = HYDROLAND_EXPERIMENTS[wc.experiment]
    f = cfg["forcing"]
    return [
        regridded_path(
            wc.experiment, f["grid"], f["method"], f["area"],
            var, f["frequency"], wc.yyyymm,
        )
        for var in f["variables"]
    ]


rule hydroland_init:
    output:
        "results/hydroland/{experiment}/init.done"
    shell:
        "bash workflow/scripts/hydroland/init.sh {wildcards.experiment} {output}"


rule hydroland_step:
    input:
        prev=hydroland_prev_state,
        forcing=hydroland_forcing,
    output:
        "results/hydroland/{experiment}/{yyyymm}.done"
    shell:
        "bash workflow/scripts/hydroland/run_step.sh "
        "{wildcards.experiment} {wildcards.yyyymm} {input.prev} {output} {input.forcing}"
