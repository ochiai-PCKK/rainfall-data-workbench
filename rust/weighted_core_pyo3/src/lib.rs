use numpy::{PyReadonlyArray2, PyReadonlyArray3};
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// ベンチおよび将来の本番利用を想定した、同一プロセスRust集計関数。
///
/// NumPy配列を直接受け取り（subprocess / ファイルI/Oなし）、
/// Pythonのdictで扱えるベクトルを返す。
#[pyfunction]
fn compute_weighted_core<'py>(
    py: Python<'py>,
    frames: PyReadonlyArray3<'py, f64>,
    weights: PyReadonlyArray2<'py, f64>,
    nodata: f64,
) -> PyResult<Py<PyDict>> {
    let frames = frames.as_array();
    let weights = weights.as_array();
    let (t_count, rows, cols) = frames.dim();
    let (w_rows, w_cols) = weights.dim();
    if rows != w_rows || cols != w_cols {
        return Err(pyo3::exceptions::PyValueError::new_err(
            "frame shape mismatch to weights shape",
        ));
    }

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

    let out = PyDict::new_bound(py);
    out.set_item("weighted_sum_mm", weighted_sum_mm)?;
    out.set_item("weighted_mean_mm", weighted_mean_mm)?;
    out.set_item("coverage_ratio", coverage_ratio)?;
    out.set_item("valid_weight", valid_weight)?;
    out.set_item(
        "total_weight",
        vec![if total_weight > 0.0 {
            Some(total_weight)
        } else {
            None
        }],
    )?;
    Ok(out.unbind())
}

#[pymodule]
fn weighted_core_pyo3(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(compute_weighted_core, m)?)?;
    Ok(())
}
