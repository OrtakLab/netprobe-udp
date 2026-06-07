# NetProbe — Sunum Metni (5 Dakika, 3 Slayt)

**Kişi 1 (K1):** Giriş + Mimari + Demo  
**Kişi 2 (K2):** Protokol + Sonuçlar + Kapanış  

---

## SLAYT 1 — Proje Tanıtımı ve Mimari

**Slayt içeriği (bullet):**
- NetProbe: UDP üzerinde güvenilir dosya aktarımı
- Stop-and-Wait ARQ + Go-Back-N ARQ
- Ağ simülasyonu (paket kaybı, gecikme)
- Web arayüzü + performans analizi

---

**K1 konuşur (~1 dk 30 sn):**

> Merhaba, biz Grup [X]. Projemizin adı NetProbe.
>
> Bildiğiniz gibi UDP protokolü hızlı ama güvenilir değil — paketler kaybolabilir, sıra bozulabilir. Bizim amacımız UDP'nin üzerine bir güvenilirlik katmanı inşa etmek.
>
> Sistem dört ana bileşenden oluşuyor: gönderici istemci, alıcı sunucu, bir günlükleme modülü ve bir analiz aracı. Bunların hepsini Flask tabanlı bir web arayüzüyle yönetebiliyoruz.
>
> İstemci dosyayı parçalara böler, UDP ile gönderir. Sunucu parçaları toplar, yeniden birleştirir, SHA-256 ile dosya bütünlüğünü doğrular. Tüm olaylar — gönderme, alındı, zaman aşımı, yeniden iletim — CSV dosyasına kaydediliyor.
>
> Şimdi [Kişi 2] protokolleri anlatacak.

---

## SLAYT 2 — Protokol Tasarımı ve Sonuçlar

**Slayt içeriği (bullet):**
- DataPacket: `type | seq | total | len | CRC32 | payload`
- Stop-and-Wait: tek paket → ACK bekle → sıradaki
- Go-Back-N: pencere kadar gönder, kayıpta tümünü tekrarla
- 4 deney: paket boyutu / timeout / kayıp oranı / dosya boyutu

---

**K2 konuşur (~1 dk 45 sn):**

> Protokol katmanında iki paket türü var. Veri paketi 15 baytlık başlık taşıyor: sıra numarası, toplam paket sayısı ve CRC32 sağlama toplamı. Alındı paketi ise 9 bayt.
>
> İki ARQ protokolü uyguladık. Stop-and-Wait'te gönderici her paketi gönderdikten sonra ACK bekler — basit ama yavaş. Go-Back-N'de gönderici pencere boyutu kadar paketi art arda gönderir; kayıp olursa penceredeki tüm paketleri yeniden iletir. Bu, ağ kapasitesini çok daha verimli kullanıyor.
>
> Dört deney senaryosu yürüttük: paket boyutunun, timeout değerinin, paket kayıp oranının ve dosya boyutunun performansa etkisini ölçtük. Sonuçlara göre: Go-Back-N, yüksek gecikmeli ortamlarda Stop-and-Wait'e kıyasla belirgin biçimde daha yüksek throughput sağladı. Kayıp oranı yüzde yirmiye çıktığında Stop-and-Wait'in tamamlanma süresi üç katına çıkarken Go-Back-N çok daha kararlı kaldı.

---

## SLAYT 3 — Demo ve Kapanış

**Slayt içeriği (bullet):**
- Canlı demo: web arayüzü
- Throughput / Goodput / RTT / Yeniden İletim Oranı
- GitHub: [repo linki]
- Sonuç: UDP üzerinde güvenilir, ölçülebilir aktarım

---

**K1 konuşur (~1 dk 15 sn):**

> Şimdi sistemi canlı olarak göstereceğim.
>
> *(Web arayüzünü aç — http://localhost:8080)*
>
> Sunucuyu başlatıyoruz, paket kayıp oranını yüzde on olarak ayarlıyoruz. Bir dosya seçiyoruz ve aktarımı başlatıyoruz. Sağ tarafta anlık olarak throughput, goodput, ortalama RTT ve yeniden iletim oranını görebilirsiniz. Aktarım tamamlandıktan sonra analiz butonuna basıyoruz — grafik otomatik olarak üretiliyor.
>
> Projenin tüm kaynak koduna README ile birlikte GitHub üzerinden erişilebilir.

**K2 konuşur (~30 sn):**

> Özetle: UDP üzerinde iki farklı ARQ protokolü başarıyla uyguladık, ağ koşullarını simüle edebildik ve tüm performans metriklerini ölçüp görselleştirebildik. Dinlediğiniz için teşekkürler. Sorularınız varsa memnuniyetle yanıtlarız.

---

## Süre Tahmini

| Bölüm         | Konuşan | Süre       |
|---------------|---------|------------|
| Slayt 1       | K1      | ~1 dk 30 sn|
| Slayt 2       | K2      | ~1 dk 45 sn|
| Slayt 3 (demo)| K1      | ~1 dk 15 sn|
| Slayt 3 (kapanış)| K2   | ~30 sn     |
| **Toplam**    |         | **~5 dk**  |

---

## Slayt Tasarım Notları

- **Slayt 1:** Sistem mimarisi ASCII diyagramı veya basit ok diyagramı.
- **Slayt 2:** İki protokol yan yana karşılaştırma tablosu + paket yapısı.
- **Slayt 3:** Web arayüzü ekran görüntüsü + grafik örneği + GitHub QR kodu.

Demo yapılamıyorsa Slayt 3'e web arayüzünün ekran görüntüsünü ve üretilen grafikleri koyun.
