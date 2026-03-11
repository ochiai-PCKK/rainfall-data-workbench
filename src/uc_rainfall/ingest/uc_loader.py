from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from ..models import UcInputBundle


def _resolve_bundle(root: Path, source_path: Path, dataset_id: str | None = None) -> UcInputBundle:
    """展開済み入力ディレクトリから取り込み対象ファイル群を確定する。"""
    if not root.exists():
        raise FileNotFoundError(f"入力パスが見つかりません: {root}")

    rain_dat_path = root / "rain.dat"
    if not rain_dat_path.exists():
        raise FileNotFoundError(f"rain.dat が見つかりません: {rain_dat_path}")

    raster_paths = tuple(
        sorted(
            path
            for path in root.iterdir()
            if path.is_file() and "_JST_" in path.name and path.suffix.lower() in {".tif", ".tiff"}
        )
    )
    if not raster_paths:
        raster_paths = tuple(
            sorted(path for path in root.iterdir() if path.is_file() and path.suffix.lower() in {".tif", ".tiff"})
        )

    mail_candidates = [
        root.parent / "uc_mail_data" / "mail_txt.txt",
        root / "mail_txt.txt",
    ]
    mail_text_path = next((path for path in mail_candidates if path.exists()), None)

    if dataset_id is not None:
        resolved_dataset_id = dataset_id
    elif source_path.is_file():
        resolved_dataset_id = source_path.stem
    else:
        resolved_dataset_id = root.name

    return UcInputBundle(
        dataset_id=resolved_dataset_id,
        source_path=source_path,
        input_dir=root,
        rain_dat_path=rain_dat_path,
        raster_paths=raster_paths,
        mail_text_path=mail_text_path,
    )


@contextmanager
def load_uc_input_bundle(input_path: str | Path, dataset_id: str | None = None):
    """ディレクトリまたは ZIP を受け取り、処理可能な入力束を返す。"""
    source_path = Path(input_path)
    if not source_path.exists():
        raise FileNotFoundError(f"入力パスが見つかりません: {source_path}")

    if source_path.is_dir():
        yield _resolve_bundle(source_path, source_path, dataset_id=dataset_id)
        return

    if source_path.suffix.lower() != ".zip":
        raise ValueError(f"未対応の入力形式です: {source_path}")

    with TemporaryDirectory(prefix="uc_rainfall_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        with zipfile.ZipFile(source_path) as archive:
            archive.extractall(tmp_root)

        rain_dat_candidates = list(tmp_root.rglob("rain.dat"))
        if len(rain_dat_candidates) != 1:
            raise ValueError(
                f"ZIP 内の rain.dat は 1 件である必要があります。検出件数={len(rain_dat_candidates)}: {source_path}"
            )
        extracted_root = rain_dat_candidates[0].parent
        yield _resolve_bundle(extracted_root, source_path, dataset_id=dataset_id)
