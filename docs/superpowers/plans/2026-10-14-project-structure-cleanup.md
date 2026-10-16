# Implementation Plan: Pembersihan Struktur Direktori Synchrono Chatbot

**User Request:** *"oke skrng sy ingin km rapiin struktur project nya, coba bikin plan nya dulu"*  
**Status:** Menunggu Persetujuan Pengguna (Awaiting Approval) — Tidak Ada Eksekusi Tanpa Izin  
**Agent Skill:** `subagent-driven-development`  
**Target:** Relokasi 8 launcher, 3 file SQL, dan 2 dokumen tanpa modifikasi kontrak runtime atau HTTP/SSE.

---

## 1. Goal, Architecture & Global Constraints

### Tujuan (Goal)
Merapikan root repository dengan memindahkan 8 file launcher ke `scripts/dev/`, 3 file SQL ke `scripts/sql/`, dan 2 panduan markdown root ke `docs/`. Launcher dapat dieksekusi dari direktori mana pun dengan CWD otomatis menuju root proyek.

### Arsitektur & Invarian Runtime
- **Runtime & Kode Sumber Tetap:** `main.py`, `api/`, `chatbot/`, `static/`, `evals/`, `Dockerfile`, `pyproject.toml`, dan `uv.lock` tidak diubah atau dipindahkan ke layout `src/`. Rangkaian uji fungsional yang ada (`tests/test_routes.py`) tetap dipertahankan tanpa perubahan; satu uji baru berbasis pustaka standar (`tests/check_project_structure.py`) ditambahkan khusus memvalidasi struktur file dan CWD launcher.
- **Import & Path Invariant:** `main.py:10-11` tetap mengimpor `api.routes` dan `chatbot.database`; `main.py:54` tetap merujuk static directory relatif; `chatbot/tools/skill.py:6-7` tetap terikat pada direktori `chatbot/skills/`.
- **Docker Compose:** Hanya host bind source baris `docker-compose.yml:28` yang diubah dari `./scripts/init_chatbot_db.sql` ke `./scripts/sql/init_chatbot_db.sql`. Baris `Dockerfile:35` (`COPY scripts/ /app/scripts/`) tidak diubah karena file tetap berada di bawah hierarki `scripts/`.
- **Perubahan Perintah Operasional:** Pemanggilan skrip root sengaja berubah (misal `bash scripts/dev/start_all.sh` dan `.\scripts\dev\start_all.ps1`). Tidak dibuat wrapper/shim di root demi menjaga kebersihan repositori.

### Batasan Global & Tech Stack
- **Tech Stack:** Python >=3.11 (`pyproject.toml:6`), FastAPI (`pyproject.toml:8`), LangChain (`pyproject.toml:11`), LangGraph (`pyproject.toml:13`), SQLAlchemy (`pyproject.toml:16`), psycopg, python-dotenv, uv, pytest >=8.3 (`pyproject.toml:21, 26-29`), Bash, PowerShell. (Docker Compose v5.1.1 adalah versi lokal terobservasi, bukan versi minimum baru yang diwajibkan).
- **Zero New Dependencies & Zero Secrets:** Pemeriksaan struktur dan tautan murni menggunakan stdlib. Validasi konfigurasi Docker Compose dilakukan offline (`--no-env-resolution --quiet`) tanpa membuka `.env` rahasia atau menyalakan container nyata.

---

## 2. Pemetaan Relokasi & Struktur Direktori Target

### Tabel Pemetaan File
| Path Asal (Source) | Path Tujuan (Destination) | Kategori | Tindakan |
|---|---|---|---|
| `start_all.sh` | `scripts/dev/start_all.sh` | Launcher | Pindah & perbarui CWD (`/../..`) |
| `start_all.ps1` | `scripts/dev/start_all.ps1` | Launcher | Pindah & perbarui CWD (`Join-Path '../..'`) |
| `start_db.sh` | `scripts/dev/start_db.sh` | Launcher | Pindah & perbarui CWD (`/../..`) |
| `start_db.ps1` | `scripts/dev/start_db.ps1` | Launcher | Pindah & perbarui CWD (`Join-Path '../..'`) |
| `stop_all.sh` | `scripts/dev/stop_all.sh` | Launcher | Pindah & perbarui CWD (`/../..`) |
| `stop_all.ps1` | `scripts/dev/stop_all.ps1` | Launcher | Pindah & perbarui CWD (`Join-Path '../..'`) |
| `stop_db.sh` | `scripts/dev/stop_db.sh` | Launcher | Pindah & perbarui CWD (`/../..`) |
| `stop_db.ps1` | `scripts/dev/stop_db.ps1` | Launcher | Pindah & perbarui CWD (`Join-Path '../..'`) |
| `scripts/init_chatbot_db.sql` | `scripts/sql/init_chatbot_db.sql` | Database SQL | Pindah byte-for-byte |
| `scripts/add_database_constraints.sql` | `scripts/sql/add_database_constraints.sql` | Database SQL | Pindah byte-for-byte |
| `scripts/add_schema_descriptions.sql` | `scripts/sql/add_schema_descriptions.sql` | Database SQL | Pindah byte-for-byte |
| `API_CONTRACT.md` | `docs/API_CONTRACT.md` | Dokumentasi | Pindah & sesuaikan relative links |
| `END_TO_END_GUIDE.md` | `docs/END_TO_END_GUIDE.md` | Dokumentasi | Pindah & sesuaikan relative links |

### Struktur Direktori Target
```text
synchrono-chatbot/
├── .env.example, Dockerfile, README.md, docker-compose.yml, pyproject.toml, uv.lock, main.py
├── api/ & chatbot/ & evals/ & static/
├── docs/
│   ├── API_CONTRACT.md, ARCHITECTURE_AND_EVALS.md, DEPLOYMENT_AND_CLONE_GUIDE.md
│   ├── END_TO_END_GUIDE.md, ENV_CONFIGURATION_GUIDE.md, FRONTEND_INTEGRATION_GUIDE.md
│   ├── TEAM_HANDOVER_AND_SERVICE_GUIDE.md, superpowers/plans/
├── scripts/
│   ├── dev/ (start_all.{sh,ps1}, start_db.{sh,ps1}, stop_all.{sh,ps1}, stop_db.{sh,ps1})
│   └── sql/ (add_database_constraints.sql, add_schema_descriptions.sql, init_chatbot_db.sql)
└── tests/ (check_project_structure.py, test_routes.py)
```

---

## 3. Preflight & Validasi Awal

Jalankan sebelum Task 1 & 2 dimulai:
1. **Catat Base Commit:** Simpan referensi hash commit awal agar komparasi tetap valid jika ada commit bertahap:
   ```bash
   BASE_COMMIT=$(git rev-parse HEAD)
   ```
2. **Pindai Rujukan Path yang Terlacak (Tracked Reference Scan):**
   ```bash
   git grep -n -E '(start|stop)_(all|db)\.(sh|ps1)|init_chatbot_db\.sql|API_CONTRACT\.md|END_TO_END_GUIDE\.md' || true
   ```
3. **Jalankan Baseline Pytest Suite Terisolasi (Offline & Tanpa Rahasia):**
   *(Catatan: Diekspektasikan 7 test di `tests/test_routes.py`. Uji ini TIDAK dijalankan selama penyusunan plan; angka 7 adalah ekspektasi, bukan bukti runtime. Rekam status baseline saat pengguna menyetujui implementasi).*
   ```bash
   uv run --frozen python -c "
   import os, sys, tempfile
   tdir = '/tmp/opencode' if os.path.exists('/tmp/opencode') else None
   with tempfile.TemporaryDirectory(dir=tdir) as tmpdir:
       db_path = os.path.join(tmpdir, 'conv.db')
       os.environ['PYTHON_DOTENV_DISABLED'] = '1'
       os.environ['POSTGRES_URI'] = f'sqlite:///{db_path}'
       os.environ['ANALYTICS_DB_URI'] = ''
       os.environ['ALLOWED_DB_SCHEMA'] = ''
       os.environ['USE_OPIK'] = 'false'
       os.environ['OPIK_API_KEY'] = ''
       os.environ['OPENAI_API_KEY'] = 'offline-test'
       import pytest
       sys.exit(pytest.main(['tests/test_routes.py', '-q']))
   "
   ```

---

## 4. Rincian Task Implementasi

### Task 1: Relokasi Launcher & Skrip SQL + Update Compose + Regression Test
**Owner:** Subagent (Scripts Lane — bertanggung jawab atas CWD, exact command logs, dan syntax check)

- [ ] **Langkah 1.1: Buat uji regresi struktural `tests/check_project_structure.py`**
  ```python
  import os, shutil, subprocess, tempfile
  from pathlib import Path

  ROOT = Path(__file__).resolve().parent.parent
  LAUNCHERS = ["start_all.sh", "start_all.ps1", "start_db.sh", "start_db.ps1",
               "stop_all.sh", "stop_all.ps1", "stop_db.sh", "stop_db.ps1"]
  SQL_FILES = ["init_chatbot_db.sql", "add_database_constraints.sql", "add_schema_descriptions.sql"]

  def test_paths_and_compose():
      for f in LAUNCHERS:
          assert not (ROOT / f).exists(), f"Old launcher still exists: {f}"
          assert (ROOT / "scripts" / "dev" / f).exists(), f"Missing new launcher: scripts/dev/{f}"
      for s in SQL_FILES:
          assert not (ROOT / "scripts" / s).exists(), f"Old SQL still exists: scripts/{s}"
          assert (ROOT / "scripts" / "sql" / s).exists(), f"Missing new SQL: scripts/sql/{s}"
      compose = (ROOT / "docker-compose.yml").read_text()
      assert "./scripts/sql/init_chatbot_db.sql:/docker-entrypoint-initdb.d/01_init_chatbot_db.sql:ro" in compose
      assert "./scripts/init_chatbot_db.sql:" not in compose

  def test_launcher_cwd_and_execution():
      tdir = "/tmp/opencode" if os.path.exists("/tmp/opencode") else None
      with tempfile.TemporaryDirectory(dir=tdir) as fix_str, tempfile.TemporaryDirectory(dir=tdir) as call_str:
          fixture, caller = Path(fix_str), Path(call_str)
          dev_dir, bin_dir = fixture / "scripts" / "dev", fixture / "bin"
          dev_dir.mkdir(parents=True); bin_dir.mkdir()
          for f in ["start_all.sh", "start_db.sh", "stop_all.sh", "stop_db.sh"]:
              shutil.copy2(ROOT / "scripts" / "dev" / f, dev_dir / f)
          (fixture / "docker-compose.yml").write_text("services: {}\n")
          (fixture / ".env.example").write_text("MOCK=1\n")
          log_file = fixture / "docker.log"
          fake_docker = bin_dir / "docker"
          fake_docker.write_text(f'#!/bin/sh\nif [ "$PWD" != "{fixture.resolve()}" ] || [ ! -f "docker-compose.yml" ]; then exit 2; fi\necho "$*" >> "{log_file.resolve()}"\nexit 0\n')
          fake_docker.chmod(0o755)
          fake_curl = bin_dir / "curl"
          fake_curl.write_text('#!/bin/sh\nexit 0\n'); fake_curl.chmod(0o755)
          env = os.environ.copy()
          env["PATH"] = f"{bin_dir.resolve()}:{env['PATH']}"

          assert not (fixture / ".env").exists(), "fixture .env must not exist before start_all"
          subprocess.run(["bash", str(dev_dir / "start_all.sh")], cwd=str(caller), env=env, timeout=10, check=True, capture_output=True)
          assert (fixture / ".env").read_text() == (fixture / ".env.example").read_text(), ".env content mismatch"
          assert not (caller / ".env").exists(), "start_all.sh created .env in caller dir"
          assert not (dev_dir / ".env").exists(), "start_all.sh created .env in scripts/dev dir"

          for script in ["start_db.sh", "stop_all.sh", "stop_db.sh"]:
              subprocess.run(["bash", str(dev_dir / script)], cwd=str(caller), env=env, timeout=10, check=True, capture_output=True)

          expected_calls = [
              "compose up -d --build",
              "compose up -d postgres-chatbot",
              "compose exec -T postgres-chatbot pg_isready -U synchrono -d synchrono_chatbot",
              "compose down",
              "compose stop postgres-chatbot"
          ]
          actual_calls = [line.strip() for line in log_file.read_text().splitlines() if line.strip()]
          assert actual_calls == expected_calls, f"Calls mismatch: {actual_calls} != {expected_calls}"

  if __name__ == "__main__":
      test_paths_and_compose()
      test_launcher_cwd_and_execution()
      print("ALL BASH STRUCTURAL CHECKS PASSED (PowerShell pending Windows/pwsh)")
  ```

- [ ] **Langkah 1.2: Eksekusi Uji RED Sebelum Relokasi Berkas**
  Jalankan script untuk membuktikan kondisi RED:
  ```bash
  python3 tests/check_project_structure.py || echo "Bukti RED: Test gagal sesuai ekspektasi karena file belum dipindahkan."
  ```

- [ ] **Langkah 1.3: Buat direktori dan pindahkan file launcher serta SQL**
  - Buat `scripts/dev/` dan `scripts/sql/`.
  - Pindahkan 8 file launcher dari root ke `scripts/dev/`.
  - Pindahkan 3 file SQL dari `scripts/` ke `scripts/sql/` (izin file git tetap 100644).

- [ ] **Langkah 1.4: Perbarui penanganan CWD pada skrip launcher**
  Karena skrip berada 2 tingkat di bawah root, perbarui resolusi root:
  - Pada `scripts/dev/start_all.sh` dan `stop_all.sh` (baris 4-5):
    ```bash
    # Lama: SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    cd "$SCRIPT_DIR"
    ```
  - Pada `scripts/dev/start_db.sh` dan `stop_db.sh` (baris 5-6):
    ```bash
    # Lama: DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
    DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )/../.." >/dev/null 2>&1 && pwd )"
    cd "$DIR"
    ```
  - Pada 4 skrip `.ps1` (`start_all.ps1`, `start_db.ps1`, `stop_all.ps1`, `stop_db.ps1`) (baris 3-4):
    ```powershell
    # Lama: Set-Location $ScriptDir
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    Set-Location (Join-Path $ScriptDir '../..')
    ```

- [ ] **Langkah 1.5: Perbarui bind volume pada `docker-compose.yml:28`**
  ```yaml
  # Lama: - ./scripts/init_chatbot_db.sql:/docker-entrypoint-initdb.d/01_init_chatbot_db.sql:ro
  - ./scripts/sql/init_chatbot_db.sql:/docker-entrypoint-initdb.d/01_init_chatbot_db.sql:ro
  ```

- [ ] **Langkah 1.6: Verifikasi Task 1 (Kondisi: GREEN)**
  ```bash
  for script in scripts/dev/*.sh; do bash -n "$script" || exit 1; done
  python3 tests/check_project_structure.py
  docker compose --env-file .env.example config --no-env-resolution --quiet
  ```

---

### Task 2: Relokasi Dokumen Root, Pembersihan Link Relatif, & Panduan Eksekusi
**Owner:** Subagent (Docs Lane — kepemilikan tunggal `README.md` dan `docs/`)

- [ ] **Langkah 2.1: Pindahkan dokumen root ke dalam `docs/`**
  - `API_CONTRACT.md` -> `docs/API_CONTRACT.md`
  - `END_TO_END_GUIDE.md` -> `docs/END_TO_END_GUIDE.md`

- [ ] **Langkah 2.2: Normalisasi 22 tautan `file:///` menjadi relatif + 1 output code formatting**
  Prefix absolut lokal yang dihapus: `file:///c:/Users/ISGS/Documents/kerjaan/syncrono_new/synchrono-chatbot/`
  Aturan resolusi:
  - Di `README.md` (7 tautan): Rujukan ke file dokumen menggunakan format `docs/<basename>` (`docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md`, `docs/ENV_CONFIGURATION_GUIDE.md`, `docs/DEPLOYMENT_AND_CLONE_GUIDE.md`, `docs/ARCHITECTURE_AND_EVALS.md`, `docs/FRONTEND_INTEGRATION_GUIDE.md`, `docs/API_CONTRACT.md`).
  - Di sesama dokumen `docs/*.md`: Rujukan dokumen tetangga menggunakan `./<basename>` (misal `docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md:397` merujuk `./FRONTEND_INTEGRATION_GUIDE.md`).
  - Di `docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md:136`: Mengarah ke `../scripts/sql/init_chatbot_db.sql`.
  - Di `docs/END_TO_END_GUIDE.md:182,189,196`: Mengarah ke `../static/index.html`, `../static/investigate.html`, dan `../static/preview.html`.
  - Di `docs/ARCHITECTURE_AND_EVALS.md`:
    - 6 path sumber chatbot: `../chatbot/handler.py` (baris 82, 196), `../chatbot/database/postgres.py` (baris 85), `../chatbot/prompts.py` (baris 89, 169), `../chatbot/middlewares/guardrail.py` (baris 107), `../chatbot/middlewares/pii.py` (baris 122), `../chatbot/database/query_engine.py` (baris 156).
    - 2 path evaluasi: `../evals/rubric.md` (baris 213), `../evals/test_cases.json` (baris 230).
    - Baris 258: Tautan ke file hasil `evals/results.json` diubah menjadi teks kode inline `evals/results.json` (bukan link berkas fisik karena tidak dilacak git).

- [ ] **Langkah 2.3: Perbarui panduan perintah eksekusi & hapus `chmod +x *.sh`**
  - Hapus instruksi usang `chmod +x *.sh` pada `README.md:86`, `docs/DEPLOYMENT_AND_CLONE_GUIDE.md:61`, dan `docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md:174`.
  - Nyatakan secara eksplisit bahwa semua perintah dijalankan dari root repositori: `bash scripts/dev/start_all.sh` (Linux/macOS) dan `.\scripts\dev\start_all.ps1` (Windows) pada `README.md:82-100`, `docs/DEPLOYMENT_AND_CLONE_GUIDE.md:57-99`, dan `docs/TEAM_HANDOVER_AND_SERVICE_GUIDE.md:170-175`.
  - Tambahkan representasi pohon direktori repositori di `README.md` yang mencerminkan struktur baru.

- [ ] **Langkah 2.4: Validasi seluruh tautan markdown lokal**
  Jalankan pemvalidasi mandiri berbasis bash + Python stdlib:
  ```bash
  python3 - <<'PY'
  from pathlib import Path
  import re, sys, urllib.parse

  targets = [Path("README.md")] + list(Path("docs").glob("*.md"))
  errors = []
  checked_count = 0

  for doc in targets:
      text = doc.read_text(encoding="utf-8")
      if "file:///" in text:
          errors.append(f"{doc}: Masih mengandung URI 'file:///'")
      for link in re.findall(r"\[.*?\]\((.*?)\)", text):
          link = link.strip()
          if not link or link.startswith("#") or re.match(r"^(https?|mailto):", link):
              continue
          clean = link.split("#")[0].split("?")[0]
          if clean:
              resolved = (doc.parent / urllib.parse.unquote(clean)).resolve()
              if not resolved.exists():
                  errors.append(f"{doc}: Tautan rusak -> '{link}' (resolusi: {resolved})")
              else:
                  checked_count += 1

  if errors:
      print("\n".join(errors), file=sys.stderr)
      sys.exit(1)
  print(f"OK: {checked_count} local markdown links verified successfully.")
  PY
  ```

---

### Task 3: Verifikasi Konsolidasi & Rekonsiliasi Invarian
**Owner:** Parent Orchestrator (bertanggung jawab atas baseline/final pytest, validasi compose, komparasi git invariant)

- [ ] **Langkah 3.1: Final Pytest Suite Terisolasi**
  Jalankan kembali perintah yang sama persis seperti pada **Bagian 3 (Preflight)**. Hasil eksekusi harus identik dengan rekaman baseline preflight tanpa kegagalan baru.

- [ ] **Langkah 3.2: Verifikasi Integritas File SQL terhadap `$BASE_COMMIT`**
  Pastikan tidak ada perubahan 1 byte pun pada file SQL:
  ```bash
  git show "$BASE_COMMIT":scripts/init_chatbot_db.sql | cmp - scripts/sql/init_chatbot_db.sql
  git show "$BASE_COMMIT":scripts/add_database_constraints.sql | cmp - scripts/sql/add_database_constraints.sql
  git show "$BASE_COMMIT":scripts/add_schema_descriptions.sql | cmp - scripts/sql/add_schema_descriptions.sql
  ```

- [ ] **Langkah 3.3: Verifikasi Invarian Kode Runtime terhadap `$BASE_COMMIT`**
  Pastikan tidak ada perubahan (baik staged maupun unstaged) pada file runtime:
  ```bash
  git diff "$BASE_COMMIT" --exit-code -- main.py api chatbot static evals pyproject.toml uv.lock Dockerfile
  ```

- [ ] **Langkah 3.4: Pengecekan Sintaks PowerShell / Explicit Verification Gap**
  ```bash
  if command -v pwsh >/dev/null 2>&1; then
      pwsh -NoProfile -Command "Get-ChildItem -Path scripts/dev/*.ps1 | ForEach-Object { [System.Management.Automation.Language.Parser]::ParseFile(\$_.FullName, [ref]\$null, [ref]\$null) }; Write-Host 'OK: PowerShell syntax valid'"
  else
      echo "GAP: pwsh tidak terpasang di host Linux ini. Sintaks dan eksekusi skrip .ps1 tetap PENDING hingga diverifikasi pada Windows."
  fi
  ```

- [ ] **Langkah 3.5: Saran Checkpoint Commit Git (Hanya dengan Izin Pengguna)**
  1. `refactor(scripts): move launchers to scripts/dev and sql to scripts/sql`
  2. `docs(structure): consolidate guides into docs and fix relative links`

---

## 5. Matriks Tanggung Jawab Validasi (Validation Ownership Budget)

| Domain Validasi | Pelaksana (Owner) | Perintah / Alat | Tolok Ukur Keberhasilan |
|---|---|---|---|
| CWD Launcher & Perilaku Script | Subagent (Scripts Lane) | `python3 tests/check_project_structure.py` | 5 pemanggilan docker tepat urutan; .env hanya di fixture root |
| Sintaks Bash Launcher | Subagent (Scripts Lane) | `for s in scripts/dev/*.sh; do bash -n "$s"; done` | Exit code 0 untuk semua skrip bash |
| Tautan Markdown & Path Obsolete | Subagent (Docs Lane) | Inline Python script di Task 2.4 | 0 tautan `file:///`, 0 tautan rusak, `chmod +x` usang dihapus |
| Konsistensi Docker Compose | Parent Orchestrator | `docker compose --env-file .env.example config ...` | Exit code 0, volume bind menunjuk `scripts/sql/` |
| Presisi Byte SQL | Parent Orchestrator | `git show "$BASE_COMMIT":... \| cmp - ...` | Exit code 0 (identik 100%) |
| Invarian Runtime | Parent Orchestrator | `git diff "$BASE_COMMIT" --exit-code -- ...` | Exit code 0 (tidak ada modifikasi kode runtime) |
| Konsistensi Test Suite | Parent Orchestrator | Isolated offline Pytest runner | Identik dengan baseline preflight (ekspektasi 7 test) |
| PowerShell Execution | Host Windows / Pengguna | PowerShell runtime | Ditandai PENDING (gap eksplisit Linux) |

---

## 6. Keterbatasan Verifikasi & Isu yang Ditunda (Deferred Issues)

### Keterbatasan Verifikasi (Explicit Gaps)
- **PowerShell Runtime:** Tidak ada binary `pwsh` pada host pengujian Linux. Verifikasi PowerShell ditandai PENDING hingga diuji di Windows.
- **Docker Daemon Isolation:** Seluruh pengujian launcher menggunakan fake binary (`bin/docker` dan `bin/curl`) pada temporary directory untuk menjamin tidak ada container nyata yang berjalan atau jaringan eksternal yang dihubungi.

### Isu yang Sengaja Ditunda (Deferred Issues)
1. **Missing import `re`:** Pada `chatbot/handler.py:60, :71` fungsi `re.sub` dan `re.search` digunakan tanpa import `re`. Ditunda agar tidak memicu perubahan kode di luar cakupan pembersihan struktur.
2. **Tool Tidak Terdaftar:** `get_table_detail` dan `get_table_names` tidak terdaftar aktif di handler tetapi `get_table_detail` dirujuk oleh prompt skill `chatbot/skills/mismatch_reasoning/SKILL.md:8`. Dibiarkan tetap ada.
3. **Runner Evaluasi:** `evals/run_eval.py`, `evals/run_judge.py`, dan `evals/e2e_judge.py` memiliki entrypoint terpisah dan tidak digabungkan.
4. **Isi Skrip SQL:** Skrip SQL tidak dijalankan atau diubah kontennya karena potensi konflik skema migrasi.

---

## 7. Gerbang Persetujuan (Approval Gate)

Dokumen ini merupakan perencanaan murni (**PLAN ONLY**). **Tidak ada implementasi kode, pemindahan/relokasi berkas fisik, maupun perubahan konfigurasi yang dieksekusi sebelum ada izin dan persetujuan eksplisit dari pengguna:**
> **"Apakah susunan relokasi ke `scripts/dev/`, `scripts/sql/`, dan `docs/` ini disetujui untuk diimplementasikan?"**
