"""scikit-learn classification training entry point.

Designed to run either:
- locally / on a compute instance (call `train()` directly), or
- as an AML command job (invoke as `python -m src.train --data-path ... --target ...`).

Logs to MLflow (which AML auto-captures) and writes the model under `outputs/model/`
so the AML job picks it up as a registerable artifact.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, f1_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def _load_dataframe(data_path: str) -> pd.DataFrame:
    p = Path(data_path)
    if p.is_dir():
        # MLTable folder produced by copy_fabric_to_aml
        parquet = p / "data.parquet"
        if parquet.exists():
            return pd.read_parquet(parquet)
        # fall through to glob
        files = list(p.glob("*.parquet"))
        if files:
            return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        raise FileNotFoundError(f"No parquet under {p}")
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    if p.suffix in {".csv", ".tsv"}:
        sep = "," if p.suffix == ".csv" else "\t"
        return pd.read_csv(p, sep=sep)
    raise ValueError(f"Unsupported data path: {p}")


def _engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Expand any datetime columns into year/month/day/dayofweek and drop the original."""
    out = df.copy()
    for col in list(out.columns):
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[f"{col}_year"] = out[col].dt.year
            out[f"{col}_month"] = out[col].dt.month
            out[f"{col}_day"] = out[col].dt.day
            out[f"{col}_dayofweek"] = out[col].dt.dayofweek
            out = out.drop(columns=[col])
    return out


def _prepare_dataframe(
    df: pd.DataFrame,
    target: str,
    drop_cols: list[str] | None,
    *,
    filter_rare_target_classes: bool,
) -> pd.DataFrame:
    if target not in df.columns:
        raise ValueError(f"Target column '{target}' not in data: {list(df.columns)}")

    if drop_cols:
        present = [c for c in drop_cols if c in df.columns]
        if present:
            df = df.drop(columns=present)
            print(f"Dropped feature columns: {present}")

    # Drop rows with null target.
    before = len(df)
    df = df.dropna(subset=[target]).reset_index(drop=True)
    if len(df) < before:
        print(f"Dropped {before - len(df):,} rows with null target.")

    # Coerce target to a discrete sklearn-friendly dtype. Object columns
    # round-tripped through parquet/MLTable can come back as `object` even
    # when values are bool/int — sklearn rejects those as "unknown" label type.
    if df[target].dtype == object:
        df[target] = df[target].astype(str)
    elif pd.api.types.is_bool_dtype(df[target]):
        df[target] = df[target].astype(str)

    # For train data, drop ultra-rare classes that would break stratified split (need >= 2).
    if filter_rare_target_classes:
        counts = df[target].value_counts()
        keep = counts[counts >= 2].index
        if len(keep) < len(counts):
            df = df[df[target].isin(keep)].reset_index(drop=True)
            print(f"Filtered to {len(keep)} classes with >= 2 samples ({len(df):,} rows).")

    return _engineer_features(df)


def _build_pipeline(
    df: pd.DataFrame,
    target: str,
    n_estimators: int = 200,
    max_depth: int | None = None,
) -> Pipeline:
    feature_df = df.drop(columns=[target])
    numeric = feature_df.select_dtypes(include="number").columns.tolist()
    categorical = [c for c in feature_df.columns if c not in numeric]

    numeric_pipe = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )
    categorical_pipe = Pipeline(
        steps=[
            ("impute", SimpleImputer(strategy="constant", fill_value="__missing__")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    pre = ColumnTransformer(
        transformers=[
            ("num", numeric_pipe, numeric),
            ("cat", categorical_pipe, categorical),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocess", pre),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=n_estimators,
                    max_depth=max_depth,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )


def train(
    data_path: str,
    target: str,
    test_data_path: str | None = None,
    test_size: float = 0.2,
    random_state: int = 42,
    output_dir: str = "outputs/model",
    drop_cols: list[str] | None = None,
    n_estimators: int = 200,
    max_depth: int | None = None,
) -> dict:
    train_df = _load_dataframe(data_path)
    print(f"Loaded training data: {len(train_df):,} rows / {train_df.shape[1]} columns.")
    train_df = _prepare_dataframe(
        train_df,
        target,
        drop_cols,
        filter_rare_target_classes=True,
    )

    X_train = train_df.drop(columns=[target])
    y_train = train_df[target]

    split_strategy = "internal_train_test_split"
    if test_data_path:
        test_df = _load_dataframe(test_data_path)
        print(f"Loaded test data: {len(test_df):,} rows / {test_df.shape[1]} columns.")
        test_df = _prepare_dataframe(
            test_df,
            target,
            drop_cols,
            filter_rare_target_classes=False,
        )

        X_test = test_df.drop(columns=[target]).reindex(columns=X_train.columns)
        y_test = test_df[target]

        # Metrics become misleading if the external test set contains labels unseen during training.
        seen_labels = set(y_train.unique().tolist())
        seen_mask = y_test.isin(seen_labels)
        dropped_unseen = int((~seen_mask).sum())
        if dropped_unseen:
            X_test = X_test.loc[seen_mask].reset_index(drop=True)
            y_test = y_test.loc[seen_mask].reset_index(drop=True)
            print(f"Dropped {dropped_unseen:,} test rows with unseen target labels.")
        if len(y_test) == 0:
            raise ValueError("No valid test rows remain after filtering unseen labels.")

        split_strategy = "external_test_dataset"
    else:
        X = train_df.drop(columns=[target])
        y = train_df[target]
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

    mlflow.sklearn.autolog(log_models=False)
    with mlflow.start_run() as run:
        pipeline = _build_pipeline(
            train_df,
            target,
            n_estimators=n_estimators,
            max_depth=max_depth,
        )
        pipeline.fit(X_train, y_train)

        mlflow.log_param("split_strategy", split_strategy)
        mlflow.log_param("train_rows", int(len(X_train)))
        mlflow.log_param("test_rows", int(len(X_test)))
        if not test_data_path:
            mlflow.log_param("test_size", test_size)
            mlflow.log_param("random_state", random_state)

        preds = pipeline.predict(X_test)
        metrics = {
            "accuracy": float(accuracy_score(y_test, preds)),
            "f1_weighted": float(f1_score(y_test, preds, average="weighted")),
        }
        if len(set(y_train)) == 2 and hasattr(pipeline, "predict_proba"):
            proba = pipeline.predict_proba(X_test)[:, 1]
            metrics["roc_auc"] = float(roc_auc_score(y_test, proba))

        for k, v in metrics.items():
            mlflow.log_metric(k, v)
        print("Test metrics:", metrics)
        print(classification_report(y_test, preds))

        eval_dir = Path("outputs/evaluation")
        if eval_dir.exists():
            shutil.rmtree(eval_dir)
        eval_dir.mkdir(parents=True, exist_ok=True)

        eval_payload = {
            "metrics": metrics,
            "train_rows": int(len(X_train)),
            "test_rows": int(len(X_test)),
            "split_strategy": split_strategy,
        }
        (eval_dir / "metrics.json").write_text(json.dumps(eval_payload, indent=2), encoding="utf-8")
        pd.DataFrame({"y_true": y_test, "y_pred": preds}).to_csv(eval_dir / "predictions.csv", index=False)
        mlflow.log_dict(eval_payload, "evaluation/metrics.json")
        mlflow.log_artifact(str(eval_dir / "predictions.csv"), artifact_path="evaluation")

        out = Path(output_dir)
        # mlflow.sklearn.save_model refuses to overwrite a non-empty dir;
        # clear any prior artifacts so re-runs don't error out.
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        mlflow.sklearn.save_model(pipeline, str(out))
        print(f"Saved model to {out.resolve()} (run_id={run.info.run_id})")

    return metrics


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", required=True, help="Path to MLTable folder, parquet, or csv")
    parser.add_argument("--target", required=True, help="Name of target column")
    parser.add_argument(
        "--test-data-path",
        default=None,
        help="Optional separate test dataset path (MLTable folder, parquet, or csv).",
    )
    parser.add_argument("--test-size", type=float, default=0.2)
    parser.add_argument("--output-dir", default="outputs/model")
    parser.add_argument(
        "--drop-cols",
        nargs="*",
        default=None,
        help="Feature columns to drop before training (e.g. leaky columns).",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=200,
        help="Number of trees in the RandomForest. Lower => smaller pickled model.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Max tree depth. Lower => smaller pickled model.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    train(
        data_path=args.data_path,
        target=args.target,
        test_data_path=args.test_data_path,
        test_size=args.test_size,
        output_dir=args.output_dir,
        drop_cols=args.drop_cols,
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
    )
