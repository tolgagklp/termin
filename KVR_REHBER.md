# Ehliyet: yabancı ehliyetin dönüştürülmesi

**Hizmet:** [Umschreibung eines ausländischen Führerscheins](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/) · **Randevu:** [KVR Terminvereinbarung](https://stadt.muenchen.de/buergerservice/terminvereinbarung.html) · **Saat dilimi:** Münih (Europe/Berlin).

| Ne zaman yeni randevu açılıyor? | Gün | Münih saati | KVR'nin açıklaması |
| --- | --- | --- | --- |
| Aynı gün için | Pazartesi–Cuma | **07:00–08:00** | Kapasiteye göre o güne ait boş saatler açılıyor; her gün boş saat garantisi yok. |
| 14 gün önceden | Pazartesi–Cuma | **07:30–08:30** | 14 gün ileri tarihli randevular açılıyor. |

Bu saatler, randevu ekranındaki **“Wann gibt es neue Termine?”** açıklamasından (20.10.2026 tarihli ekran görüntüm) alınmıştır. İki aralık **07:30–08:00** arasında çakışır; boş saatler sonradan da kaybolup geri gelebilir.

| Konu | Kısa bilgi |
| --- | --- |
| Resmî başvuru zamanı | KVR'ye göre yabancı ehliyetle Almanya'daki ilk kayıttan sonra **6 ay** araç kullanılabilir; ardından dönüştürülmesi gerekir. Bu süre dolmadan başvuruyu planlamalıyım. EU/EWR ehliyetleri için ayrı kurallar vardır. [Kaynak](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/). |
| Yer ve işlem | **Führerscheinstelle, Garmischer Straße 19–21.** Randevu sayfasında “Umschreibung eines ausländischen Führerscheins” seçilir. |
| Belgeler ve işlem süresi | Belgeleri [resmî listeden](https://stadt.muenchen.de/service/info/fuhrerscheinstelle/1071898/) kontrol etmeliyim. KVR, eksiksiz belgelerden sonra işlem süresini **14 haftaya kadar** bildiriyor. |
| Benim tarih tercihim | **30 Ekim 2026'ya kadar:** herhangi bir saat. **2–20 Kasım:** erken sabah veya geç saat. **Son sınır: 24 Kasım 2026.** Bunlar KVR kuralı değil, benim tercihlerim. |
| Benim gözlemim | **3 Kasım 2026** için birden çok öğleden sonra saati gördüm; sonra boş saat kalmadı. Başka bir taramada yalnız **15:40** göründü. Görünen kontenjan hızla değişiyor. |
| Rezervasyon akışı | Uygun gün/saat → iletişim bilgileri → özet ekranında **elektronik haberleşme onayı** → “Termin reservieren”. Gelen e-postadaki bağlantıyı **ben** etkinleştiririm. |
| Botun şu anki durumu | Ehliyet botu uygun saatleri izliyor ve bildiriyor. `.env` içindeki `AUTO_BOOK_ENABLED=false` olduğu sürece rezervasyon göndermiyor. |

| Yerel komutlar — proje klasöründe PowerShell | Komut |
| --- | --- |
| İkisini aynı terminalde hemen başlat | `.\.venv\Scripts\python.exe -m src.run_both` |
| İkisini sonraki 06:15'te başlat | `.\.venv\Scripts\python.exe -m src.run_both --start-at 06:15` |
| Belirli gün ve saatte başlat | `.\.venv\Scripts\python.exe -m src.run_both --start-at "2026-10-21 06:15"` |
| Başlatmadan planı gör | `.\.venv\Scripts\python.exe -m src.run_both --start-at 06:15 --plan` |
| İzlemeyi başlat | `.\.venv\Scripts\python.exe -m src.driver_license_monitor` |
| Son durumu gör | `.\.venv\Scripts\python.exe -m src.driver_license_monitor --status` |
| Günlüğü canlı izle | `Get-Content .\monitor\monitor.log -Wait -Tail 30` |

Tek komut, iki ayrı görev açar. Aynı terminalde satırların başında **[Ehliyet]** veya **[Notfall]** görünür; kayıt ve koşulları ayrı kalır. `--start-at 06:15` bugünkü saat geçtiyse **yarın** 06:15 anlamına gelir. Tam tarih geçmişteyse komut hata verir. `--plan` görevleri başlatmaz. **Ctrl+C** ikisini de durdurur. Başlatıcı `monitor/runner.log`, ehliyet `monitor/monitor.log`, Notfall `monitor/notfall/reminder.log` dosyasına yazar. Başlatıcı açıkken Windows'un boşta uyumasını engeller; kapağı kapatmak, bilgisayarı elle uyutmak veya yeniden başlatmak programı keser.

İnternet kesilirse ehliyet izleyicisi geçici bağlantı hatasında **1, 2, 4, 8 ve en fazla 15 dakika** aralıklarla yeniden denenir. Böyle bir kesinti Notfall hatırlatıcısını durdurmaz. CAPTCHA, erişim engeli veya başka kalıcı hata halinde ehliyet görevi durur ve nedenini gösterir; site koruması aşılmaz. `AUTO_BOOK_ENABLED=false` kaldığı sürece uygun saati bildirse bile rezervasyon göndermez.

# Blue Card: öğrenci/mezun Notfall randevusu

**Hizmet:** [Notfall-Hilfe Aufenthaltstitel – Studierende, Arbeitsplatzsuche nach Studium oder erstmalige Beschäftigung nach Studium](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/) · **Randevu:** [KVR Terminvereinbarung](https://stadt.muenchen.de/buergerservice/terminvereinbarung.html) · **Saat dilimi:** Münih (Europe/Berlin).

| Gün | 10 dk önce | 2 dk önce | Resmî açılış ve son mesaj | Hangi randevu? |
| --- | --- | --- | --- | --- |
| Pazartesi, çarşamba, cuma | **06:20** | **06:28** | **06:30** | Yalnızca **o gün** için. |
| Salı, perşembe | **07:20** | **07:28** | **07:30** | Yalnızca **o gün** için. |
| Hafta sonu | — | — | — | Bu kategori için açıklanmış açılış saati yok. |

KVR'nin [hizmet sayfası](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/) ve randevu ekranındaki **“Wann gibt es neue Termine?”** açıklaması bu saatleri veriyor. Randevu ücretsiz; ücretli üçüncü taraf tekliflerini kullanmamalıyım.

| Konu | Kısa bilgi |
| --- | --- |
| Bana uygun kategori | Hâlen öğrenci olduğum için **öğrenci/mezun Notfall** hizmetini seçiyorum; “Beschäftigte, Angehörige” farklı kategoridir. |
| Acil durum şartı | Yalnızca **belgelenebilir acil durumlar** inceleniyor. İş veya iş teklifi kaybı tehlikesi örneklerden biri; acil olup olmadığına KVR karar veriyor. [Öğrenci hizmeti](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/). |
| İşe başlama ve Blue Card | Yalnızca işe başlamak acil durum sayılmıyor. Notfall gişesi Blue Card verme/uzatma işlemini yapmıyor. [Blue Card başvurusu](https://stadt.muenchen.de/service/en-GB/info/servicestelle-fur-zuwanderung-und-einburgerung/10422541/) ayrı olarak çevrim içi veya postayla yapılır; incelemeden sonra KVR görüşme randevusu verir. [Genel Notfall açıklaması](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10339065/). |
| Benim gözlemim | **20 Ekim 2026:** İnsan doğrulamasını elle tamamlayınca tarih ekranı açıldı; **boş randevu yoktu**. Sayfa yenilenince doğrulama yeniden istendi. |
| Telegram ne yapıyor? | **Aynı bot**, resmî açılıştan **10 dakika önce, 2 dakika önce ve açılışta** bağlantılı hatırlatma gönderiyor. **Boş saatleri kontrol etmiyor, rezervasyon yapmıyor.** Gönderim kaydı tekrar mesajı önlüyor. |
| Boş randevu bulamazsam | KVR servis telefonu: **+49 89 233-96010**. [Kaynak](https://stadt.muenchen.de/service/info/servicestelle-fur-zuwanderung-und-einburgerung/10338844/). |

| Yerel komutlar — proje klasöründe PowerShell | Komut |
| --- | --- |
| İki görevi aynı terminalde başlat | `.\.venv\Scripts\python.exe -m src.run_both` |
| Hatırlatıcıyı başlat | `.\.venv\Scripts\python.exe -m src.notfall_reminder` |
| Gelecek saatleri gör | `.\.venv\Scripts\python.exe -m src.notfall_reminder --status` |
| Günlüğü canlı izle | `Get-Content .\monitor\notfall\reminder.log -Wait -Tail 30` |

Bağlantı kesilince Notfall başarısız Telegram denemesinden sonra 20 saniye bekleyip yeniden dener. Bağlantı geç dönerse aynı açılışa ait geçmiş uyarıları topluca göndermez; yalnızca hâlâ geçerli **en son** uyarıyı gönderir. Açılış mesajı açılıştan sonra en çok 10 dakika boyunca denenir; daha geç kalınan bir açılış için eski mesaj gönderilmez. Gönderilen her mesaj `monitor/notfall/reminders.state.json` içine yazılır ve program yeniden başlasa da tekrarlanmaz. Notfall kayıtları `monitor/notfall/` içindedir; bu klasör ve gizli `.env` Git'e eklenmez. Notfall için ayrı bitiş tarihi gerekiyorsa `.env` içine `NOTFALL_REMINDER_UNTIL=YYYY-MM-DD` yazabilirim.
