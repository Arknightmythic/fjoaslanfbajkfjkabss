# Chatbot synchrono di Kubernetes

Manifest untuk menjalankan chatbot di cluster RKE2 kantor, namespace `syncrono` (bersama portal dan
engine).

| Berkas | Isi |
|---|---|
| `kustomization.yaml`, `chatbot.yaml` | API (+ initContainer migrasi, + container pengarsip log), document worker, celery beat, PVC data, Service NodePort 31801 |
| `config.env` | setelan bukan rahasia → ConfigMap `synchrono-chatbot-config` |
| `secret.env.example` | daftar kunci rahasia → Secret `synchrono-chatbot-secret` (dibuat sendiri) |
| `pendukung/` | PostgreSQL pgvector + Valkey bundle khusus chatbot (StatefulSet + PVC + NetworkPolicy) |

## Layanan di cluster (dicek 1 Nov 2026)

| Kebutuhan chatbot | Di cluster | Dipakai? |
|---|---|---|
| PostgreSQL + **pgvector** | `database/postgres` (postgres:16) | **Tidak**: ekstensi `vector` tidak tersedia → `pendukung/postgres.yaml` |
| Valkey + **modul search** (cache semantik `FT.*`) + broker Celery | `valkey/valkey` | **Tidak**: valkey polos tanpa modul, tanpa persistensi, `allkeys-lru` → `pendukung/valkey.yaml` |
| S3 dokumen & arsip log | `seaweedfs/seaweedfs` | **Ya**: `seaweedfs.seaweedfs.svc:8333`; bucket `chatbot-documents` dan `chatbot-logs` dibuat otomatis |
| StarRocks (tabel engine) | `starrocks/starrocks` | **Ya**: `starrocks.starrocks.svc:9030`, DB `syncrono_starrocks_v002` |
| LLM + embedding | ollama-proxies docker di 107 (`:11435`) | **Ya**, tetap di docker. `ai-gateway` di cluster belum dicek kecocokannya |
| Registry image | `registry.digie-tekno.com`, pull secret `gitlab-registry` | Image chatbot perlu di-push |

## Perubahan kode untuk kube

- **Arsip log harian.** Task arsip membaca berkas trace milik API. Di docker, document worker
  berbagi `./data` dengan API; di kube pod-nya terpisah. Antrean task arsip kini diatur lewat
  `CHATBOT_LOG_QUEUE` (bawaan `document_ingest`, perilaku docker tidak berubah). Di kube nilainya
  `chatbot_logs` dan dikonsumsi container `log-archiver` di pod API, yang berbagi `/app/data`.
- **Password Valkey.** Cache semantik membaca `VALKEY_PASSWORD` (atau `REDIS_PASSWORD`).
- **UID tetap.** User `synchrono` dipatok uid/gid 999 (sama dengan sebelumnya), sehingga pod
  memakai `runAsUser`/`fsGroup`, tanpa jalan sebagai root dan `chown` saat start.

## Langkah

### 1. Image

```bash
docker build -t registry.digie-tekno.com/product/synchrono-chatbot:kube-mvp .
docker push registry.digie-tekno.com/product/synchrono-chatbot:kube-mvp
```

Nama dan tag ada di `kustomization.yaml` (`images:`).

### 2. Secret (sebelum pendukung)

```bash
cp kube/secret.env.example kube/secret.env     # isi; berkas ini di-.gitignore
kubectl -n syncrono create secret generic synchrono-chatbot-secret \
  --from-env-file=kube/secret.env --dry-run=client -o yaml | kubectl apply -f -
```

### 3. PostgreSQL + Valkey chatbot (sekali)

```bash
kubectl apply -k kube/pendukung
kubectl -n syncrono rollout status sts/synchrono-chatbot-db
kubectl -n syncrono rollout status sts/synchrono-chatbot-valkey
```

### 4. Chatbot

```bash
kubectl apply -k kube
kubectl -n syncrono logs deploy/synchrono-chatbot-api -c migrate     # alembic upgrade head
kubectl -n syncrono get pods -l app.kubernetes.io/name=synchrono-chatbot
curl -s http://192.168.2.9:31801/api/v1/health
```

### 5. Arahkan portal

Portal memakai `CHATBOT_URL` di Secret `syncrono-env`, sekarang `http://192.168.2.107:8001` (docker,
sudah dimatikan). Ganti ke `http://synchrono-chatbot:8000` lalu restart portal (wewenang tim portal).

## Data lama di docker 107

Riwayat percakapan, knowledge, dan vektornya ada di volume docker `synchrono_chatbot_data`
(PostgreSQL); dokumen knowledge ada di `synchrono_seaweedfs_data` (SeaweedFS chatbot). Container-nya
sudah dihentikan, volumenya masih ada. Bila perlu dipindah:

1. Nyalakan sementara `synchrono-chatbot-db`, lalu `pg_dump -Fc` dan pulihkan dengan `pg_restore` ke
   `synchrono-chatbot-db` di kube (lewat `kubectl port-forward`).
2. Salin bucket `chatbot-documents` (dan `chatbot-logs` bila perlu) dari SeaweedFS chatbot docker ke
   SeaweedFS kube, misalnya dengan `aws s3 sync` / `rclone`.

Tanpa pemindahan, chatbot kube mulai dengan basis data kosong (migrasi membuat skemanya) dan
knowledge perlu diunggah ulang.

## Catatan

- **Akses keluar.** Reranker fastembed mengunduh modelnya saat pertama dipakai (disimpan di PVC
  `synchrono-chatbot-data`), jadi pod API butuh internet sekali itu.
- **DB_USER StarRocks.** Di 107 chatbot memakai `root`. Lebih aman memakai user baca-saja.
- **Skala.** API satu replika (PVC ReadWriteOnce dan pengarsip log di pod yang sama). Document
  worker boleh ditambah `replicas`. Beat harus tepat satu.
