# Menjalankan dan mengoperasikan lab

## Prasyarat

Gunakan Docker Desktop dengan Linux containers dan Compose v2 pada Windows, atau Docker Engine serta Compose v2 pada Linux. Host memerlukan Git dan Python 3.11 atau lebih baru untuk script pengendali. Node.js 22 dan dependency Playwright diperlukan bila ingin membuat screenshot otomatis.

Jenkins controller serta agent memakai Java 21 di container. Instalasi Java 17 native tidak perlu diubah. Tool Go untuk aplikasi berasal dari Dockerfile ReserveFlow yang dipatok, sehingga Go native tidak diperlukan. Sediakan sumber daya untuk satu build pada satu waktu; lab ini dirancang untuk laptop RAM 8 GB.

Pada workspace Windows pengembangan, proyek berada di drive D. Script proyek tidak mengubah lokasi data global Docker Desktop, instalasi Java, atau repository ReserveFlow asal.

## Menyalakan pada Windows

Dari root repository lab:

```powershell
.\scripts\Start.ps1
```

[Start.ps1](../scripts/Start.ps1) membuat konfigurasi privat bila belum ada, membangun image satu per satu, menyalakan engine dan controller, menyiapkan job serta secret agent, lalu menyalakan agent. Startup pertama mengunduh image dan plugin yang dipatok sehingga waktunya bergantung pada koneksi serta cache lokal. `-NoBuild` memakai image lab yang sudah dibangun:

```powershell
.\scripts\Start.ps1 -NoBuild
```

Buka Jenkins di `http://127.0.0.1:8110/`. Baca username dan password dari berkas lokal `.local/LOCAL-CREDENTIALS.txt` yang dihasilkan script. Berkas itu diabaikan Git dan tidak boleh ikut screenshot atau artifact. Jangan menyalin nilai secret ke issue, console publik, maupun dokumentasi.

Job bernama `reserveflow-release`. Gateway API berada di `http://127.0.0.1:8111`. Sebelum deployment sehat pertama, gateway belum memiliki release aktif sehingga belum dapat melayani API.

## Menjalankan verifikasi lengkap

```powershell
.\scripts\Verify.ps1
```

[Verify.ps1](../scripts/Verify.ps1) menjalankan tes release engine, kemudian [verify_jenkins.py](../scripts/verify_jenkins.py) memakai API Jenkins untuk menjalankan lima build berurutan: dua deployment sehat, kandidat tidak sehat, manual rollback, dan gangguan setelah cutover. Dua build gangguan wajib berstatus `FAILURE`; verifier memeriksa bahwa layanan tetap atau kembali sehat.

Verifier melakukan perubahan nyata pada resource milik lab. Kandidat tidak sehat memakai slot previous dan mengganti container release sehat sebelumnya; manual rollback kemudian harus membuat ulang image release tersebut. Jalankan saat tidak ada build manual yang sedang berjalan. Sentinel database berisi produk sintetis untuk memeriksa bahwa pergantian image tidak mengganti database deployment.

Laporan ringkas publik ada di `.local/verification.json`, termasuk metadata dan hasil build yang diperiksa. Berkas ini merupakan hasil lokal, bukan source yang disimpan dalam repository. Angka dan hasil yang boleh diklaim tersedia pada [catatan verifikasi](VERIFICATION.md).

## Menjalankan job dari UI

1. Login lalu buka `reserveflow-release`.
2. Pilih `Build with Parameters` dan nilai `ACTION`.
3. Buka nomor build pada build history.
4. Periksa stage dan console. Pada build yang menjalankan tes, buka test result JUnit.
5. Buka artifact laporan, kemudian cocokkan `release`, `image_id`, source aplikasi, source lab, dan build.

`DEPLOY_GOOD` menjalankan alur normal. `DEPLOY_UNHEALTHY` membuat kandidat gagal health gate sebelum cutover. `ROLLBACK` memulihkan previous image ID. `DEPLOY_POSTCHECK_FAIL` menghentikan kandidat setelah cutover dan memeriksa pemulihan old release.

Manual rollback memerlukan setidaknya dua release sehat yang tercatat. Build pertama belum memiliki previous release. Jangan mengubah file state secara manual untuk membuat tampilan rollback seolah berhasil.

## Menyalakan pada Linux atau runner CI

Urutan di bawah sama dengan bootstrap Windows. Pada CI, isi `--git-ref` dengan SHA checkout agar job Jenkins memakai source lab yang sedang diverifikasi. Untuk pemakaian lokal terhadap branch publik, hilangkan argumen tersebut.

```bash
python scripts/init_env.py --git-ref "$GITHUB_SHA"
docker compose build controller
docker compose build agent
docker compose build engine
docker compose up -d engine controller
python scripts/bootstrap.py --timeout 600
docker compose up -d --no-deps agent
python scripts/bootstrap.py --wait-agent --timeout 300
python -m unittest discover -s tests -v
python scripts/verify_jenkins.py --timeout 1800
```

[init_env.py](../scripts/init_env.py) menghasilkan secret acak 64 karakter hex dan mempertahankan nilai yang sudah ada. [bootstrap.py](../scripts/bootstrap.py) memerlukan controller terautentikasi, memeriksa 0 executor, mengambil secret inbound node secara privat, dan membuat job Pipeline from SCM. Mode `--wait-agent` memeriksa agent online serta 1 executor.

Jangan mengganti secret database pada konfigurasi lalu berharap database yang sudah berisi data ikut mengganti password. Volume PostgreSQL mempertahankan kredensial awalnya. Rotasi memerlukan prosedur database yang disengaja.

## Screenshot Jenkins

Setelah verifikasi menghasilkan build history, pasang dependency proyek dan browser screenshot:

```powershell
$env:npm_config_cache = Join-Path (Get-Location) '.local/npm-cache'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.local/browsers'
npm ci
npx playwright install chromium
node .\scripts\capture-ui.mjs
```

Jalankan instalasi dan capture pada terminal yang sama dari root repository. Kedua variabel environment hanya berlaku pada proses PowerShell tersebut dan menempatkan cache di direktori proyek pada drive D; perintah ini tidak mengubah pengaturan Windows permanen.

[capture-ui.mjs](../scripts/capture-ui.mjs) membuka UI klasik Jenkins, menggunakan kredensial lokal untuk login, dan menangkap halaman bukti. Gambar disimpan pada [screenshots/](screenshots/), sedangkan `.local/ui-checks.json` mencatat pemeriksaannya. Screenshot harus berasal dari Jenkins yang sedang berjalan, dengan nilai secret tidak terlihat.

Pada runner Ubuntu, workflow memasang browser dengan `npx playwright install --with-deps chromium`. GitHub Actions mengunggah hanya file publik yang disebut eksplisit pada [workflow verifikasi](../.github/workflows/verify.yml), sesudah pemeriksaan materi secret.

## Image runtime dari CI

Ekspor image hanya berjalan ketika operator memilih workflow manual dan mengaktifkan input `export_runtime_images`. Nilai awalnya `false`; push biasa tidak mengekspor atau mengunggah image runtime. Bila diaktifkan, workflow mengekspor tiga image hasil build sebelum container pertama dinyalakan sebagai artifact `runtime-images` dengan retensi satu hari.

Ekspor memakai daftar image dari Compose dan `docker save`, sehingga isinya adalah image controller, agent, dan engine. Ekspor ini tidak mengambil volume, controller home, env file, sertifikat yang baru dibuat saat runtime, database, atau cache daemon dalam DinD.

Artifact image bersifat opsional dan terpisah dari artifact bukti pengujian. Bila dipakai untuk mempercepat startup lokal, catat run CI serta source yang menghasilkan image tersebut. Memuat image hasil CI tidak berarti host lokal membangun sendiri image itu. Rangkaian Jenkins tetap perlu dijalankan untuk mendapatkan bukti runtime lokal.

## Menghentikan lab

```powershell
.\scripts\Stop.ps1
```

[Stop.ps1](../scripts/Stop.ps1) menghentikan Compose project milik lab tanpa menghapus volume. Perintah Linux yang setara:

```bash
docker compose down --remove-orphans
```

Data controller, workspace agent, state release, sertifikat client, dan daemon DinD berada pada named volume Compose. Database deployment berada pada volume di dalam daemon DinD, sehingga datanya bergantung pada volume data daemon tersebut. Prosedur normal tidak memakai `down -v`, `docker system prune`, atau penghapusan volume global.

Jenkins lokal hanya perlu menyala ketika lab sedang dijalankan atau diperiksa. Publikasi repository serta screenshot tidak membuat controller menjadi layanan publik.

## Penyimpanan dan kredensial

| Lokasi | Peran | Boleh dipublikasikan? |
|---|---|---|
| `.env` | Konfigurasi privat startup dan secret controller | Tidak |
| `.local/agent.env` | Secret koneksi inbound agent | Tidak |
| `.local/LOCAL-CREDENTIALS.txt` | Salinan lokal agar operator dapat login | Tidak |
| Volume `controller_home` | Konfigurasi, credentials terenkripsi Jenkins, dan build history | Tidak |
| Volume `agent_workspace` | Checkout lab dan checkout privat upstream pada agent | Tidak |
| Volume `lab_state` | State deployment dan env file privat runtime | Tidak |
| Volume `engine_data` | Image, container dan volume database daemon DinD | Tidak |
| Laporan JSON/XML yang diaudit | Hasil skenario tanpa nilai secret | Ya, setelah guard lulus |
| [screenshots/](screenshots/) | Halaman Jenkins terpilih | Ya, setelah diperiksa |

## Troubleshooting

| Gejala | Pemeriksaan |
|---|---|
| Port 8110 atau 8111 sudah dipakai | Hentikan instance lab lama; periksa pemilik proses sebelum mengubah atau menghentikan layanan lain |
| Controller belum siap | Tunggu startup plugin dan gunakan bootstrap dengan timeout yang tersedia; periksa log secara lokal tanpa mengunggahnya |
| Build menunggu agent | Periksa `builder` online, label `release-builder`, secret agent yang telah di-bootstrap dan koneksi WebSocket controller |
| Docker client gagal TLS | Periksa health `engine` dan mount sertifikat client; jangan menonaktifkan verifikasi TLS untuk menutupi masalah |
| Tes database dilewati | Periksa laporan Go/JUnit; gate memang menolak tes wajib yang `SKIP` atau `MISSING` |
| Kandidat tidak sehat gagal | Untuk `DEPLOY_UNHEALTHY`, cocokkan `FAILURE` dengan active release yang tidak berubah |
| Post-check gagal | Untuk `DEPLOY_POSTCHECK_FAIL`, periksa `switched`, `recovered`, recovery smoke, image aktif dan sentinel |
| Rollback tidak punya previous | Jalankan dua deployment sehat terlebih dahulu |
| Image previous tidak ada | Rollback memerlukan image ID yang masih tersimpan pada daemon lab; jangan melakukan prune selama demonstrasi |
| Report guard menolak archive | Periksa laporan privat secara lokal dan perbaiki sumber kebocoran atau format; jangan melewati guard |

Jangan mengatasi masalah lab dengan menonaktifkan autentikasi, memasang socket Docker host, menerbitkan port database/daemon, atau menghapus volume berisi data. Konfigurasi normal sudah menyediakan jalur bootstrap dan pemeriksaan yang terbatas pada resource lab.
