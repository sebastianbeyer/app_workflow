# DestinE download + regrid rules.
#
# Provides:
#   - source_resolution_for(grid)     : threshold mapping target grid → native HEALPix tier
#   - native_path(...)                : path to a downloaded GRIB chunk
#   - regridded_path(...)             : path to a regridded netCDF chunk
#   - rule download_destine           : one monthly GRIB via polytope (native HEALPix)
#   - rule regrid_destine             : HEALPix GRIB → regular lat/lon netCDF


def source_resolution_for(grid: str) -> str:
    """Pick HEALPix source: 'high' (~10 km) for any target finer than 50 km, else 'standard' (~50 km)."""
    deg = float(grid.removeprefix("g"))
    return "high" if deg < 0.5 else "standard"


def native_path(experiment, source_resolution, variable, frequency, yyyymm):
    return (
        f"resources/data/destine/{experiment}/native/{source_resolution}/"
        f"{variable}/{frequency}/{yyyymm}.grib"
    )


def regridded_path(experiment, grid, method, area, variable, frequency, yyyymm):
    return (
        f"resources/data/destine/{experiment}/{grid}/{method}/{area}/"
        f"{variable}/{frequency}/{yyyymm}.nc"
    )


rule download_destine:
    output:
        temp("resources/data/destine/{experiment}/native/{source_resolution}/{variable}/{frequency}/{yyyymm}.grib")
    params:
        destine_config=DESTINE_CONFIG,
        year=lambda wc: wc.yyyymm[:4],
        month=lambda wc: wc.yyyymm[4:6],
        skip_tls_flag=("--skip-tls" if SKIP_TLS else ""),
    resources:
        polytope_api=1,
    retries: 3
    shell:
        """
        pixi run python workflow/scripts/download/destine.py \
            --destine-config {params.destine_config} \
            --experiment {wildcards.experiment} \
            --variable {wildcards.variable} \
            --frequency {wildcards.frequency} \
            --year {params.year} \
            --month {params.month} \
            --source-resolution {wildcards.source_resolution} \
            --output {output} \
            {params.skip_tls_flag}
        """


rule regrid_destine:
    input:
        lambda wc: native_path(
            wc.experiment, source_resolution_for(wc.grid),
            wc.variable, wc.frequency, wc.yyyymm,
        )
    output:
        "resources/data/destine/{experiment}/{grid}/{method}/{area}/{variable}/{frequency}/{yyyymm}.nc"
    params:
        defaults_config=DEFAULTS_CONFIG,
        grid_deg=lambda wc: wc.grid.removeprefix("g"),
        batch_size=REGRID_BATCH_SIZE,
    threads: 1
    resources:
        slurm_partition="small",     # shared CPU partition on LUMI-C
        mem_mb=24000,                # 
        runtime=60,                  # minutes; observed ~7 min, leave room
    retries: 3
    shell:
        """
        OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 \
        pixi run python workflow/scripts/regrid/healpix_to_latlon.py \
            --input {input} \
            --output {output} \
            --grid {params.grid_deg} \
            --method {wildcards.method} \
            --area {wildcards.area} \
            --defaults-config {params.defaults_config} \
            --batch-size {params.batch_size}
        """
