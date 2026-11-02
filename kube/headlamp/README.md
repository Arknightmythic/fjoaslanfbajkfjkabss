# Deploy chatbot lewat Headlamp

Untuk deploy tanpa kubectl: tempel berkas di folder ini ke Headlamp
(http://192.168.2.9:30880/c/main, login dengan token ServiceAccount dari tim infra).

Image chatbot tetap harus sudah ada di registry (`kube/README.md` langkah 1). Headlamp hanya
menjalankan image, tidak membangunnya.

| Urutan | Berkas | Isi |
|---|---|---|
| 1 | `1-secret.yaml` | Secret `synchrono-chatbot-secret` berisi nilai (di-.gitignore, tidak ada di git). Belum ada? Salin `1-secret.example.yaml` lalu isi |
| 2 | `2-pendukung.yaml` | PostgreSQL pgvector + Valkey bundle; tunggu Running (Workloads → StatefulSets) |
| 3 | `3-chatbot.yaml` | ConfigMap, PVC, API (+ migrasi + pengarsip log), document worker, beat, Service NodePort 31801 |

Secret harus ada sebelum langkah 2: PostgreSQL membaca `INTERNAL_PASSWORD` darinya. Langkah 1 dan 2
bisa dikerjakan sebelum image siap: PostgreSQL dan Valkey memakai image publik.

## Cara

1. Klik **Create** (ikon +), tempel isi satu berkas, lalu klik **Apply**.
2. Cek di **Workloads → Pods**. Log migrasi ada di pod API, container `migrate`.
3. Perubahan berikutnya: pakai **Edit** pada resource-nya. Create ulang resource yang sudah ada
   ditolak ("already exists").

## Render ulang

`2-pendukung.yaml` dan `3-chatbot.yaml` adalah hasil render `kube/`. Setelah mengubah
`kube/*.yaml` atau `kube/config.env`, render ulang dari akar repo:

```bash
kubectl kustomize kube/pendukung > kube/headlamp/2-pendukung.yaml
kubectl kustomize kube > kube/headlamp/3-chatbot.yaml
```

Nama ConfigMap ikut berubah (akhiran hash) setiap `config.env` berubah. Tempel ulang
`3-chatbot.yaml` utuh agar Deployment memakai ConfigMap yang baru.
