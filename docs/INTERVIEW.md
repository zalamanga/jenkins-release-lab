# Menjelaskan proyek saat interview

## Penjelasan singkat

Saya membuat lab Jenkins untuk merilis ReserveFlow API. Controller mengelola job, sementara satu agent menjalankan tes Go dengan PostgreSQL, membangun image, dan melakukan deployment blue-green. Saya menguji kandidat gagal sebelum cutover dan gangguan setelah cutover. Laporan Jenkins menunjukkan apakah release ditolak atau dipulihkan, dan sentinel database membuktikan data deployment tetap ada.

Source ReserveFlow dipatok pada satu commit. Dua release sehat adalah dua eksekusi rilis dari source yang sama. Saya tidak mengklaim bahwa demonstrasi ini mengirim dua fitur aplikasi baru.

## Mengapa Jenkins ketika ada GitHub Actions?

Tujuannya mempelajari controller, node, executor, JCasC, credentials, pipeline dari SCM, JUnit, artifact, dan build history Jenkins. GitHub Actions hanya menyiapkan stack lab serta memeriksa Jenkins melalui API. Jenkins sungguhan tetap menjadwalkan dan menjalankan pipeline pada agent.

## Mengapa controller memakai 0 executor?

Controller menyimpan konfigurasi dan bukti build. Saya memberikan pekerjaan build kepada agent agar build tidak berjalan pada built-in node. Agent memiliki satu executor karena lab memakai sumber daya terbatas dan state deployment perlu berubah secara berurutan. Rekomendasi ini mengikuti [Jenkins controller isolation](https://www.jenkins.io/doc/book/security/controller-isolation/).

## Apa bedanya JCasC dan Jenkinsfile?

JCasC menyiapkan Jenkins, termasuk node dan kredensial. Bootstrap membuat job Pipeline from SCM, sedangkan Jenkinsfile menjelaskan langkah build. Dengan pemisahan ini, reviewer dapat membedakan perubahan pengaturan Jenkins dari perubahan cara aplikasi diuji dan dirilis. Job membaca Jenkinsfile dari SCM agar definisi pipeline memiliki riwayat versi.

## Apa yang benar-benar diuji?

Tes Go menggunakan PostgreSQL nyata untuk memeriksa transaksi, idempotency, tenant isolation, expiry, pagination, dan konflik konkurensi ReserveFlow. HTTP smoke mengirim request ke deployment melalui gateway untuk memeriksa autentikasi, pembuatan stok, reservation, replay, konflik, isolasi tenant, konfirmasi, dan audit.

Jumlah yang benar-benar dieksekusi dan hasil setiap build tercatat pada [verifikasi](VERIFICATION.md). Parser JUnit menolak keluaran yang melewati tes atau tidak memuat tes wajib. Saya membedakan tes unit release engine dari tes integrasi aplikasi dan request smoke.

## Mengapa memakai image ID saat rollback?

Tag adalah nama yang dapat diarahkan ke image lain. Image ID mengidentifikasi image lokal yang sudah dibangun. State previous release menyimpan image ID tersebut, sehingga engine dapat membuat ulang container ketika container sebelumnya sudah tidak ada. Kandidat gagal sengaja memakai slot previous dan mengganti container release lama; uji rollback kemudian memeriksa pembuatan ulang image tersebut.

Rollback masih bergantung pada image yang tersedia pada daemon lab. Proyek ini tidak menyediakan registry atau kebijakan retensi image produksi. Menghapus image yang diperlukan dapat membuat rollback gagal.

## Bagaimana membuktikan health gate bekerja?

Saya mencatat active release sebelum menjalankan `DEPLOY_UNHEALTHY`. Kandidat harus gagal, build harus berstatus `FAILURE`, dan active release setelah build harus sama. Gateway juga harus tetap melayani release sehat. Build gagal saja belum membuktikan active release tidak berubah.

## Mengapa build tetap gagal setelah auto recovery berhasil?

Deployment kandidat gagal memenuhi pemeriksaan setelah cutover. Engine memulihkan layanan, tetapi hasil rilis tetap gagal agar operator melihat insidennya. Laporan memisahkan hasil deployment, tindakan recovery, dan keadaan layanan setelah recovery.

## Apakah rollback mengembalikan database?

Tidak. Blue dan green memakai database deployment yang sama. Engine mengganti container dan tujuan gateway, lalu memeriksa sentinel sintetis pada database yang sama. Ini cocok untuk source aplikasi yang dipatok pada demonstrasi ini. Untuk perubahan skema produksi, saya perlu rancangan migrasi yang kompatibel ke belakang, backup yang diuji, dan prosedur recovery data terpisah.

## Mengapa DinD dan mutual TLS?

Saya ingin perintah Docker agent menarget daemon lab tersendiri tanpa memasang socket Docker host. Mutual TLS mengautentikasi client dan daemon. Container daemon DinD tetap privileged, sehingga saya tidak menyebutnya batas keamanan produksi untuk menjalankan kode tak tepercaya. Sertifikat client juga perlu dijaga karena pemegangnya dapat mengendalikan daemon lab. Lihat [Docker daemon TLS](https://docs.docker.com/engine/security/protect-access/).

## Apa yang akan diubah untuk produksi?

Saya akan menyesuaikan desain dengan kebutuhan deployment: agent yang terisolasi, registry dengan retensi dan kontrol akses, secret manager, akses Jenkins melalui TLS, otorisasi yang lebih rinci, backup controller dan database yang diuji, migrasi skema, serta monitoring. Lab ini belum membuktikan high availability, kapasitas produksi, atau zero downtime. Saya melaporkan pemeriksaan yang benar-benar dijalankan tanpa mengubahnya menjadi klaim SLA.

## Urutan demo yang bisa diperiksa reviewer

1. Tunjukkan konfigurasi controller dan agent, termasuk executor.
2. Buka job, parameter `ACTION`, Jenkinsfile dari SCM, dan build history.
3. Buka build sehat untuk melihat stage, JUnit, dan artifact.
4. Buka build kandidat tidak sehat; cocokkan active release sebelum dan sesudah.
5. Buka manual rollback; cocokkan previous image ID dengan image yang aktif kembali.
6. Buka build post-check gagal; tunjukkan hasil `FAILURE` dan bukti recovery.
7. Buka laporan sentinel database dan jelaskan batas bukti tersebut.

Screenshot mendukung penjelasan UI. JSON, XML, nomor build, image ID, serta respons API mendukung pemeriksaan hasil teknis.
