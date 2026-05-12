"""Regrid a HEALPix GRIB chunk to a regular lat/lon netCDF (single precision).

Regridding is streamed in time-batches and written incrementally so peak
memory is bounded by `--batch-size` fields rather than the whole input.
"""

import argparse
from datetime import datetime
from pathlib import Path

import earthkit.data
import netCDF4
import numpy as np
import xarray as xr
import yaml

# Earthkit-regrid's default "user" cache policy registers every regrid-matrix
# lookup in a shared SQLite DB at ~/.cache/earthkit-regrid/. Each interpolate()
# call writes a row — and on a shared/networked filesystem (e.g. Lustre) parallel
# jobs race for the DB lock and fail with `database is locked` (manifesting as
# a misleading "Could not download matrix file" error). Switch to "temporary":
# each process gets its own private cache dir + SQLite, so within the process
# the matrix is fetched once and reused, but no two processes ever touch the
# same DB file. ("off" doesn't help because that path uses unique filenames
# per call and re-downloads the matrix every batch.)
from earthkit.regrid.utils.caching import SETTINGS as _EK_REGRID_SETTINGS
_EK_REGRID_SETTINGS["cache-policy"] = "temporary"

from earthkit.regrid import interpolate  # noqa: E402  (must follow SETTINGS tweak)


_NETCDF_SAFE_TYPES = (str, int, float, bytes, list, tuple, np.ndarray, np.number)


def _netcdf_safe_attrs(attrs):
    """Drop attribute values netCDF4 cannot serialise (e.g. earthkit's `_earthkit` dict)."""
    clean = {}
    for k, v in attrs.items():
        if hasattr(v, "item"):
            try:
                v = v.item()
            except (ValueError, AttributeError):
                pass
        if isinstance(v, _NETCDF_SAFE_TYPES):
            clean[k] = v
    return clean


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\033[94m[{ts}] {level}: {msg}\033[0m", flush=True)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_args():
    p = argparse.ArgumentParser(description="Regrid HEALPix GRIB to regular lat/lon netCDF.")
    p.add_argument("--input", required=True, help="Input GRIB file (native HEALPix)")
    p.add_argument("--output", required=True, help="Output netCDF file")
    p.add_argument("--grid", required=True, type=float,
                   help="Target grid spacing in degrees (e.g. 0.25)")
    p.add_argument("--method", required=True,
                   help="Regrid method key from defaults.yaml (e.g. nearest, linear, gridbox)")
    p.add_argument("--area", required=True,
                   help="Area cutout key from defaults.yaml (e.g. global, land)")
    p.add_argument("--defaults-config", required=True)
    p.add_argument("--batch-size", type=int, default=24,
                   help="Fields regridded per batch. Caps peak RAM. Default: 24 (one day hourly).")
    return p.parse_args()


def _datetime_coord(ds):
    """Return name of a datetime coordinate in `ds`, or raise."""
    for c in ds.coords:
        if np.issubdtype(ds[c].dtype, np.datetime64):
            return c
    raise RuntimeError("No datetime coordinate found in regridded output")


def _build_area_cropper(area_str):
    """Return a function ds -> cropped ds for the given 'N/W/S/E' string, or None."""
    if not area_str:
        return None
    parts = area_str.split("/")
    if len(parts) != 4:
        raise ValueError(f"area must be 'N/W/S/E', got '{area_str}'")
    n, w, s, e = (float(x) for x in parts)
    full_lon = (e - w) >= 360.0 - 1e-9
    w_mod = w % 360.0
    e_mod = e % 360.0

    def crop(ds, lat_name="latitude", lon_name="longitude"):
        lat_vals = ds[lat_name].values
        if lat_vals[0] > lat_vals[-1]:
            ds = ds.sel({lat_name: slice(n, s)})
        else:
            ds = ds.sel({lat_name: slice(s, n)})
        if full_lon:
            return ds
        if w_mod <= e_mod:
            return ds.sel({lon_name: slice(w_mod, e_mod)})
        return xr.concat(
            [ds.sel({lon_name: slice(w_mod, 360.0)}),
             ds.sel({lon_name: slice(0.0, e_mod)})],
            dim=lon_name,
        )

    return crop


def main():
    args = parse_args()

    defaults = load_yaml(args.defaults_config)
    method_map = defaults.get("regrid", {}).get("methods", {})
    if args.method not in method_map:
        raise KeyError(
            f"Unknown regrid method '{args.method}'. Known: {sorted(method_map)}. "
            f"Add to {args.defaults_config}."
        )
    ek_method = method_map[args.method]

    areas_map = defaults.get("regrid", {}).get("areas", {})
    if args.area not in areas_map:
        raise KeyError(
            f"Unknown area '{args.area}'. Known: {sorted(areas_map)}. "
            f"Add to {args.defaults_config}."
        )
    area_str = areas_map[args.area]  # None for 'global' / no cropping

    # earthkit-regrid only ships matrices for full global grids, so we always
    # regrid global and apply the bbox afterwards via xarray.
    out_grid = {"grid": [args.grid, args.grid]}
    cropper = _build_area_cropper(area_str)
    if cropper:
        log(f"Cropping to area '{args.area}' = {area_str} (N/W/S/E) after regrid")

    nc_cfg = defaults.get("netcdf", {})
    float_dtype = nc_cfg.get("float_dtype", "float32")
    comp = nc_cfg.get("compression", {})
    zlib_on = comp.get("zlib", True)
    complevel = comp.get("complevel", 4)
    shuffle = comp.get("shuffle", True)

    src = earthkit.data.from_source("file", args.input)
    n_fields = len(src)
    n_batches = (n_fields + args.batch_size - 1) // args.batch_size
    log(f"Loaded {n_fields} fields, will regrid in {n_batches} batches of up to {args.batch_size}")
    log(f"Target grid {out_grid}, method '{ek_method}'")

    # First batch: regrid to learn output schema (grid, time/var coord names).
    first_end = min(args.batch_size, n_fields)
    log(f"Regridding batch 1/{n_batches} (fields [0:{first_end}])...")
    first_ds = interpolate(src[:first_end], out_grid=out_grid, method=ek_method).to_xarray()
    if cropper:
        first_ds = cropper(first_ds)
    first_ds.attrs = _netcdf_safe_attrs(first_ds.attrs)
    for v in first_ds.variables:
        first_ds[v].attrs = _netcdf_safe_attrs(first_ds[v].attrs)

    data_vars = list(first_ds.data_vars)
    if len(data_vars) != 1:
        raise NotImplementedError(
            f"Streaming regrid currently supports single-variable GRIBs, got {data_vars}"
        )
    var_name = data_vars[0]
    time_name = _datetime_coord(first_ds)
    lat = first_ds["latitude"].values
    lon = first_ds["longitude"].values
    ny, nx = len(lat), len(lon)
    log(f"Output schema: var='{var_name}', time='{time_name}', lat={ny}, lon={nx}")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    nc_out = netCDF4.Dataset(output_path, "w", format="NETCDF4")
    try:
        nc_out.createDimension("time", None)
        nc_out.createDimension("latitude", ny)
        nc_out.createDimension("longitude", nx)

        lat_v = nc_out.createVariable("latitude", "f8", ("latitude",))
        lon_v = nc_out.createVariable("longitude", "f8", ("longitude",))
        lat_v[:] = lat
        lon_v[:] = lon
        for attr_name in ("units", "long_name", "standard_name", "axis"):
            for src_da, dst in [(first_ds["latitude"], lat_v), (first_ds["longitude"], lon_v)]:
                val = src_da.attrs.get(attr_name)
                if val is not None:
                    setattr(dst, attr_name, val)

        first_time = (
            np.datetime64(first_ds[time_name].values[0], "s")
            .astype("datetime64[us]").astype(object)
        )
        time_units = f"hours since {first_time.strftime('%Y-%m-%d %H:%M:%S')}"
        time_v = nc_out.createVariable("time", "f8", ("time",))
        time_v.units = time_units
        time_v.calendar = "proleptic_gregorian"
        time_v.standard_name = "time"
        time_v.long_name = "time"

        # Chunk time at the batch boundary so each batch becomes one disk chunk.
        chunksizes = (min(args.batch_size, n_fields), ny, nx)
        data_v = nc_out.createVariable(
            var_name, float_dtype, ("time", "latitude", "longitude"),
            zlib=zlib_on, complevel=complevel, shuffle=shuffle,
            chunksizes=chunksizes,
        )
        for k, v in _netcdf_safe_attrs(first_ds[var_name].attrs).items():
            setattr(data_v, k, v)
        for k, v in first_ds.attrs.items():
            setattr(nc_out, k, v)

        def _write_batch(batch_ds, start_idx):
            times = batch_ds[time_name].values
            data = batch_ds[var_name].values.astype(float_dtype, copy=False)
            n_b = data.shape[0]
            time_v[start_idx:start_idx + n_b] = netCDF4.date2num(
                [np.datetime64(t, "s").astype("datetime64[us]").astype(object) for t in times],
                units=time_units,
                calendar="proleptic_gregorian",
            )
            data_v[start_idx:start_idx + n_b, :, :] = data

        _write_batch(first_ds, 0)
        # Release first-batch arrays before next iteration.
        del first_ds

        idx = first_end
        batch_n = 2
        while idx < n_fields:
            end = min(idx + args.batch_size, n_fields)
            log(f"Regridding batch {batch_n}/{n_batches} (fields [{idx}:{end}])...")
            batch_ds = interpolate(
                src[idx:end], out_grid=out_grid, method=ek_method,
            ).to_xarray()
            if cropper:
                batch_ds = cropper(batch_ds)
            batch_ds.attrs = _netcdf_safe_attrs(batch_ds.attrs)
            for v in batch_ds.variables:
                batch_ds[v].attrs = _netcdf_safe_attrs(batch_ds[v].attrs)
            _write_batch(batch_ds, idx)
            del batch_ds
            idx = end
            batch_n += 1

        log(f"Wrote {n_fields} time steps to {output_path}")
    finally:
        nc_out.close()


if __name__ == "__main__":
    main()
