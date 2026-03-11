import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from datetime import datetime; from datetime import timedelta
import numpy as np
import csv
from jaxa.earth import je


# =========================================================
# デフォルト（ユーザー指定）
# =========================================================
DEFAULT_DTIM_START = "2021-07-01T00:00:00"
DEFAULT_DTIM_END   = "2021-07-03T00:00:00"

DEFAULT_BBOX = [122.0, 24.0, 146.0, 46.0]   # [min_lon, min_lat, max_lon, max_lat]
DEFAULT_PPU = 4

DEFAULT_COLLECTION = "JAXA.EORC_GSMaP_standard.Gauge.00Z-23Z.v6_daily"
DEFAULT_BAND = "PRECIP"


# =========================================================
# ユーティリティ
# =========================================================
def is_iso8601(s: str) -> bool:
    """YYYY-MM-DDTHH:MM:SS 形式チェック（24:00:00 は不可）"""
    try:
        datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return True
    except ValueError:
        return False


def ask_open_geojson():
    return filedialog.askopenfilename(
        title="GeoJSONファイルを選択",
        filetypes=[("GeoJSON", "*.geojson"), ("JSON", "*.json"), ("All files", "*.*")]
    )


def ask_save_csv():
    return filedialog.asksaveasfilename(
        title="CSV保存先を指定",
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
    )


def ask_save_tif():
    return filedialog.asksaveasfilename(
        title="GeoTIFF保存先を指定",
        defaultextension=".tif",
        filetypes=[("GeoTIFF", "*.tif;*.tiff"), ("All files", "*.*")]
    )


def log(msg: str):
    """GUIログ出力"""
    log_box.insert(tk.END, msg + "\n")
    log_box.see(tk.END)
    root.update_idletasks()


def lim_pair(lim):
    """ip.raster.latlim / lonlim から (min, max) を安全に取得"""
    b = np.array(lim, dtype=float)
    b = np.squeeze(b)
    if b.ndim == 1 and b.size == 2:
        return float(b[0]), float(b[1])
    b = b.reshape(-1, 2)
    return float(b[0, 0]), float(b[0, 1])


def normalize_to_tyx(arr):
    """
    ip.raster.img を (T, Y, X) に整形（1x1など極小でも対応）
    (Y,X)          -> (1,Y,X)
    (T,Y,X)        -> OK
    (T,Y,X,1)      -> (T,Y,X)
    (T,1,1,1)      -> (T,1,1)
    (T,)           -> (T,1,1)  ※ここが今回の救済
    (1,)           -> (1,1,1)
    """
    a = np.asarray(arr)

    # まず末尾のサイズ1軸だけを安全に落とす（時間軸は落とさない）
    while a.ndim >= 4 and a.shape[-1] == 1:
        a = a[..., 0]

    # 2D画像
    if a.ndim == 2:
        return a[None, :, :]

    # 3D
    if a.ndim == 3:
        return a

    # 1D（今回ここに来る：例 (3,)）
    if a.ndim == 1:
        return a[:, None, None]

    # それ以外は想定外
    raise ValueError(f"Unsupported raster.img shape: {getattr(arr, 'shape', None)} -> {a.shape}")
    return a


def build_lat_lon_vectors(latlim, lonlim, nrows, ncols):
    """
    latlim/lonlim と配列形状からセル中心の lat/lon ベクトルを生成。
    """
    latmin, latmax = lim_pair(latlim)
    lonmin, lonmax = lim_pair(lonlim)

    dlon = (lonmax - lonmin) / ncols
    dlat = (latmax - latmin) / nrows

    lons = lonmin + dlon * (0.5 + np.arange(ncols))
    lats = latmax - dlat * (0.5 + np.arange(nrows))  # 北→南
    return lats, lons


# =========================================================
# GeoJSONポリゴンでローカルマスク（NaN化）
# =========================================================
def _extract_rings_from_geojson_geometry(geom: dict):
    """
    GeoJSON geometry(dict) からポリゴンのリング列を取り出す。
    return: list of polygons, polygon = (exterior, holes[])
      exterior: [(x,y),...]
      holes: [ [(x,y),...], ... ]
    """
    gtype = geom.get("type", "")
    coords = geom.get("coordinates", None)
    if coords is None:
        return []

    polys = []
    if gtype == "Polygon":
        exterior = [(x, y) for x, y in coords[0]]
        holes = []
        for hole in coords[1:]:
            holes.append([(x, y) for x, y in hole])
        polys.append((exterior, holes))
    elif gtype == "MultiPolygon":
        for poly in coords:
            exterior = [(x, y) for x, y in poly[0]]
            holes = []
            for hole in poly[1:]:
                holes.append([(x, y) for x, y in hole])
            polys.append((exterior, holes))
    else:
        return []
    return polys


def polygon_mask_from_feature(feature: dict, lats: np.ndarray, lons: np.ndarray):
    """
    feature(GeoJSON Feature) とセル中心(lats,lons)から、
    ポリゴン内=Trueのマスク(H,W)を作る。
    依存: matplotlib
    """
    try:
        from matplotlib.path import Path as MplPath
    except Exception:
        return None

    geom = feature.get("geometry", feature)  # featureでもgeometryでも可
    polys = _extract_rings_from_geojson_geometry(geom)
    if not polys:
        return None

    H = len(lats)
    W = len(lons)
    lon_grid, lat_grid = np.meshgrid(lons, lats)
    pts = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])

    inside_any = np.zeros((H * W,), dtype=bool)

    for exterior, holes in polys:
        ext_path = MplPath(exterior)
        inside = ext_path.contains_points(pts)

        for hole in holes:
            hole_path = MplPath(hole)
            inside_hole = hole_path.contains_points(pts)
            inside &= ~inside_hole

        inside_any |= inside

    return inside_any.reshape(H, W)


def apply_polygon_nan_mask(arr_tyx: np.ndarray, mask_hw: np.ndarray):
    """
    mask_hw==False のセルを NaN にする（全時間バンドに適用）
    ※ (T,H,W) と (H,W) のブールインデックス事故を回避するため where を使う
    """
    if mask_hw is None:
        return arr_tyx

    a = np.asarray(arr_tyx)
    if not np.issubdtype(a.dtype, np.floating):
        a = a.astype("float32")

    m = np.asarray(mask_hw, dtype=bool)
    if m.ndim != 2:
        raise ValueError(f"mask_hw must be 2D (H,W), got {m.shape}")

    return np.where(m[None, :, :], a, np.nan)


# =========================================================
# CSV書き出し（巨大対策：ストリーミング）
# =========================================================
def write_pixel_csv(out_csv, arr_tyx, lats, lons, dates=None, drop_nan=True):
    """
    出力CSV列: time, lat, lon, value
    - dates が取れない場合は time=0..T-1
    - drop_nan=True で NaNを除外
    """
    out_path = Path(out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    T, H, W = arr_tyx.shape

    if dates is not None:
        time_labels = list(dates)
        if len(time_labels) != T:
            time_labels = [str(i) for i in range(T)]
    else:
        time_labels = [str(i) for i in range(T)]

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "lat", "lon", "value"])

        for t in range(T):
            tlabel = time_labels[t]
            layer = arr_tyx[t]  # (H, W)

            for y in range(H):
                lat = float(lats[y])
                row_vals = layer[y, :]  # (W,)

                if drop_nan:
                    mask = ~np.isnan(row_vals)
                    if not np.any(mask):
                        continue
                    xs = np.where(mask)[0]
                    for x in xs:
                        writer.writerow([tlabel, lat, float(lons[x]), float(row_vals[x])])
                else:
                    for x in range(W):
                        v = row_vals[x]
                        writer.writerow([tlabel, lat, float(lons[x]), "" if np.isnan(v) else float(v)])


# =========================================================
# GeoTIFF書き出し（バンド=時間）
# =========================================================
def write_multiband_geotiff(out_tif, arr_tyx, latlim, lonlim, band_desc=None, nodata=-9999.0, crs="EPSG:4326"):
    """
    arr_tyx: (T, Y, X)
    latlim/lonlim と配列形状から transform を作り、GeoTIFFへ書き出す。
    band_desc: list[str] を渡すと、各バンドに説明（日時など）を埋め込む。
    """
    try:
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.enums import ColorInterp
    except ImportError as e:
        raise ImportError("GeoTIFF出力には rasterio が必要です。例: pip install rasterio") from e

    data = np.asarray(arr_tyx)
    if not np.issubdtype(data.dtype, np.floating):
        data = data.astype("float32")
    else:
        data = data.astype("float32", copy=False)

    T, H, W = data.shape

    latmin, latmax = lim_pair(latlim)
    lonmin, lonmax = lim_pair(lonlim)

    transform = from_bounds(lonmin, latmin, lonmax, latmax, W, H)

    # NaNをnodataへ
    if np.isnan(data).any():
        data = np.where(np.isnan(data), nodata, data)

    out_path = Path(out_tif)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=H,
        width=W,
        count=T,               # バンド数=時間
        dtype="float32",
        crs=crs,
        transform=transform,
        nodata=nodata,
        compress="deflate",
    ) as dst:
        for i in range(T):
            dst.write(data[i, :, :], i + 1)

        # QGISのRGB誤解釈回避：全部 Gray にする
        try:
            dst.colorinterp = tuple([ColorInterp.gray] * T)
        except Exception:
            pass

        # バンド説明（日時）を埋め込む
        if band_desc is not None and len(band_desc) == T:
            for i in range(T):
                try:
                    dst.set_band_description(i + 1, str(band_desc[i]))
                except Exception:
                    pass

    return {"bands": T, "height": H, "width": W, "bbox": (lonmin, latmin, lonmax, latmax)}


# =========================================================
# 追加：GeoTIFF 分割出力ユーティリティ（最小追記）
# =========================================================
def _safe_suffix(s: str) -> str:
    """ファイル名用に危険文字を除去"""
    return (str(s)
            .replace(":", "")
            .replace("/", "")
            .replace("\\", "")
            .replace(" ", "_")
            .replace("..", "_")
            .replace("__", "_"))


def _make_child_tif_path(base_tif: str, suffix: str) -> str:
    """out.tif -> out_SUFFIX.tif"""
    p = Path(base_tif)
    return str(p.with_name(f"{p.stem}_{_safe_suffix(suffix)}{p.suffix}"))


def _group_time_indices(time_labels, mode: str):
    """
    mode:
    - "single": 全部まとめる
    - "daily" : 日付(YYYYMMDD)ごと
    - "hourly": 時間(YYYYMMDD_HH)ごと
    return: list of (suffix, indices[list[int]])
    """
    T = len(time_labels)
    if mode == "single":
        return [("all", list(range(T)))]

    groups = {}
    for i, lab in enumerate(time_labels):
        key = None
        try:
            dt = datetime.strptime(lab, "%Y-%m-%dT%H:%M:%S")
            if mode == "daily":
                key = dt.strftime("%Y%m%d")
            elif mode == "hourly":
                key = dt.strftime("%Y%m%d_%H")
        except Exception:
            # ラベルがISOでない場合のフォールバック（崩さないため控えめ）
            if mode == "daily":
                key = f"day_{i:03d}"
            else:
                key = f"hour_{i:03d}"

        groups.setdefault(key, []).append(i)

    # 安定した順序で出力
    return [(k, groups[k]) for k in sorted(groups.keys())]


# =========================================================
# JAXA Earth API 取得（公式の呼び出し順序に準拠）
# =========================================================
def fetch_jaxa_images(collection_id, band_name, dlim, ppu, bounds_mode, bounds_obj, ssl_verify=True):
    """
    bounds_mode: 'bbox' or 'geojson'
    bounds_obj: bbox(list) or geojson feature(dict)
    return: ImageCollection（raster更新済み）
    """
    ic = je.ImageCollection(collection=collection_id, ssl_verify=ssl_verify)

    ic = ic.filter_date(dlim=dlim)
    ic = ic.filter_resolution(ppu=ppu)

    if bounds_mode == "bbox":
        ic = ic.filter_bounds(bbox=bounds_obj)
    else:
        ic = ic.filter_bounds(geoj=bounds_obj)

    ic = ic.select(band=band_name)
    ic = ic.get_images()
    return ic


def try_extract_time_labels_from_dlim(dlim, T):
    """
    timeラベル生成：
    - daily系なら「start + i日」を優先
    - うまく行かなければ fallback
    """
    if not dlim or len(dlim) != 2:
        return [str(i) for i in range(T)]

    try:
        start = datetime.strptime(dlim[0], "%Y-%m-%dT%H:%M:%S")
        end = datetime.strptime(dlim[1], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return [f"{dlim[0]}..{dlim[1]}#{i}" for i in range(T)]

    # daily想定：1日刻み
    daily = [(start + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M:%S") for i in range(T)]
    if (end - start) >= timedelta(days=max(T - 1, 0)):
        return daily

    # それ以外：均等割り
    if T > 1:
        step = (end - start) / (T - 1)
        return [(start + step * i).strftime("%Y-%m-%dT%H:%M:%S") for i in range(T)]

    return [start.strftime("%Y-%m-%dT%H:%M:%S")]


# =========================================================
# GUIコールバック
# =========================================================
def on_pick_geojson():
    path = ask_open_geojson()
    if path:
        entry_geojson.delete(0, tk.END)
        entry_geojson.insert(0, path)


def on_pick_outcsv():
    path = ask_save_csv()
    if path:
        entry_outcsv.delete(0, tk.END)
        entry_outcsv.insert(0, path)


def on_pick_outtif():
    path = ask_save_tif()
    if path:
        entry_outtif.delete(0, tk.END)
        entry_outtif.insert(0, path)


def on_mode_change(*_):
    mode = area_mode.get()
    if mode == "bbox":
        for w in bbox_widgets:
            w.configure(state="normal")
        entry_geojson.configure(state="disabled")
        btn_geojson.configure(state="disabled")
    else:
        for w in bbox_widgets:
            w.configure(state="disabled")
        entry_geojson.configure(state="normal")
        btn_geojson.configure(state="normal")


# ========# 取得 → CSV/GeoTIFF 出力（両方）

# --- 追加：白余白削除（有効データ外接矩形で切り抜く）用 ---
def crop_by_valid_data(arr_tyx):
    """
    arr_tyx: (T, H, W)
    return: y0, y1, x0, x1  (包含)
    """
    valid_hw = (~np.isnan(arr_tyx)).any(axis=0)  # (H,W)
    ys, xs = np.where(valid_hw)
    if ys.size == 0 or xs.size == 0:
        raise ValueError("有効データが存在しません（全てNaNの可能性）")
    return int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())


def edges_latlon_for_crop(lats, lons, y0, y1, x0, x1):
    """
    セル中心ベクトル(lats,lons)から、切り抜き窓に対応する外枠(latlim/lonlim)を計算。
    lats: 北→南（降順）, lons: 西→東（昇順）
    """
    if len(lons) >= 2:
        dlon = float(lons[1] - lons[0])
    else:
        dlon = 0.0
    if len(lats) >= 2:
        dlat = float(abs(lats[1] - lats[0]))
    else:
        dlat = 0.0

    lon_min_edge = float(lons[x0] - dlon / 2.0)
    lon_max_edge = float(lons[x1] + dlon / 2.0)

    lat_max_edge = float(lats[y0] + dlat / 2.0)  # 上端（北側）
    lat_min_edge = float(lats[y1] - dlat / 2.0)  # 下端（南側）

    latlim_new = (lat_min_edge, lat_max_edge)
    lonlim_new = (lon_min_edge, lon_max_edge)
    return latlim_new, lonlim_new


# --- 追加：GeoTIFF 分割出力ユーティリティ（現行/日別/時間別） ---
def _safe_suffix(s: str) -> str:
    return (str(s)
            .replace(":", "")
            .replace("/", "")
            .replace("\\", "")
            .replace(" ", "_")
            .replace("..", "_")
            .replace("__", "_"))


def _make_child_tif_path(base_tif: str, suffix: str) -> str:
    p = Path(base_tif)
    return str(p.with_name(f"{p.stem}_{_safe_suffix(suffix)}{p.suffix}"))


def _group_time_indices(time_labels, mode: str):
    """
    mode:
    - "single": 全部まとめる
    - "daily" : 日付(YYYYMMDD)ごと
    - "hourly": 時間(YYYYMMDD_HH)ごと
    return: list of (suffix, indices[list[int]])
    """
    T = len(time_labels)
    if mode == "single":
        return [("all", list(range(T)))]

    groups = {}
    for i, lab in enumerate(time_labels):
        try:
            dt = datetime.strptime(lab, "%Y-%m-%dT%H:%M:%S")
            if mode == "daily":
                key = dt.strftime("%Y%m%d")
            else:
                key = dt.strftime("%Y%m%d_%H")
        except Exception:
            key = f"{mode}_{i:03d}"
        groups.setdefault(key, []).append(i)

    return [(k, groups[k]) for k in sorted(groups.keys())]


def run_fetch_export():
    try:
        log_box.delete("1.0", tk.END)

        mode = area_mode.get()  # "bbox" or "geojson"

        # --- parameter ---
        start_dt = entry_start.get().strip()
        end_dt = entry_end.get().strip()
        if not (is_iso8601(start_dt) and is_iso8601(end_dt)):
            raise ValueError("Date は 'YYYY-MM-DDTHH:MM:SS' 形式で入力してください。例: 2021-07-01T00:00:00")
        dlim = [start_dt, end_dt]

        try:
            ppu = float(entry_ppu.get().strip())
        except ValueError:
            raise ValueError("ppu は数値で入力してください。例: 10（GSMaPは0.1度格子なら10推奨）")

        collection_id = entry_collection.get().strip()
        band_name = entry_band.get().strip()
        if not collection_id:
            raise ValueError("Collection ID が空です。")
        if not band_name:
            raise ValueError("Band が空です。")

        ssl_verify = bool_var_ssl.get()
        drop_nan = bool_var_dropnan.get()

        do_csv = bool_var_out_csv.get()
        do_tif = bool_var_out_tif.get()

        out_csv = entry_outcsv.get().strip()
        out_tif = entry_outtif.get().strip()

        if not (do_csv or do_tif):
            raise ValueError("出力が未選択です。CSVまたはGeoTIFFの少なくともどちらかにチェックしてください。")

        if do_csv and not out_csv:
            raise ValueError("CSV出力を選択していますが、CSV保存先が未指定です。")
        if do_tif and not out_tif:
            raise ValueError("GeoTIFF出力を選択していますが、GeoTIFF保存先が未指定です。")

        # GeoTIFFモード（追加）
        tif_mode = tif_output_mode.get()  # "single" / "daily" / "hourly"

        # --- 領域指定 ---
        if mode == "bbox":
            vals = [e.get().strip() for e in (entry_minlon, entry_minlat, entry_maxlon, entry_maxlat)]
            if any(v == "" for v in vals):
                raise ValueError("BBox の4値（min_lon, min_lat, max_lon, max_lat）を全て入力してください。")
            try:
                bbox = [float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3])]
            except ValueError:
                raise ValueError("BBox は数値で入力してください。")
            bounds_mode = "bbox"
            bounds_obj = bbox
            log(f"[INFO] Mode=BBox  bbox={bbox}")
        else:
            geojson_path = entry_geojson.get().strip()
            if not geojson_path:
                raise ValueError("GeoJSONファイルが未指定です。参照ボタンで選択してください。")
            if not Path(geojson_path).exists():
                raise ValueError(f"GeoJSONファイルが見つかりません: {geojson_path}")

            features = je.FeatureCollection().read(geojson_path).select([])
            if not features:
                raise ValueError("GeoJSONにFeatureが見つかりませんでした。")
            feature = features[0]

            bounds_mode = "geojson"
            bounds_obj = feature
            log(f"[INFO] Mode=GeoJSON  path={geojson_path}")

        # --- 取得（公式のメソッド順序に準拠） ---
        btn_run.configure(state="disabled")
        root.configure(cursor="watch")
        root.update_idletasks()

        log("[INFO] Fetch start ...")
        ic = fetch_jaxa_images(
            collection_id=collection_id,
            band_name=band_name,
            dlim=dlim,
            ppu=ppu,
            bounds_mode=bounds_mode,
            bounds_obj=bounds_obj,
            ssl_verify=ssl_verify
        )

        ip = je.ImageProcess(ic)

        # 生配列・範囲
        arr_tyx = normalize_to_tyx(ip.raster.img)
        latlim = ip.raster.latlim
        lonlim = ip.raster.lonlim
        T, H, W = arr_tyx.shape

        # NaNのためfloat化
        if not np.issubdtype(arr_tyx.dtype, np.floating):
            arr_tyx = arr_tyx.astype("float32")

        log(f"[DEBUG] raw raster.img shape = {np.asarray(ip.raster.img).shape}")
        log(f"[DEBUG] normalized arr_tyx shape = {arr_tyx.shape}")
        log(f"[INFO] raster.img shape (T,Y,X) = {arr_tyx.shape}")
        log(f"[INFO] raster.latlim={np.squeeze(np.array(latlim)).tolist()}  raster.lonlim={np.squeeze(np.array(lonlim)).tolist()}")

        # 座標ベクトル生成（CSV用）
        lats, lons = build_lat_lon_vectors(latlim, lonlim, H, W)

        # timeラベル
        time_labels = try_extract_time_labels_from_dlim(dlim, T)

        # --- GeoJSON選択時：ポリゴン外をNaN化（CSV軽量化に効く） ---
        mask_hw = None
        if bounds_mode == "geojson" and drop_nan:
            mask_hw = polygon_mask_from_feature(bounds_obj, lats, lons)
            if mask_hw is None:
                log("[WARN] ポリゴンマスクを作れませんでした（matplotlib未導入等）。bbox相当で出力します。")
            else:
                before = np.isnan(arr_tyx).sum()
                arr_tyx = apply_polygon_nan_mask(arr_tyx, mask_hw)
                after = np.isnan(arr_tyx).sum()
                log(f"[INFO] Polygon mask applied. NaN count: {before} -> {after}")

        # ==============================
        # 追加：GeoTIFFを“白余白（NoData）”が出ないように切り抜く（CSVと一致）
        # ==============================
        arr_tyx_tif = arr_tyx
        latlim_tif = latlim
        lonlim_tif = lonlim

        # 有効データ外接矩形で切り抜き（drop_nanの結果と揃う）
        y0, y1, x0, x1 = crop_by_valid_data(arr_tyx_tif)
        arr_tyx_tif = arr_tyx_tif[:, y0:y1+1, x0:x1+1]
        latlim_tif, lonlim_tif = edges_latlon_for_crop(lats, lons, y0, y1, x0, x1)
        log(f"[INFO] GeoTIFF crop by valid data bbox: y={y0}-{y1}, x={x0}-{x1}")

        # --- CSV出力 ---
        if do_csv:
            log(f"[INFO] Write CSV ... {out_csv}")
            write_pixel_csv(out_csv, arr_tyx, lats, lons, dates=time_labels, drop_nan=drop_nan)
            log("[INFO] CSV done.")

        # --- GeoTIFF出力（モード分岐：現行/日別/時間別） ---
        if do_tif:
            if tif_mode == "single":
                log(f"[INFO] Write GeoTIFF (single) ... {out_tif}")
                info = write_multiband_geotiff(out_tif, arr_tyx_tif, latlim_tif, lonlim_tif, band_desc=time_labels)
                log(f"[INFO] GeoTIFF done. {info}")
            else:
                groups = _group_time_indices(time_labels, tif_mode)  # (suffix, indices)
                log(f"[INFO] Write GeoTIFF ({tif_mode}) ... base={out_tif}  files={len(groups)}")
                for suffix, idxs in groups:
                    child = _make_child_tif_path(out_tif, suffix)
                    sub_arr = arr_tyx_tif[idxs, :, :]
                    sub_desc = [time_labels[i] for i in idxs]
                    log(f"[INFO]  - {child}  bands={len(idxs)}")
                    write_multiband_geotiff(child, sub_arr, latlim_tif, lonlim_tif, band_desc=sub_desc)
                log("[INFO] GeoTIFF split output done.")

            log("[TIP] QGISでは「単バンド疑似カラー」で表示し、min/maxを固定すると見やすくなります。")

        log("[INFO] All done.")
        messagebox.showinfo("完了", "取得と出力が完了しました。")

    except Exception as e:
        messagebox.showerror("エラー", str(e))
        log(f"[ERROR] {e}")

    finally:
        root.configure(cursor="")
        btn_run.configure(state="normal")
        root.update_idletasks()


# =========================================================
# GUI
# =========================================================
root = tk.Tk()
root.title("JAXA Earth API 取得GUI（BBox / GeoJSON）→ CSV & GeoTIFF 出力")

root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

main = ttk.Frame(root, padding=12)
main.grid(row=0, column=0, sticky="nsew")
main.columnconfigure(1, weight=1)
main.rowconfigure(12, weight=1)

# --- Dataset ---
ttk.Label(main, text="Collection ID").grid(row=0, column=0, sticky="w")
entry_collection = ttk.Entry(main)
entry_collection.grid(row=0, column=1, sticky="ew", padx=6)
entry_collection.insert(0, DEFAULT_COLLECTION)

ttk.Label(main, text="Band").grid(row=1, column=0, sticky="w")
entry_band = ttk.Entry(main)
entry_band.grid(row=1, column=1, sticky="ew", padx=6)
entry_band.insert(0, DEFAULT_BAND)

ttk.Label(main, text="ppu (Pixels Per Unit)").grid(row=2, column=0, sticky="w")
entry_ppu = ttk.Entry(main, width=10)
entry_ppu.grid(row=2, column=1, sticky="w", padx=6)
entry_ppu.insert(0, str(DEFAULT_PPU))

bool_var_ssl = tk.BooleanVar(value=True)
ttk.Checkbutton(main, text="SSL verify", variable=bool_var_ssl).grid(row=2, column=1, sticky="e", padx=6)

# --- Date
ttk.Label(main, text="Start (YYYY-MM-DDTHH:MM:SS)").grid(row=3, column=0, sticky="w")
entry_start = ttk.Entry(main)
entry_start.grid(row=3, column=1, sticky="ew", padx=6)
entry_start.insert(0, DEFAULT_DTIM_START)

ttk.Label(main, text="End   (YYYY-MM-DDTHH:MM:SS)").grid(row=4, column=0, sticky="w")
entry_end = ttk.Entry(main)
entry_end.grid(row=4, column=1, sticky="ew", padx=6)
entry_end.insert(0, DEFAULT_DTIM_END)

# --- Area mode ---
area_mode = tk.StringVar(value="bbox")

frame_area = ttk.LabelFrame(main, text="領域指定", padding=8)
frame_area.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10)
frame_area.columnconfigure(1, weight=1)

ttk.Radiobutton(frame_area, text="BBox（四点座標）", value="bbox", variable=area_mode, command=on_mode_change).grid(row=0, column=0, sticky="w")
ttk.Radiobutton(frame_area, text="GeoJSON（境界ポリゴン）", value="geojson", variable=area_mode, command=on_mode_change).grid(row=0, column=1, sticky="w")

bbox_row = ttk.Frame(frame_area)
bbox_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)

ttk.Label(bbox_row, text="min_lon").grid(row=0, column=0, sticky="w")
entry_minlon = ttk.Entry(bbox_row, width=12)
entry_minlon.grid(row=0, column=1, padx=4)
entry_minlon.insert(0, str(DEFAULT_BBOX[0]))

ttk.Label(bbox_row, text="min_lat").grid(row=0, column=2, sticky="w")
entry_minlat = ttk.Entry(bbox_row, width=12)
entry_minlat.grid(row=0, column=3, padx=4)
entry_minlat.insert(0, str(DEFAULT_BBOX[1]))

ttk.Label(bbox_row, text="max_lon").grid(row=0, column=4, sticky="w")
entry_maxlon = ttk.Entry(bbox_row, width=12)
entry_maxlon.grid(row=0, column=5, padx=4)
entry_maxlon.insert(0, str(DEFAULT_BBOX[2]))

ttk.Label(bbox_row, text="max_lat").grid(row=0, column=6, sticky="w")
entry_maxlat = ttk.Entry(bbox_row, width=12)
entry_maxlat.grid(row=0, column=7, padx=4)
entry_maxlat.insert(0, str(DEFAULT_BBOX[3]))

bbox_widgets = [entry_minlon, entry_minlat, entry_maxlon, entry_maxlat]

geo_row = ttk.Frame(frame_area)
geo_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=6)
geo_row.columnconfigure(0, weight=1)

entry_geojson = ttk.Entry(geo_row)
entry_geojson.grid(row=0, column=0, sticky="ew")
btn_geojson = ttk.Button(geo_row, text="参照…", command=on_pick_geojson)
btn_geojson.grid(row=0, column=1, padx=6)

# --- Output options ---
frame_out = ttk.LabelFrame(main, text="出力", padding=8)
frame_out.grid(row=6, column=0, columnspan=2, sticky="ew", pady=6)
frame_out.columnconfigure(2, weight=1)

bool_var_out_csv = tk.BooleanVar(value=True)
bool_var_out_tif = tk.BooleanVar(value=True)

ttk.Checkbutton(frame_out, text="CSV（ピクセル全点）を出力", variable=bool_var_out_csv).grid(row=0, column=0, sticky="w")
ttk.Checkbutton(frame_out, text="GeoTIFF（時間=バンド）を出力", variable=bool_var_out_tif).grid(row=1, column=0, sticky="w")

# GeoTIFF 出力モード（追加）
tif_output_mode = tk.StringVar(value="single")
frame_tifmode = ttk.Frame(frame_out)
frame_tifmode.grid(row=2, column=0, sticky="w", pady=(6, 0))
ttk.Label(frame_tifmode, text="GeoTIFFモード: ").grid(row=0, column=0, sticky="w")
ttk.Radiobutton(frame_tifmode, text="(1)現行", value="single", variable=tif_output_mode).grid(row=0, column=1, sticky="w")
ttk.Radiobutton(frame_tifmode, text="(2)日別",  value="daily",  variable=tif_output_mode).grid(row=0, column=2, sticky="w", padx=(8, 0))
ttk.Radiobutton(frame_tifmode, text="(3)時間別", value="hourly", variable=tif_output_mode).grid(row=0, column=3, sticky="w", padx=(8, 0))

# CSV path
ttk.Label(frame_out, text="CSV保存場所").grid(row=0, column=1, sticky="w", padx=(10, 0))
row_csv = ttk.Frame(frame_out)
row_csv.grid(row=0, column=2, sticky="ew")
row_csv.columnconfigure(0, weight=1)
entry_outcsv = ttk.Entry(row_csv)
entry_outcsv.grid(row=0, column=0, sticky="ew")
ttk.Button(row_csv, text="保存先…", command=on_pick_outcsv).grid(row=0, column=1, padx=6)

# TIF path
ttk.Label(frame_out, text="GeoTIFF保存先").grid(row=1, column=1, sticky="w", padx=(10, 0))
row_tif = ttk.Frame(frame_out)
row_tif.grid(row=1, column=2, sticky="ew")
row_tif.columnconfigure(0, weight=1)
entry_outtif = ttk.Entry(row_tif)
entry_outtif.grid(row=0, column=0, sticky="ew")
ttk.Button(row_tif, text="保存先…", command=on_pick_outtif).grid(row=0, column=1, padx=6)

# CSV軽量化
bool_var_dropnan = tk.BooleanVar(value=True)
ttk.Checkbutton(main, text="NaN（ポリゴン外など）を除外してCSVを軽量化", variable=bool_var_dropnan).grid(row=7, column=0, columnspan=2, sticky="w")

# --- Run ---
btn_run = ttk.Button(main, text="取得して出力（CSV/GeoTIFF）", command=run_fetch_export)
btn_run.grid(row=8, column=0, columnspan=2, sticky="ew", pady=10)

# --- Log ---
ttk.Label(main, text="ログ").grid(row=9, column=0, sticky="w")
log_box = tk.Text(main, height=12)
log_box.grid(row=12, column=0, columnspan=2, sticky="nsew")

# 初期排他制御
on_mode_change()

log("GUI起動しました。CSVとGeoTIFFの両方を出力できます。")
log("GeoTIFF出力には rasterio が必要です（未導入なら pip install rasterio）。")
log("取得順序は filter_date → filter_resolution → filter_bounds → select → get_images です。")
log("QGISで見づらい場合は「単バンド疑似カラー」＋ min/max 固定が基本です。")

root.mainloop()


