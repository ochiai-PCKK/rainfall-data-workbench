use ndarray::{Array2, Array3};
use ndarray_npy::read_npy;
use serde::Serialize;
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::PathBuf;

// subprocess版ベンチ実行バイナリ:
// - `weights.npy` / `frames.npy` を読む
// - 重み付き集計を計算する
// - 結果をJSONで書き出す

#[derive(Debug, Serialize)]
struct OutputPayload {
    weighted_sum_mm: Vec<Option<f64>>,
    weighted_mean_mm: Vec<Option<f64>>,
    coverage_ratio: Vec<Option<f64>>,
    valid_weight: Vec<Option<f64>>,
    total_weight: Vec<Option<f64>>,
}

fn fail(msg: &str) -> ! {
    eprintln!("{msg}");
    std::process::exit(2);
}

fn parse_args() -> (PathBuf, PathBuf, PathBuf, f64) {
    // ベンチ専用の最小引数パーサ。
    let args: Vec<String> = env::args().collect();
    let mut map: HashMap<String, String> = HashMap::new();
    let mut i = 1usize;
    while i + 1 < args.len() {
        if args[i].starts_with("--") {
            map.insert(args[i].clone(), args[i + 1].clone());
            i += 2;
        } else {
            i += 1;
        }
    }
    let weights = map
        .get("--weights")
        .map(PathBuf::from)
        .unwrap_or_else(|| fail("missing --weights"));
    let frames = map
        .get("--frames")
        .map(PathBuf::from)
        .unwrap_or_else(|| fail("missing --frames"));
    let out = map
        .get("--out")
        .map(PathBuf::from)
        .unwrap_or_else(|| fail("missing --out"));
    let nodata = map
        .get("--nodata")
        .and_then(|s| s.parse::<f64>().ok())
        .unwrap_or_else(|| fail("invalid --nodata"));
    (weights, frames, out, nodata)
}

fn main() {
    let (weights_path, frames_path, out_path, nodata) = parse_args();
    let weights: Array2<f64> =
        read_npy(&weights_path).unwrap_or_else(|e| fail(&format!("failed to read weights npy: {e}")));
    let frames: Array3<f64> =
        read_npy(&frames_path).unwrap_or_else(|e| fail(&format!("failed to read frames npy: {e}")));

    let (rows, cols) = (weights.shape()[0], weights.shape()[1]);
    if frames.shape()[1] != rows || frames.shape()[2] != cols {
        fail("frame shape mismatch to weights shape");
    }
    let t_count = frames.shape()[0];

    // 正の重みセルを先に求めておき、時刻ループで再利用する。
    let mut positive = vec![vec![false; cols]; rows];
    let mut total_weight = 0.0f64;
    for i in 0..rows {
        for j in 0..cols {
            let w = weights[(i, j)];
            if w > 0.0 {
                positive[i][j] = true;
                total_weight += w;
            }
        }
    }

    let mut weighted_sum_mm = vec![None; t_count];
    let mut weighted_mean_mm = vec![None; t_count];
    let mut coverage_ratio = vec![None; t_count];
    let mut valid_weight = vec![None; t_count];

    for t in 0..t_count {
        // 時刻ごとの重み付き集計。
        let mut vw = 0.0f64;
        let mut ws = 0.0f64;
        for i in 0..rows {
            for j in 0..cols {
                if !positive[i][j] {
                    continue;
                }
                let v = frames[(t, i, j)];
                if !v.is_finite() {
                    continue;
                }
                if (v - nodata).abs() < 1e-12 {
                    continue;
                }
                let w = weights[(i, j)];
                vw += w;
                ws += v * w;
            }
        }
        if total_weight > 0.0 {
            coverage_ratio[t] = Some(vw / total_weight);
        }
        if vw > 0.0 {
            valid_weight[t] = Some(vw);
            weighted_sum_mm[t] = Some(ws);
            weighted_mean_mm[t] = Some(ws / vw);
        }
    }

    let payload = OutputPayload {
        weighted_sum_mm,
        weighted_mean_mm,
        coverage_ratio,
        valid_weight,
        total_weight: vec![if total_weight > 0.0 { Some(total_weight) } else { None }],
    };
    let text = serde_json::to_string(&payload).unwrap_or_else(|e| fail(&format!("json serialize error: {e}")));
    fs::write(&out_path, text).unwrap_or_else(|e| fail(&format!("failed to write out json: {e}")));
}
