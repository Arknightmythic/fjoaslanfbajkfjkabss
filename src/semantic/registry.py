from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    expression: str
    description: str
    domain: str
    format: str = "number"


@dataclass(frozen=True)
class DimensionDefinition:
    name: str
    expression: str
    description: str
    domain: str
    filter_column: str
    requires_join: Optional[str] = None


@dataclass(frozen=True)
class JoinDefinition:
    name: str
    join_type: str
    table: str
    alias: str
    condition: str


@dataclass(frozen=True)
class DomainDefinition:
    name: str
    primary_table: str
    table_alias: str
    time_column: str
    description: str
    joins: dict[str, JoinDefinition] = field(default_factory=dict)
    metrics: dict[str, MetricDefinition] = field(default_factory=dict)
    dimensions: dict[str, DimensionDefinition] = field(default_factory=dict)


DOMAINS: dict[str, DomainDefinition] = {
    "grading": DomainDefinition(
        name="grading",
        primary_table="syncrono_service_grading_jobs",
        table_alias="g",
        time_column="g.created_at",
        description="Audit mutu dan penilaian data grading berkas",
        joins={
            "results": JoinDefinition(
                name="results",
                join_type="LEFT JOIN",
                table="syncrono_service_grading_results",
                alias="gr",
                condition="gr.job_id = g.job_id AND gr.phase = g.grading_phase",
            )
        },
        metrics={
            "grading_jobs": MetricDefinition(
                name="grading_jobs",
                expression="COUNT(*)",
                description="Total job grading berkas",
                domain="grading",
            ),
            "completed_jobs": MetricDefinition(
                name="completed_jobs",
                expression="COALESCE(SUM(CASE WHEN g.status = 'COMPLETED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job grading selesai (COMPLETED)",
                domain="grading",
            ),
            "failed_jobs": MetricDefinition(
                name="failed_jobs",
                expression="COALESCE(SUM(CASE WHEN g.status = 'FAILED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job grading gagal (FAILED)",
                domain="grading",
            ),
            "cancelled_jobs": MetricDefinition(
                name="cancelled_jobs",
                expression="COALESCE(SUM(CASE WHEN g.status = 'CANCELLED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job grading dibatalkan (CANCELLED)",
                domain="grading",
            ),
            "running_jobs": MetricDefinition(
                name="running_jobs",
                expression="COALESCE(SUM(CASE WHEN g.status = 'RUNNING' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job grading sedang berjalan (RUNNING)",
                domain="grading",
            ),
            "row_count": MetricDefinition(
                name="row_count",
                expression="COALESCE(SUM(g.row_count), 0)",
                description="Total akumulasi baris rekaman pada job grading",
                domain="grading",
            ),
            "unique_file_ids": MetricDefinition(
                name="unique_file_ids",
                expression="COUNT(DISTINCT g.file_id)",
                description="Jumlah identifikasi berkas unik (distinct file_id)",
                domain="grading",
            ),
            "unique_filenames": MetricDefinition(
                name="unique_filenames",
                expression="COUNT(DISTINCT g.filename)",
                description="Jumlah nama berkas fisik unik (distinct filename)",
                domain="grading",
            ),
        },
        dimensions={
            "day": DimensionDefinition(
                name="day",
                expression="DATE(g.created_at)",
                description="Tanggal kalender WIB (YYYY-MM-DD)",
                domain="grading",
                filter_column="DATE(g.created_at)",
            ),
            "date": DimensionDefinition(
                name="date",
                expression="DATE(g.created_at)",
                description="Alias tanggal kalender WIB",
                domain="grading",
                filter_column="DATE(g.created_at)",
            ),
            "week": DimensionDefinition(
                name="week",
                expression="YEARWEEK(g.created_at, 1)",
                description="Minggu kalender ISO (YYYYWW)",
                domain="grading",
                filter_column="YEARWEEK(g.created_at, 1)",
            ),
            "month": DimensionDefinition(
                name="month",
                expression="DATE_FORMAT(g.created_at, '%Y-%m')",
                description="Bulan kalender (YYYY-MM)",
                domain="grading",
                filter_column="DATE_FORMAT(g.created_at, '%Y-%m')",
            ),
            "status": DimensionDefinition(
                name="status",
                expression="g.status",
                description="Status job grading (COMPLETED, FAILED, CANCELLED, RUNNING)",
                domain="grading",
                filter_column="g.status",
            ),
            "institution": DimensionDefinition(
                name="institution",
                expression="g.institution_name",
                description="Nama kementerian atau lembaga pemilik data",
                domain="grading",
                filter_column="LOWER(g.institution_name)",
            ),
            "grade": DimensionDefinition(
                name="grade",
                expression="gr.grade_letter",
                description="Huruf mutu data hasil grading (A, B, C, D, E, F)",
                domain="grading",
                filter_column="gr.grade_letter",
                requires_join="results",
            ),
            "phase": DimensionDefinition(
                name="phase",
                expression="g.grading_phase",
                description="Fase grading (BEFORE, AFTER)",
                domain="grading",
                filter_column="g.grading_phase",
            ),
            "filename": DimensionDefinition(
                name="filename",
                expression="g.filename",
                description="Nama berkas",
                domain="grading",
                filter_column="g.filename",
            ),
            "file_id": DimensionDefinition(
                name="file_id",
                expression="g.file_id",
                description="ID berkas",
                domain="grading",
                filter_column="g.file_id",
            ),
        },
    ),
    "matching": DomainDefinition(
        name="matching",
        primary_table="syncrono_portal_matching_jobs",
        table_alias="m",
        time_column="m.created_at",
        description="Pemadanan identitas kependudukan WNI",
        metrics={
            "matching_jobs": MetricDefinition(
                name="matching_jobs",
                expression="COUNT(*)",
                description="Total job pemadanan identitas",
                domain="matching",
            ),
            "matching_completed_jobs": MetricDefinition(
                name="matching_completed_jobs",
                expression="COALESCE(SUM(CASE WHEN m.status = 'COMPLETED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job pemadanan selesai (COMPLETED)",
                domain="matching",
            ),
            "matching_failed_jobs": MetricDefinition(
                name="matching_failed_jobs",
                expression="COALESCE(SUM(CASE WHEN m.status = 'FAILED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job pemadanan gagal (FAILED)",
                domain="matching",
            ),
            "matching_running_jobs": MetricDefinition(
                name="matching_running_jobs",
                expression="COALESCE(SUM(CASE WHEN m.status = 'MATCHING' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job pemadanan aktif berjalan (MATCHING)",
                domain="matching",
            ),
            "matching_cancelled_jobs": MetricDefinition(
                name="matching_cancelled_jobs",
                expression="COALESCE(SUM(CASE WHEN m.status = 'CANCELLED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah job pemadanan dibatalkan (CANCELLED)",
                domain="matching",
            ),
            "total_incoming": MetricDefinition(
                name="total_incoming",
                expression="COALESCE(SUM(m.total_incoming), 0)",
                description="Total data masuk yang dipadankan",
                domain="matching",
            ),
            "total_candidates": MetricDefinition(
                name="total_candidates",
                expression="COALESCE(SUM(m.total_candidates), 0)",
                description="Total kandidat master identitas yang diperiksa",
                domain="matching",
            ),
            "auto_count": MetricDefinition(
                name="auto_count",
                expression="COALESCE(SUM(m.auto_count), 0)",
                description="Total rekaman cocok otomatis (Auto Match)",
                domain="matching",
            ),
            "review_count": MetricDefinition(
                name="review_count",
                expression="COALESCE(SUM(m.review_count), 0)",
                description="Total rekaman butuh peninjauan manual (Manual Review)",
                domain="matching",
            ),
            "unmatch_count": MetricDefinition(
                name="unmatch_count",
                expression="COALESCE(SUM(m.unmatch_count), 0)",
                description="Total rekaman tidak cocok (Unmatch)",
                domain="matching",
            ),
            "conflict_count": MetricDefinition(
                name="conflict_count",
                expression="COALESCE(SUM(m.conflict_count), 0)",
                description="Total rekaman terdapat konflik data (Conflict)",
                domain="matching",
            ),
        },
        dimensions={
            "day": DimensionDefinition(
                name="day",
                expression="DATE(m.created_at)",
                description="Tanggal kalender WIB (YYYY-MM-DD)",
                domain="matching",
                filter_column="DATE(m.created_at)",
            ),
            "date": DimensionDefinition(
                name="date",
                expression="DATE(m.created_at)",
                description="Alias tanggal kalender WIB",
                domain="matching",
                filter_column="DATE(m.created_at)",
            ),
            "week": DimensionDefinition(
                name="week",
                expression="YEARWEEK(m.created_at, 1)",
                description="Minggu kalender ISO (YYYYWW)",
                domain="matching",
                filter_column="YEARWEEK(m.created_at, 1)",
            ),
            "month": DimensionDefinition(
                name="month",
                expression="DATE_FORMAT(m.created_at, '%Y-%m')",
                description="Bulan kalender (YYYY-MM)",
                domain="matching",
                filter_column="DATE_FORMAT(m.created_at, '%Y-%m')",
            ),
            "status": DimensionDefinition(
                name="status",
                expression="m.status",
                description="Status job pemadanan (MATCHING, COMPLETED, FAILED, CANCELLED)",
                domain="matching",
                filter_column="m.status",
            ),
            "file_id": DimensionDefinition(
                name="file_id",
                expression="m.file_id",
                description="ID berkas yang dipadankan",
                domain="matching",
                filter_column="m.file_id",
            ),
        },
    ),
    "batch": DomainDefinition(
        name="batch",
        primary_table="syncrono_service_batches",
        table_alias="b",
        time_column="b.created_at",
        description="Proses pengolahan asinkronus batch dan part",
        metrics={
            "batch_count": MetricDefinition(
                name="batch_count",
                expression="COUNT(*)",
                description="Total jumlah batch",
                domain="batch",
            ),
            "batch_done": MetricDefinition(
                name="batch_done",
                expression="COALESCE(SUM(CASE WHEN b.status = 'DONE' THEN 1 ELSE 0 END), 0)",
                description="Jumlah batch selesai (DONE)",
                domain="batch",
            ),
            "batch_running": MetricDefinition(
                name="batch_running",
                expression="COALESCE(SUM(CASE WHEN b.status = 'RUNNING' THEN 1 ELSE 0 END), 0)",
                description="Jumlah batch berjalan (RUNNING)",
                domain="batch",
            ),
            "batch_cancelled": MetricDefinition(
                name="batch_cancelled",
                expression="COALESCE(SUM(CASE WHEN b.status = 'CANCELLED' THEN 1 ELSE 0 END), 0)",
                description="Jumlah batch dibatalkan (CANCELLED)",
                domain="batch",
            ),
            "batch_part_count": MetricDefinition(
                name="batch_part_count",
                expression="COALESCE(SUM(b.parts), 0)",
                description="Total akumulasi part pada batch",
                domain="batch",
            ),
            "batch_row_count": MetricDefinition(
                name="batch_row_count",
                expression="COALESCE(SUM(b.total_rows), 0)",
                description="Total baris data pada batch",
                domain="batch",
            ),
        },
        dimensions={
            "day": DimensionDefinition(
                name="day",
                expression="DATE(b.created_at)",
                description="Tanggal kalender WIB (YYYY-MM-DD)",
                domain="batch",
                filter_column="DATE(b.created_at)",
            ),
            "date": DimensionDefinition(
                name="date",
                expression="DATE(b.created_at)",
                description="Alias tanggal kalender WIB",
                domain="batch",
                filter_column="DATE(b.created_at)",
            ),
            "status": DimensionDefinition(
                name="status",
                expression="b.status",
                description="Status batch (DONE, CANCELLED, RUNNING)",
                domain="batch",
                filter_column="b.status",
            ),
        },
    ),
    "anomaly": DomainDefinition(
        name="anomaly",
        primary_table="syncrono_kl_records",
        table_alias="a",
        time_column="a.created_at",
        description="Analisis kualitas anomali data K/L",
        joins={
            "grading": JoinDefinition(
                name="grading",
                join_type="JOIN",
                table="syncrono_service_grading_jobs",
                alias="g",
                condition="g.job_id = a.grading_job_id AND g.file_id = a.file_id",
            )
        },
        metrics={
            "total_kl_rows": MetricDefinition(
                name="total_kl_rows",
                expression="COUNT(*)",
                description="Total baris data K/L yang diperiksa",
                domain="anomaly",
            ),
            "anomaly_rows": MetricDefinition(
                name="anomaly_rows",
                expression="COALESCE(SUM(CASE WHEN a.is_anomaly = 1 THEN 1 ELSE 0 END), 0)",
                description="Total baris data terdeteksi anomali",
                domain="anomaly",
            ),
            "clean_rows": MetricDefinition(
                name="clean_rows",
                expression="COALESCE(SUM(CASE WHEN a.is_anomaly = 0 THEN 1 ELSE 0 END), 0)",
                description="Total baris data bersih tanpa anomali",
                domain="anomaly",
            ),
            "anomaly_rate": MetricDefinition(
                name="anomaly_rate",
                expression="ROUND(COALESCE(SUM(CASE WHEN a.is_anomaly = 1 THEN 1 ELSE 0 END), 0) * 100.0 / NULLIF(COUNT(*), 0), 2)",
                description="Persentase tingkat anomali (persen)",
                domain="anomaly",
                format="percent",
            ),
        },
        dimensions={
            "day": DimensionDefinition(
                name="day",
                expression="DATE(a.created_at)",
                description="Tanggal kalender WIB (YYYY-MM-DD)",
                domain="anomaly",
                filter_column="DATE(a.created_at)",
            ),
            "date": DimensionDefinition(
                name="date",
                expression="DATE(a.created_at)",
                description="Alias tanggal kalender WIB",
                domain="anomaly",
                filter_column="DATE(a.created_at)",
            ),
            "anomaly_type": DimensionDefinition(
                name="anomaly_type",
                expression="a.anomaly_type",
                description="Tipe anomali (misalnya NIK_KECAMATAN_INVALID, EMPTY_NIK)",
                domain="anomaly",
                filter_column="a.anomaly_type",
            ),
            "file_id": DimensionDefinition(
                name="file_id",
                expression="a.file_id",
                description="ID berkas",
                domain="anomaly",
                filter_column="a.file_id",
            ),
            "institution": DimensionDefinition(
                name="institution",
                expression="g.institution_name",
                description="Nama institusi (join ke grading jobs)",
                domain="anomaly",
                filter_column="LOWER(g.institution_name)",
                requires_join="grading",
            ),
        },
    ),
}

METRIC_ALIASES: dict[str, str] = {
    "total_jobs": "grading_jobs",
    "jobs": "grading_jobs",
    "total_grading_jobs": "grading_jobs",
    "job_grading": "grading_jobs",
    "grading_selesai": "completed_jobs",
    "grading_gagal": "failed_jobs",
    "grading_batal": "cancelled_jobs",
    "total_rows": "row_count",
    "rows": "row_count",
    "baris": "row_count",
    "file_unik": "unique_file_ids",
    "unique_files": "unique_file_ids",
    "nama_file_unik": "unique_filenames",
    "matching": "matching_jobs",
    "total_matching": "matching_jobs",
    "matching_selesai": "matching_completed_jobs",
    "matching_gagal": "matching_failed_jobs",
    "matching_aktif": "matching_running_jobs",
    "auto_match": "auto_count",
    "manual_review": "review_count",
    "anomali": "anomaly_rows",
    "total_anomali": "anomaly_rows",
    "tingkat_anomali": "anomaly_rate",
    "persen_anomali": "anomaly_rate",
    "batch": "batch_count",
}

DIMENSION_ALIASES: dict[str, str] = {
    "tanggal": "day",
    "hari": "day",
    "minggu": "week",
    "bulan": "month",
    "institusi": "institution",
    "kementerian": "institution",
    "lembaga": "institution",
    "tipe_anomali": "anomaly_type",
    "jenis_anomali": "anomaly_type",
}


def resolve_metric_name(name: str) -> str:
    cleaned = name.strip().lower()
    return METRIC_ALIASES.get(cleaned, cleaned)


def resolve_dimension_name(name: str) -> str:
    cleaned = name.strip().lower()
    return DIMENSION_ALIASES.get(cleaned, cleaned)


def find_domain_for_query(
    metrics: list[str],
    dimensions: list[str],
    explicit_domain: Optional[str] = None,
) -> str:
    if explicit_domain and explicit_domain.lower() in DOMAINS:
        return explicit_domain.lower()

    resolved_metrics = [resolve_metric_name(m) for m in metrics]
    resolved_dims = [resolve_dimension_name(d) for d in dimensions]

    domain_votes: dict[str, int] = {}
    for d_name, domain in DOMAINS.items():
        score = 0
        for m in resolved_metrics:
            if m in domain.metrics:
                score += 3
        for dim in resolved_dims:
            if dim in domain.dimensions:
                score += 1
        if score > 0:
            domain_votes[d_name] = score

    if not domain_votes:
        return "grading"

    return max(domain_votes.items(), key=lambda x: x[1])[0]
