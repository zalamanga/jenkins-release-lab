# Panduan kode per file dan fungsi

Panduan ini memakai bahasa Indonesia untuk menjelaskan alur lab. Mulai dari definisi pipeline, kemudian baca batas Docker dan state, lalu deployment. Source aplikasi ReserveFlow tetap berada di repository asal; lab hanya mengambil commit yang tercatat pada lock ke workspace privat Jenkins.

## Peta baca

| Urutan | Berkas | Pertanyaan yang dijawab |
|---|---|---|
| 1 | [Jenkinsfile](../Jenkinsfile) | Apa yang Jenkins jalankan dan bukti apa yang disimpan? |
| 2 | [upstream.lock.json](../upstream.lock.json) | Source aplikasi dan tes wajib mana yang dipakai? |
| 3 | [versions.lock.json](../versions.lock.json) | Image runtime serta versi Jenkins mana yang dipatok? |
| 4 | [fetch_upstream.py](../scripts/fetch_upstream.py) | Bagaimana pipeline mengambil source tanpa mengubah repo asal? |
| 5 | [release.py](../scripts/release.py) | Bagaimana command pipeline masuk ke release engine? |
| 6 | [core.py](../src/release_lab/core.py) | Bagaimana penulisan state, lock dan operasi Docker dibatasi? |
| 7 | [junit.py](../src/release_lab/junit.py) | Bagaimana hasil Go nyata menjadi laporan Jenkins? |
| 8 | [smoke.py](../src/release_lab/smoke.py) | Bagaimana deployment diperiksa melalui HTTP? |
| 9 | [engine.py](../src/release_lab/engine.py) | Bagaimana kandidat diuji, trafik berpindah, dan rollback bekerja? |

## Jenkinsfile

[Jenkinsfile](../Jenkinsfile) adalah Declarative Pipeline. `agent { label 'release-builder' }` memilih node yang memiliki tool lab. Controller tidak memiliki executor, sehingga pekerjaan shell berjalan pada agent.

`skipDefaultCheckout(true)` membuat tahap checkout terlihat sebagai stage tersendiri. `disableConcurrentBuilds()` mencegah dua build pada job yang sama berjalan bersamaan. `timeout` membatasi satu build, dan `buildDiscarder` membatasi build history yang dipertahankan.

Parameter `ACTION` memiliki empat nilai. Deploy normal, kandidat tidak sehat, dan gangguan setelah cutover melewati fetch, tes, serta package. Rollback memakai image yang telah tersimpan, sehingga melewati ketiga tahap tersebut.

| Stage | Penjelasan |
|---|---|
| `Checkout` | `checkout scm` mengambil repository lab yang mendefinisikan job, lalu membersihkan laporan build sebelumnya pada workspace tersebut |
| `Fetch pinned upstream` | Memanggil fetch ReserveFlow sesuai commit penuh pada lock |
| `PostgreSQL tests` | Mengikat kredensial database tes hanya untuk command tes |
| `Package immutable release` | Membangun image rilis dan mencatat image ID serta identitas source |
| `Deploy or rollback` | Mengikat kredensial runtime lalu menjalankan health gate dan perubahan trafik |
| `Gateway post-check` | Menjalankan pemeriksaan HTTP tambahan melalui gateway pada release terpilih |

Blok `post { always { ... } }` memproses hasil meskipun stage sebelumnya gagal. Command `audit-reports` memeriksa laporan sebelum publikasi. `junit` menampilkan test result, sedangkan `archiveArtifacts` menyimpan laporan JSON/XML bersama build. `allowEmptyResults` mendukung rollback yang tidak menjalankan ulang tes; command tes sendiri tetap menolak hasil wajib yang tidak ada. Lihat [JUnit Jenkins](https://www.jenkins.io/doc/pipeline/steps/junit/) dan [tests/artifacts](https://www.jenkins.io/doc/pipeline/tour/tests-and-artifacts/).

Binding `withCredentials` membatasi kapan command menerima secret. Masking Jenkins membantu tampilan console, tetapi kode tetap perlu menghindari mencetak secret atau mengarsipkan berkas privat.

## Lock source dan runtime

[upstream.lock.json](../upstream.lock.json) menyimpan URL source aplikasi, commit penuh, target Docker `tests` dan `runtime`, serta daftar tes Go yang diwajibkan. Engine memakai daftar tersebut untuk menolak test run yang tidak lengkap.

[versions.lock.json](../versions.lock.json) menyimpan referensi image dengan digest. Tag mudah dibaca manusia, sedangkan digest mematok manifest yang dipakai. Berkas ini juga menunjuk lock plugin Jenkins. Mengganti lock merupakan perubahan konfigurasi yang perlu diverifikasi ulang; keberadaan digest bukan bukti bahwa suatu runtime sudah diuji.

## Pengambilan source aplikasi

Fungsi `fetch(root)` pada [fetch_upstream.py](../scripts/fetch_upstream.py) memvalidasi commit penuh, menyiapkan checkout privat, memeriksa origin, menolak perubahan lokal, lalu melakukan shallow fetch dan detached checkout. Setelah checkout, fungsi membandingkan `HEAD` dengan lock.

Fungsi `git(*args)` di dalam `fetch` menjalankan Git pada direktori checkout tersebut dengan batas waktu. Pesan gagal keluar dalam bentuk ringkas agar command privat tidak ikut tercetak. Blok utama memilih root dari lokasi script dan mengembalikan exit code 1 bila fetch tidak memenuhi syarat.

## Pintu masuk CLI

Fungsi `main()` pada [release.py](../scripts/release.py) membaca command, membuat `Engine`, lalu memanggil method command itu. `LabError` memuat pesan yang aman untuk console publik. Exception lain menghasilkan pesan umum karena pesan library atau CLI bisa memuat input privat.

`BUILD_NUMBER` dan `GIT_COMMIT` berasal dari Jenkins. Engine membentuk release ID dari commit lab dan nomor build. `WORKSPACE` menentukan lokasi laporan, dan `LAB_STATE_DIR` menunjuk state persisten lab. CLI ini dirancang untuk konteks agent, bukan pengganti tombol build dengan environment yang ditebak di host.

## Fondasi pada core.py

| Fungsi atau kelas pada [core.py](../src/release_lab/core.py) | Cara kerjanya |
|---|---|
| `LabError` | Menandai kegagalan dengan alasan yang boleh muncul pada console atau laporan publik |
| `atomic_write` | Menulis file sementara di direktori tujuan, melakukan flush dan fsync, lalu mengganti tujuan secara atomik; mode privat membatasi izin berkas |
| `write_json` | Mengubah nilai menjadi JSON stabil dan menulisnya melalui `atomic_write` |
| `read_json` | Membaca JSON bila ada, atau mengembalikan nilai awal yang diberikan pemanggil |
| `state_lock` | Mengunci perubahan state dengan locking file sesuai OS, lalu melepas lock pada akhir blok |
| `private_env` | Menolak newline, null byte, dan key environment yang tidak sesuai; menulis env file privat tanpa mencetak nilainya |
| `Docker.run` | Menjalankan Docker dengan batas waktu dan keluaran yang ditangkap; kegagalan hanya meneruskan nama operasi dan exit code |
| `Docker.container` | Membaca ID, image ID, status running, serta label container melalui format inspect terbatas |
| `Docker.image` | Membaca image ID dan label image tanpa mencetak seluruh konfigurasi environment |
| `Docker.assert_owned` | Memeriksa label pemilik sebelum engine menggunakan atau mengubah container |
| `Docker.remove` | Menghapus container hanya setelah pemeriksaan kepemilikan |
| `Docker.stop` | Menghentikan container hanya setelah pemeriksaan kepemilikan |
| `Docker.ensure_resource` | Membuat network atau volume berlabel; menolak resource bernama sama yang bukan milik lab |
| `wait_until` | Mengulang predicate sampai berhasil atau sampai batas waktu health gate habis |

Label kepemilikan mencegah engine mengubah resource bernama sama yang tidak dibuat untuk lab. Ini melengkapi daemon DinD tersendiri; keduanya tidak mengubah privileged DinD menjadi sandbox produksi.

## Konversi hasil tes

`go_results(stdout, returncode, expected)` pada [junit.py](../src/release_lab/junit.py) membaca baris hasil tes Go. Setiap tes yang tercantum pada lock harus benar-benar berstatus `PASS`, dan proses tes harus keluar dengan code 0. Tes yang tidak muncul diberi status `MISSING`; `SKIP` juga menggagalkan gate.

`junit_xml(report)` pada [junit.py](../src/release_lab/junit.py) membuat elemen testcase dari hasil tersebut. Tes gagal atau hilang memiliki failure. Tes skip memiliki elemen skipped, dan exit code proses yang gagal mendapat testcase harness bila diperlukan. Jenkins dapat menampilkan hasil nyata tersebut tanpa membuat hasil lulus fiktif.

## HTTP smoke

| Fungsi pada [smoke.py](../src/release_lab/smoke.py) | Peran |
|---|---|
| `request` | Mengirim request JSON dengan timeout, membaca response yang dibatasi, serta mengambil header replay dan metadata gateway; response 4xx tetap dapat diperiksa |
| `health` | Memerlukan HTTP 200 serta payload health dengan status `ok`; gangguan koneksi mengembalikan false |
| `run_smoke` | Membuat SKU dan idempotency key sintetis, menjalankan rangkaian request, dan memeriksa isi response penting |
| `call` di dalam `run_smoke` | Mencatat method, path, expected status dan status aktual; bila ada expected release, mencocokkan header slot/release gateway |

Dua belas request mencakup health, penolakan tanpa autentikasi, produk, reservation, replay byte yang sama, konflik key, isolasi tenant pada reservation dan produk, penolakan stok habis, konfirmasi, stok akhir, dan daftar audit. Smoke tidak menyimpan token, header Authorization, atau body lengkap ke laporan publik.

## Release engine

`now()` pada [engine.py](../src/release_lab/engine.py) memberi timestamp UTC. `nginx_config(record)` memvalidasi slot serta release ID, lalu membuat konfigurasi gateway dengan header metadata. Metadata tersebut berasal dari proxy lab; aplikasi ReserveFlow tidak diubah untuk menambahkan endpoint versi.

| Method `Engine` pada [engine.py](../src/release_lab/engine.py) | Penjelasan |
|---|---|
| `__init__` | Membaca environment, root, workspace, direktori state dan kedua lock; memvalidasi aksi, nomor build dan commit lab; membentuk release ID |
| `image_name` | Mengambil referensi image runtime yang telah dipatok pada lock versi |
| `report` | Menulis satu laporan JSON ke direktori laporan build |
| `state` | Membaca active, previous, dan history dari state; memakai state kosong pada deployment pertama |
| `credentials` | Memerlukan secret sesuai tahap; menolak karakter pemisah baris, API key yang tidak berbentuk 64 karakter hex, atau key tenant yang sama |
| `verify_upstream` | Memastikan checkout aplikasi ada, bersih, dan `HEAD` sesuai lock |
| `build_image` | Menjalankan build target Docker upstream sambil memberi label owner, source lab, source aplikasi, build, dan release |
| `test` | Membuat image tes, PostgreSQL sementara, dan runner; memerlukan database nyata, membuat laporan hasil Go/JUnit, lalu membersihkan container dan env file tes |
| `package` | Membangun target runtime, membaca image ID, dan menyimpan metadata package |
| `wait_database` | Menunggu `pg_isready` pada database yang dimaksud dengan batas waktu |
| `infrastructure` | Menyiapkan network, volume, dan PostgreSQL deployment milik lab; memakai kembali data yang ada |
| `start_release` | Membuat container slot dari image ID, menulis DSN privat dan hash key tenant; skenario tidak sehat memakai koneksi database yang sengaja gagal |
| `selected` | Memeriksa container berjalan dengan image ID, label release dan slot yang diharapkan |
| `ensure_release` | Membuat ulang container bila image/label/status tidak sesuai, kemudian menjalankan health gate |
| `gate` | Menunggu container terpilih serta `/healthz` sehat sebelum perubahan trafik |
| `direct_url` | Menunjuk port slot pada host jaringan daemon DinD agar kandidat dapat diperiksa sebelum cutover |
| `switch` | Menulis konfigurasi gateway, memvalidasi Nginx, melakukan reload, lalu menunggu metadata release baru; mencoba mengembalikan konfigurasi lama bila switch gagal |
| `gateway_matches` | Memeriksa health dan header release/slot melalui gateway setelah reload |
| `smoke` | Menjalankan HTTP smoke dan tetap menulis laporan request yang sempat dikerjakan ketika pemeriksaan gagal |
| `proof` | Mencatat hash byte state, active record, image ID container, status running, dan health/metadata gateway tanpa mengeluarkan environment privat |
| `deployment_record` | Memerlukan package dari build saat ini, memeriksa label image, lalu memasangkan image itu dengan slot tujuan |
| `append_attempt` | Menambah catatan percobaan deployment ke history JSON Lines dan melakukan flush/fsync |
| `deploy` | Mengunci state; menyamakan gateway dengan active release yang telah tersimpan; menyiapkan kandidat atau previous image; menjalankan gate serta smoke; switch; menyimpan state hanya setelah berhasil; memulihkan old release bila gagal setelah switch |
| `post` | Mengunci state dan menjalankan smoke tambahan melalui gateway pada active release yang tersimpan |
| `status` | Menghasilkan state dan proof terpilih sebagai JSON untuk pemeriksaan lab |
| `audit_reports` | Memeriksa allowlist laporan, menolak symlink/format rusak dan materi kredensial sebelum archive publik |

`deploy` menyimpan `switched` dan `recovered` secara terpisah. Kandidat tidak sehat berhenti sebelum switch. Gangguan post-check menghentikan kandidat setelah switch, sehingga jalur recovery perlu menghidupkan dan memilih kembali old release. State previous tetap menyimpan image ID meskipun container pada slot itu sudah ditimpa kandidat gagal.

## Laporan per build

| Laporan | Isi |
|---|---|
| `tests.json` dan `test-results.xml` | Hasil tes Go/PostgreSQL aktual dan tampilan JUnit |
| `package.json` | Release ID, image ID, source aplikasi, source lab dan nomor build |
| `candidate-smoke.json` | Pemeriksaan kandidat langsung sebelum cutover |
| `deployment.json` | Aksi, before/candidate/after, hasil switch, recovery, dan alasan gagal |
| `smoke.json` | Pemeriksaan melalui gateway sesudah cutover |
| `recovery-smoke.json` | Pemeriksaan melalui gateway setelah pemulihan otomatis |
| `proof.json` | Identitas active container serta keadaan gateway yang diamati |
| `postcheck.json` | Pemeriksaan tambahan melalui gateway pada stage terakhir |

Sebagian laporan hanya ada pada skenario yang melewati langkah terkait. Misalnya, rollback tidak menghasilkan package baru, dan kandidat yang gagal health gate belum menghasilkan smoke gateway kandidat.

## Compose, Dockerfile, dan konfigurasi Jenkins

| Berkas | Peran dan bagian yang perlu dibaca |
|---|---|
| [compose.yml](../compose.yml) | Mendefinisikan service `controller`, `engine`, `agent`, batas resource, health check, port loopback, network, dan named volume; `agent` memakai Docker client TLS serta secret koneksi dari env file privat |
| [controller.Dockerfile](../docker/controller.Dockerfile) | Mengambil image Jenkins berdigest, memasang seluruh plugin dari daftar versi tetap, lalu memeriksa checksum dan jumlah archive plugin |
| [agent.Dockerfile](../docker/agent.Dockerfile) | Mengambil inbound agent berdigest, memasang Python/Git, menyalin Docker CLI yang dipatok, menyiapkan direktori bersama, lalu kembali ke user Jenkins |
| [engine.Dockerfile](../docker/engine.Dockerfile) | Mengambil DinD berdigest dan menyiapkan kepemilikan direktori workspace/state agar agent dapat memakainya |
| [casc.yml](../jenkins/casc.yml) | Mematikan executor controller, mengatur login lokal, menolak anonymous read, membuat inbound node `builder` dengan label `release-builder` dan 1 executor, serta mengisi credentials dari environment controller |
| [plugins.txt](../jenkins/plugins.txt) | Daftar versi seluruh plugin yang dipasang, termasuk dependency wajib |
| [plugins.sha256](../jenkins/plugins.sha256) | Checksum archive yang diperiksa selama image controller dibangun |
| [plugins.lock.json](../jenkins/plugins.lock.json) | Catatan source update center, versi core yang diperlukan, URL resmi dan checksum setiap plugin |
| [.env.example](../.env.example) | Nama konfigurasi tanpa nilai secret produksi atau kredensial lab yang aktif |
| [.gitignore](../.gitignore) | Mengecualikan secret, state privat, cache, dependency, dan laporan runtime dari Git |
| [.dockerignore](../.dockerignore) | Mengeluarkan Git metadata, secret, state lokal dan berkas yang tidak dibutuhkan dari build context |
| [.gitattributes](../.gitattributes) | Menjaga akhir baris source dan script agar cocok saat berjalan di container Linux |
| [__init__.py](../src/release_lab/__init__.py) | Menandai direktori sebagai package Python; tidak menjalankan deployment saat import |

Compose menjalankan tiga container luar. Container aplikasi, Nginx, PostgreSQL deployment, serta database tes dibuat oleh daemon DinD. Karena itu, nama volume database di dalam DinD tidak muncul sebagai volume database pada Docker host luar. Volume `engine_data` milik Compose menyimpan data daemon beserta volume database di dalamnya.

## Konfigurasi lokal dan client Jenkins

| Fungsi pada [lab_config.py](../scripts/lab_config.py) | Penjelasan |
|---|---|
| `configuration` | Membaca pasangan key/value dari konfigurasi lokal; berhenti bila init belum dijalankan |
| `private_write` | Membuat direktori bila perlu, menulis UTF-8/LF, dan meminta mode berkas privat tanpa menampilkan isinya |
| `assert_no_secrets` | Menolak byte laporan yang memuat salah satu nilai secret lokal sebelum publikasi |
| `JenkinsClient.__init__` | Membatasi base URL pada controller lab lokal dan menyiapkan autentikasi serta cookie jar |
| `JenkinsClient.request` | Memerlukan path relatif controller; request yang menulis mengambil CSRF crumb dengan cookie yang sama; pesan error hanya menampilkan status/path |
| `JenkinsClient.json` | Mengambil response melalui client yang sama lalu membaca JSON |
| `JenkinsClient.ready` | Mengulang pemeriksaan API terautentikasi sampai controller siap atau timeout habis |

Fungsi `initialize(git_ref)` pada [init_env.py](../scripts/init_env.py) mempertahankan konfigurasi yang sudah ada, menghasilkan secret yang masih kosong dengan `secrets.token_hex(32)`, dan memvalidasi format 64 karakter hex. Referensi SCM hanya boleh `main` atau commit penuh. Fungsi menulis konfigurasi, placeholder env agent sebelum bootstrap, kredensial lokal, dan direktori sementara. Nilai secret tidak muncul pada hasil JSON command.

Fungsi `job_xml(values)` pada [bootstrap.py](../scripts/bootstrap.py) menyusun konfigurasi job Jenkins sebagai XML. Parameter berisi empat aksi lab. Definition `CpsScmFlowDefinition` menunjuk repository lab dan path Jenkinsfile, dengan branch `main` atau SHA yang dipatok.

Fungsi `bootstrap(timeout, wait_agent)` pada [bootstrap.py](../scripts/bootstrap.py) menunggu API terautentikasi dan memeriksa 0 executor controller. Mode biasa mengambil secret node secara privat lalu membuat atau memperbarui job. Mode `wait_agent` menunggu node `builder` online dan memeriksa tepat 1 executor. Fungsi tidak mencetak secret yang diterima.

## Script operasi dan verifikasi Jenkins

| Berkas | Alur |
|---|---|
| [Start.ps1](../scripts/Start.ps1) | Menyimpan environment proses semula, mengarahkan temporary/cache Python ke direktori lokal proyek, menjalankan init, memeriksa Docker, membangun tiga image berurutan kecuali `-NoBuild`, lalu bootstrap controller dan agent; blok `finally` mengembalikan direktori serta environment proses |
| [Stop.ps1](../scripts/Stop.ps1) | Menjalankan Compose `down` hanya pada project `jenkins-release-lab`, memeriksa exit code, dan mempertahankan volume |
| [Verify.ps1](../scripts/Verify.ps1) | Menyiapkan temporary/cache lokal, menjalankan `unittest`, lalu verifier runtime; setiap exit code gagal menghentikan script dan blok `finally` mengembalikan environment proses |

Script PowerShell tersebut berjalan langsung dari blok utama dan tidak mendefinisikan fungsi tambahan. Temporary/cache proyek tetap berada di direktori lab pada drive tempat repository berada; script tidak mengubah environment sistem permanen.

| Fungsi pada [verify_jenkins.py](../scripts/verify_jenkins.py) | Penjelasan |
|---|---|
| `api` | Mengirim request terautentikasi ke gateway loopback dan membaca payload JSON serta header release/slot tanpa mencetak token |
| `trigger` | Mengirim parameter aksi ke Jenkins, memvalidasi path queue, menunggu executable build, lalu menunggu hasil build aktual dengan timeout |
| `artifact` | Mengambil laporan JSON dari artifact build Jenkins, memeriksa materi secret, kemudian mem-parse hasilnya |
| `assert_active` | Mencocokkan state active dengan container berjalan, image ID, health gateway, header slot/release dan hash state |
| `verify` | Memeriksa executor, menjalankan lima build dengan expected result berbeda, memeriksa JUnit, membandingkan image/state, memeriksa HTTP 502 dan recovery, serta memastikan produk sentinel bertahan; hasil ditulis setelah guard secret lulus |

Sentinel pada verifier merupakan produk sintetis yang dibuat melalui API dengan stok 17. Setelah setiap build, verifier membaca produk yang sama dan memerlukan `onHand` serta `available` tetap 17. Jadi pemeriksaan memakai data aplikasi yang tersimpan pada PostgreSQL deployment, bukan tanda yang hanya hidup di memori script.

Sesudah kandidat tidak sehat memakai slot previous, container release sehat sebelumnya sudah tergantikan. Manual rollback harus membuat ulang image ID release pertama dan menghasilkan proof yang sama dengan record rilis pertama. Verifier juga mengamati health gateway dari host agar hasil tidak hanya bergantung pada laporan internal agent.

## Capture UI Jenkins

[capture-ui.mjs](../scripts/capture-ui.mjs) berjalan dari blok utama, memakai dependency Playwright pada [package.json](../package.json) dan versi yang dikunci pada [package-lock.json](../package-lock.json). Script membaca proof runtime yang sudah `PASS`, membatasi hostname Jenkins ke loopback, lalu membuka Chromium headless pada viewport desktop.

Urutannya adalah login, memeriksa lima build pada job overview, membuka hasil JUnit build sehat kedua, membuka console penolakan health gate, membuka artifact rollback yang memuat image ID asal, lalu membuka form parameter dan kembali tanpa memicu build baru. Empat screenshot memakai nama tetap. Callback `pageerror` mencatat exception JavaScript yang tidak tertangani. Blok `catch` menyamarkan nilai secret dari pesan gagal, dan `finally` selalu menutup browser.

Laporan UI berisi hasil, versi Jenkins yang dibaca verifier, daftar pemeriksaan, viewport, jumlah screenshot, dan page error. Lingkupnya adalah bukti desktop dari UI vendor yang tidak dimodifikasi. Laporan ini tidak mengklaim sertifikasi aksesibilitas atau pemeriksaan semua halaman Jenkins.

## Tes release engine

[test_release.py](../tests/test_release.py) memeriksa parser, berkas privat, batas Docker dan keputusan state deployment. `MemoryDocker` serta `SimulatedEngine` adalah test double dalam memori. Tes ini tidak dihitung sebagai bukti deployment Docker nyata; rangkaian Jenkins runtime memeriksa deployment yang sebenarnya.

| Fungsi tes pada [test_release.py](../tests/test_release.py) | Perilaku yang diperiksa |
|---|---|
| `test_actual_eight_passes` | Parser menghasilkan delapan testcase dari delapan baris hasil Go dalam fixture tes |
| `test_skip_is_not_a_successful_db_gate` | Satu tes skip menggagalkan gate dan muncul sebagai skipped pada JUnit |
| `test_missing_test_is_reported_as_missing` | Keluaran kosong tidak berubah menjadi hasil lulus |
| `test_nonzero_process_overrides_pass_lines` | Exit code proses gagal tetap menggagalkan hasil walaupun semua baris tes terlihat lulus |
| `test_untrusted_stdout_is_never_copied_to_junit` | Parser tidak menyalin stderr/stdout bebas yang dapat berisi DSN privat ke laporan |
| `test_private_file_atomic_replace_and_mode` | Penggantian env file menghasilkan isi baru tanpa file sementara yang tertinggal; mode POSIX diperiksa pada OS yang mendukungnya |
| `test_newline_credential_injection_rejected` | Secret dengan newline tidak dapat menyisipkan pasangan env tambahan |
| `test_state_lock_is_portable` | Penulisan JSON di dalam lock dapat dibaca kembali |
| `test_unowned_container_cannot_be_removed` | Label owner yang tidak sesuai menghentikan operasi remove |
| `test_docker_error_redacts_private_stderr_and_argv` | Pesan kegagalan Docker tidak memuat secret dari argumen atau stderr |
| `test_nginx_metadata_is_validated` | Release ID yang dapat menyisipkan konfigurasi ditolak |
| `test_two_healthy_releases_alternate_slots_and_preserve_previous_image` | Dua deployment bergantian slot dan menyimpan previous image ID |
| `test_unhealthy_candidate_cannot_change_committed_state` | Health gate gagal mempertahankan byte state dan active release |
| `test_rollback_recreates_image_after_previous_slot_overwritten` | Rollback membuat kembali previous image walaupun slot telah diisi kandidat gagal |
| `test_postcutover_fault_recovers_old_gateway_before_error` | Recovery memulihkan gateway dan old container sebelum engine mengembalikan kegagalan |
| `test_proof_hashes_actual_committed_state_bytes` | Proof memuat SHA-256 dari byte state yang benar-benar tersimpan, bukan JSON yang disusun ulang |
| `test_interrupted_gateway_is_reconciled_before_inactive_slot_is_replaced` | Percobaan berikutnya menyamakan gateway dengan state committed sebelum mengubah slot kandidat |
| `test_no_previous_rollback_fails_without_claiming_success` | Rollback tanpa previous berhenti dengan laporan gagal |
| `test_secret_scanner_blocks_credentials_and_unexpected_reports` | Archive guard menolak materi secret dan nama laporan di luar allowlist |

Helper `ResultTests.output` membuat fixture baris hasil Go. `MemoryDocker.__init__`, `image`, `assert_owned`, dan `stop` menyimpan metadata container dalam memori. Override `SimulatedEngine.infrastructure`, `start_release`, `gate`, `switch`, `smoke`, dan `proof` mengganti efek eksternal dengan state tes. `DeploymentTests.setUp` membuat direktori sementara; `engine` menyusun environment fixture; `deploy` menahan stdout tes; `two_healthy` menyiapkan baseline dua release.

[test_smoke.py](../tests/test_smoke.py) menyalakan HTTP server sungguhan pada loopback, dengan kontrak response sebagai fixture. Ini menguji transport dan pemeriksaan client smoke; server tersebut bukan aplikasi ReserveFlow dan tidak memakai PostgreSQL.

| Fungsi tes pada [test_smoke.py](../tests/test_smoke.py) | Perilaku yang diperiksa |
|---|---|
| `test_twelve_real_http_requests_match_upstream_smoke` | Client mengirim dua belas request pada fixture HTTP dan mencatat status yang sesuai |
| `test_http_replay_without_replayed_header_fails` | Response replay tanpa header yang diwajibkan menggagalkan kontrak |
| `test_proxy_metadata_mismatch_fails_first_request` | Header release yang tidak sesuai expected release menghentikan smoke |
| `test_health_uses_actual_json_contract` | Health memeriksa payload JSON, bukan status HTTP saja |
| `test_real_gateway_failure_preserves_http_status_as_evidence` | Response HTML 502 tetap tercatat sebagai HTTP 502 pada laporan gagal |

`ContractHandler.log_message` menahan log fixture, `do_GET` dan `do_POST` meneruskan request ke `respond`, dan `respond` menghasilkan respons sesuai skenario tes. `HTTPContractTests.setUp` menyalakan server pada port sementara; `tearDown` menghentikan server dan thread setelah setiap tes.

## Workflow GitHub Actions

[verify.yml](../.github/workflows/verify.yml) hanya dipicu oleh push `main` yang relevan atau pemanggilan manual. Workflow memerlukan izin repository baca. Runner memasang Python/Node, menjalankan tes engine, lalu menyiapkan stack Jenkins yang sama. Verifier mengirim build melalui API Jenkins dan memeriksa hasil aktual. Screenshot diambil setelah rangkaian selesai.

Ekspor image memerlukan pemanggilan workflow manual dengan input boolean `export_runtime_images` bernilai `true`. Nilai awalnya `false`, sehingga push biasa melewati ekspor dan upload image. Bila diminta, tahap setelah build dan sebelum startup mengekspor tiga image hasil Compose sebagai `runtime-images` dengan retensi satu hari. `docker save` mengekspor image, bukan volume atau environment runtime container. Artifact ini terpisah dari bukti pengujian; kegagalan ekspor tidak mengubah hasil skenario Jenkins.

Sebelum upload bukti, workflow memeriksa dua JSON publik terhadap secret lokal dan hanya menyebut path bukti yang diperbolehkan. Tidak ada upload glob seluruh direktori lokal. Tahap cleanup selalu memakai Compose `down` tanpa menghapus volume. Kebijakan ini menjaga contoh workflow tetap terfokus pada lab yang dimiliki repository tersebut.
